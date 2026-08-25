#!/usr/bin/env python3
"""Stage 6 — convert a pptx to images through Windows PowerPoint.

This is the office-machine path: LibreOffice cannot be installed, so
`ppt_to_images()` hands the file to PowerPoint on the Windows side via
pptagent/winppt.py instead of `soffice`.

Nothing in slide *generation* needs this. It matters for template induction
(scripts/template_induct.py) and for ppteval, which are the only callers of
ppt_to_images().

Run:  python smoketest/06_win_convert.py [--template default]

Exit: 0 pass, 3 skipped (bridge unusable), 1 failed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "_result_06_win.json"

REMEDY = {
    "WSLInterop": (
        "WSL cannot launch Windows programs. With systemd=true, re-register the\n"
        "         handler (as root, inside WSL):\n"
        "           echo ':WSLInterop:M::MZ::/init:PF' > /proc/sys/fs/binfmt_misc/register\n"
        "         A `wsl --shutdown` from Windows also restores it until the next boot."
    ),
    "PPTAGENT_WIN_PYTHON": (
        "No Windows Python found. Install Python on the Windows side, then:\n"
        "           py -m pip install pywin32\n"
        "           export PPTAGENT_WIN_PYTHON=/mnt/c/.../python.exe"
    ),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", default="default")
    args = ap.parse_args()

    print("\n=== Stage 6: Windows PowerPoint 변환 브리지 ===\n")

    from pptagent import winppt
    from pptagent.utils import package_join, ppt_to_images

    report: dict = {}

    # ── 1. can the bridge run at all? ─────────────────────────────────
    ok, reason = winppt.bridge_status()
    report["bridge"] = {"ok": ok, "reason": reason}
    print("[1] 브리지 상태")
    if not ok:
        print(f"  [SKIP] {reason}\n")
        for key, remedy in REMEDY.items():
            if key in reason:
                print(f"  해결:  {remedy}\n")
        OUT.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return 3
    interpreter = winppt.find_win_python(os.environ.get("PPTAGENT_WIN_PYTHON"))
    print(f"  [OK  ] Windows 인터프리터   {interpreter}")
    print(f"  [OK  ] 스테이징 위치        {winppt.staging_base()}")
    report["bridge"]["interpreter"] = str(interpreter)

    # ── 2. convert a real template ────────────────────────────────────
    source = Path(package_join("templates", args.template, "source.pptx"))
    if not source.exists():
        print(f"  [FAIL] 템플릿을 찾지 못함: {source}\n")
        return 1

    print(f"\n[2] 변환  {source.name} ({source.stat().st_size:,} bytes)")
    print("  PowerPoint를 띄웁니다. 이미 열려 있던 PowerPoint는 종료하지 않습니다.")

    # Force the bridge even on a machine that also has LibreOffice, so this
    # stage always exercises the path it is meant to test.
    os.environ["PPTAGENT_OFFICE_MODE"] = "1"

    with tempfile.TemporaryDirectory(prefix="win-convert-") as out_dir:
        try:
            asyncio.run(ppt_to_images(str(source), out_dir))
        except Exception as e:
            print(f"  [FAIL] {type(e).__name__}: {str(e)[:600]}\n")
            report["convert"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            OUT.write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return 1

        images = sorted(Path(out_dir).glob("slide_*.jpg"))
        if not images:
            print("  [FAIL] 변환은 끝났지만 이미지가 없습니다.\n")
            report["convert"] = {"ok": False, "error": "no images produced"}
            OUT.write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return 1

        total = sum(p.stat().st_size for p in images)
        print(f"  [OK  ] 슬라이드 이미지 {len(images)}장, 합계 {total:,} bytes")
        print(
            f"           첫 장: {images[0].name} ({images[0].stat().st_size:,} bytes)"
        )

        keep = HERE / "win_convert_slide_0001.jpg"
        keep.write_bytes(images[0].read_bytes())
        report["convert"] = {
            "ok": True,
            "template": args.template,
            "images": len(images),
            "bytes": total,
            "kept": str(keep),
        }

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n  [OK  ] Stage 6 통과")
    print(f"  결과 저장: {OUT}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
