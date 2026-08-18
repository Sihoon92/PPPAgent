#!/usr/bin/env python3
"""Stage 4 — is the Docker sandbox usable?

The sandbox MCP server is the only Docker dependency in the template path. It
supplies read_file/write_file/execute_command to the PPTAgent role
(deeppresenter/roles/PPTAgent.yaml). Stages 1-3 do not need it; the full agent
loop does.

This script checks the daemon, looks for the image, and — if present — actually
speaks MCP to it over stdio and calls list_directory in a scratch workspace.

Run:  python smoketest/04_docker_sandbox.py
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "_result_04_docker.json"
IMAGE = "deeppresenter-sandbox"


def run(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or p.stderr).strip()
    except FileNotFoundError:
        return 127, "not found"
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s"


async def probe_sandbox_mcp(workspace: Path) -> dict:
    """Start the sandbox image as an MCP stdio server and list its tools."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    name = f"smoketest-{uuid.uuid4().hex[:8]}"
    params = StdioServerParameters(
        command="docker",
        args=[
            "run", "--init", "--name", name, "-i", "--rm",
            "-v", f"{workspace}:{workspace}",
            "-w", str(workspace),
            IMAGE,
        ],
        env=None,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), timeout=120)
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            result: dict = {"tools": names}

            if "list_directory" in names:
                r = await asyncio.wait_for(
                    session.call_tool("list_directory", {"path": str(workspace)}),
                    timeout=60,
                )
                text = "".join(
                    c.text for c in r.content if getattr(c, "type", "") == "text"
                )
                result["list_directory"] = text[:400]
            return result


def main() -> int:
    print("\n=== Stage 4: 도커 sandbox ===\n")
    report: dict = {}

    # ── 1. docker binary + daemon ────────────────────────────────────
    where = shutil.which("docker")
    print(f"  docker 실행 파일: {where or '없음'}")
    if not where:
        print("\n  [FAIL] docker 명령을 찾을 수 없습니다.")
        print("         WSL 안에서 실행 중인지, docker engine이 그 배포판에 설치됐는지 확인하세요.\n")
        OUT.write_text(json.dumps({"docker": False}, ensure_ascii=False, indent=2), encoding="utf-8")
        return 1

    rc, out = run(["docker", "info", "--format", "{{.ServerVersion}}"])
    if rc != 0:
        print(f"  [FAIL] 데몬 응답 없음: {out.splitlines()[0] if out else rc}")
        print("         sudo service docker start  또는  systemctl --user start docker 를 확인하세요.\n")
        OUT.write_text(json.dumps({"docker": True, "daemon": False, "error": out[:300]},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
        return 1
    print(f"  [OK  ] 데몬 응답: server {out}")
    report["daemon"] = out

    # ── 2. image present? ────────────────────────────────────────────
    rc, out = run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"])
    images = [ln for ln in out.splitlines() if ln.strip()]
    hit = [i for i in images if IMAGE in i]
    report["images"] = images
    if not hit:
        print(f"  [WARN] '{IMAGE}' 이미지 없음")
        print("\n  받는 방법 (인터넷이 되는 경우):")
        print(f"    docker pull forceless/{IMAGE} && docker tag forceless/{IMAGE} {IMAGE}")
        print("  폐쇄망이면 인터넷 되는 PC에서 저장 후 옮기세요:")
        print(f"    docker save forceless/{IMAGE} | gzip > sandbox.tar.gz")
        print(f"    docker load < sandbox.tar.gz && docker tag forceless/{IMAGE} {IMAGE}")
        print("  또는 소스에서 빌드:")
        print(f"    docker build -t {IMAGE} -f deeppresenter/docker/SandBox.Dockerfile .")
        print("\n  참고: 1~3단계는 이 이미지 없이도 전부 동작합니다.\n")
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return 1
    print(f"  [OK  ] 이미지 확인: {', '.join(hit)}")

    # ── 3. real MCP handshake ────────────────────────────────────────
    with tempfile.TemporaryDirectory(prefix="ppt-smoke-") as tmp:
        ws = Path(tmp)
        (ws / "hello.txt").write_text("smoketest", encoding="utf-8")
        print(f"\n  MCP 핸드셰이크 시도 (workspace={ws})")
        try:
            res = asyncio.run(probe_sandbox_mcp(ws))
        except Exception as e:
            print(f"  [FAIL] {type(e).__name__}: {e}")
            report["mcp"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            return 1

        print(f"  [OK  ] 도구 {len(res['tools'])}개: {', '.join(res['tools'])}")
        if "list_directory" in res:
            print("  [OK  ] list_directory 응답:")
            for ln in res["list_directory"].splitlines()[:6]:
                print(f"           {ln}")
        report["mcp"] = {"ok": True, **res}

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  [OK  ] Stage 4 통과")
    print(f"  결과 저장: {OUT}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
