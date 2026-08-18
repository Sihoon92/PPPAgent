#!/usr/bin/env python3
"""Stage 0 — environment probe.

Reports what this machine can and cannot do, without importing anything heavy
and without touching the network unless --net is passed.

Run:  python smoketest/00_env_probe.py [--net]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "_result_00_env.json"

OK, WARN, FAIL = "OK  ", "WARN", "FAIL"


def row(status: str, name: str, detail: str = "") -> None:
    print(f"  [{status}] {name:<26} {detail}")


def has_module(name: str) -> bool:
    """Check importability without executing the module."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def run(cmd: list[str], timeout: int = 20) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or p.stderr).strip()
    except FileNotFoundError:
        return 127, "not found"
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s"


def tcp_probe(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", action="store_true", help="also probe outbound network")
    args = ap.parse_args()

    result: dict = {}

    print("\n=== Stage 0: 환경 프로브 ===\n")

    # ── 1. interpreter ────────────────────────────────────────────────
    print("[1] 파이썬")
    py_ok = sys.version_info >= (3, 11)
    row(OK if py_ok else FAIL, "version", f"{platform.python_version()} (>=3.11 필요)")
    row(OK, "executable", sys.executable)
    row(OK, "platform", f"{platform.system()} {platform.release()}")
    result["python"] = {
        "version": platform.python_version(),
        "ok": py_ok,
        "executable": sys.executable,
    }

    # ── 2. packages ───────────────────────────────────────────────────
    print("\n[2] 파이썬 패키지")
    required = ["pptagent", "pptagent_pptx", "pptx", "PIL", "lxml", "jinja2", "yaml"]
    optional = {
        "fastmcp": "MCP 서버 (5단계)",
        "mcp": "MCP 클라이언트 (5단계)",
        "html2image": "표→이미지 변환 (선택 도구)",
        "playwright": "HTML 렌더링 (자유형 경로 전용)",
        "openai": "LLM 호출 (5단계)",
        "docker": "도커 SDK (4단계)",
    }
    pkgs = {}
    for m in required:
        found = has_module(m)
        pkgs[m] = found
        row(OK if found else FAIL, m, "필수")
    for m, why in optional.items():
        found = has_module(m)
        pkgs[m] = found
        row(OK if found else WARN, m, why)
    result["packages"] = pkgs

    # ── 3. external binaries ──────────────────────────────────────────
    print("\n[3] 외부 실행 파일")
    bins = {}
    for b, why in [
        ("docker", "4단계 sandbox"),
        ("node", "html2pptx (자유형 경로 전용)"),
        ("npm", "html2pptx (자유형 경로 전용)"),
        ("pdfinfo", "poppler / PDF 첨부"),
        ("soffice", "pptx→이미지 (템플릿 *제작* 전용)"),
        ("unoconvert", "pptx→이미지 (템플릿 *제작* 전용)"),
    ]:
        p = shutil.which(b)
        bins[b] = p
        row(OK if p else WARN, b, p or f"없음 — {why}")
    result["binaries"] = bins

    # ── 4. docker daemon ──────────────────────────────────────────────
    print("\n[4] 도커 데몬")
    docker_ok = False
    images: list[str] = []
    if bins["docker"]:
        rc, out = run(["docker", "info", "--format", "{{.ServerVersion}}"])
        docker_ok = rc == 0
        row(OK if docker_ok else FAIL, "docker info", out.splitlines()[0] if out else "")
        if docker_ok:
            rc, out = run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"])
            images = [ln for ln in out.splitlines() if ln.strip()]
            want = "deeppresenter-sandbox"
            hit = [i for i in images if want in i]
            row(OK if hit else WARN, want, ", ".join(hit) or "이미지 없음 (4단계에서 필요)")
    else:
        row(FAIL, "docker", "실행 파일 없음")
    result["docker"] = {"daemon": docker_ok, "images": images}

    # ── 5. bundled templates ──────────────────────────────────────────
    print("\n[5] 번들 템플릿")
    tpl_dir = REPO / "pptagent" / "templates"
    tpls: dict[str, dict] = {}
    if tpl_dir.is_dir():
        for d in sorted(p for p in tpl_dir.iterdir() if p.is_dir()):
            need = ["source.pptx", "slide_induction.json", "image_stats.json", "description.txt"]
            missing = [f for f in need if not (d / f).exists()]
            tpls[d.name] = {"complete": not missing, "missing": missing}
            row(OK if not missing else FAIL, d.name, "완전" if not missing else f"누락: {missing}")
    else:
        row(FAIL, "templates/", f"{tpl_dir} 없음")
    result["templates"] = tpls

    # ── 6. network (opt-in) ───────────────────────────────────────────
    print("\n[6] 네트워크" + ("" if args.net else " (--net 옵션으로 활성화)"))
    net: dict[str, bool] = {}
    if args.net:
        for host, port in [
            ("pypi.org", 443),
            ("registry-1.docker.io", 443),
            ("api.openai.com", 443),
        ]:
            reachable = tcp_probe(host, port)
            net[f"{host}:{port}"] = reachable
            row(OK if reachable else WARN, host, "연결됨" if reachable else "차단/도달 불가")
        # local LLM endpoints commonly used inside a corporate network
        for host, port in [("127.0.0.1", 11434), ("127.0.0.1", 8000), ("127.0.0.1", 7811)]:
            reachable = tcp_probe(host, port, timeout=1.0)
            net[f"{host}:{port}"] = reachable
            if reachable:
                row(OK, f"local {port}", "LLM 후보 발견")
    else:
        row(WARN, "skipped", "폐쇄망 여부를 확인하려면 --net")
    result["network"] = net

    # ── verdict ───────────────────────────────────────────────────────
    print("\n=== 판정 ===\n")
    core = all(pkgs.get(m) for m in required) and py_ok and bool(tpls)
    verdict = {
        "1단계 템플릿 로드": core,
        "2단계 내용 검증": core,
        "3단계 슬라이드 생성 (LLM 없이)": core,
        "4단계 도커 sandbox": docker_ok,
        "5단계 MCP 전 구간 (LLM 필요)": core and pkgs.get("fastmcp") and pkgs.get("mcp"),
    }
    for k, v in verdict.items():
        row(OK if v else FAIL, k, "가능" if v else "불가")
    result["verdict"] = {k: bool(v) for k, v in verdict.items()}

    print("\n  참고: soffice/LibreOffice는 템플릿을 *새로 만들 때*만 필요합니다.")
    print("        번들 템플릿을 쓰는 한 없어도 1~3단계는 전부 동작합니다.\n")

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  결과 저장: {OUT}\n")
    return 0 if core else 1


if __name__ == "__main__":
    sys.exit(main())
