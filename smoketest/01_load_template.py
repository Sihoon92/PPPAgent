#!/usr/bin/env python3
"""Stage 1 — load the bundled templates. No LLM, no Docker, no LibreOffice.

Mirrors what PPTAgentServer.__init__ does (pptagent/mcp_server.py:96-133) but
without constructing an AsyncLLM, so it runs on a machine with no model access.

Run:  python smoketest/01_load_template.py [--template default]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pptagent.multimodal import ImageLabler
from pptagent.presentation import Presentation
from pptagent.presentation.layout import Layout
from pptagent.utils import Config, Language, package_join

OUT = Path(__file__).resolve().parent / "_result_01_templates.json"


def load_one(folder: Path) -> dict:
    """Load a single template folder exactly the way the MCP server does."""
    cfg = Config(str(folder))
    prs = Presentation.from_file(str(folder / "source.pptx"), cfg)

    labler = ImageLabler(prs, cfg)
    labler.apply_stats(json.loads((folder / "image_stats.json").read_text()))

    induction = json.loads((folder / "slide_induction.json").read_text())

    # set_reference() pops these two keys before building Layout objects
    # (pptagent/pptgen.py:109-114). Work on a copy so the file stays intact.
    induction = dict(induction)
    lang = Language(**induction.pop("language"))
    functional = induction.pop("functional_keys")
    layouts = {k: Layout(title=k, **v) for k, v in induction.items()}

    return {
        "slides": len(prs.slides),
        "language": {"lid": lang.lid, "cjk": lang.cjk},
        "functional_keys": functional,
        "layouts": layouts,
        "description": (folder / "description.txt").read_text().strip(),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", help="한 개만 자세히 보기")
    args = ap.parse_args()

    tpl_dir = Path(package_join("templates"))
    folders = sorted(p for p in tpl_dir.iterdir() if p.is_dir())
    if args.template:
        folders = [p for p in folders if p.name == args.template]
        if not folders:
            print(f"템플릿 '{args.template}' 없음", file=sys.stderr)
            return 2

    print("\n=== Stage 1: 템플릿 로드 ===\n")
    summary: dict[str, dict] = {}
    failed = 0

    for folder in folders:
        try:
            info = load_one(folder)
        except Exception as e:
            failed += 1
            print(f"  [FAIL] {folder.name:<10} {type(e).__name__}: {e}")
            continue

        layouts = info["layouts"]
        text_n = sum(1 for k in layouts if k.endswith("text"))
        img_n = sum(1 for k in layouts if k.endswith("image"))
        print(
            f"  [OK  ] {folder.name:<10} 슬라이드 {info['slides']:>2}장 · "
            f"레이아웃 {len(layouts):>2}개 (text {text_n} / image {img_n}) · "
            f"언어 {info['language']['lid']}"
        )
        summary[folder.name] = {
            "slides": info["slides"],
            "layout_count": len(layouts),
            "layouts": list(layouts),
            "functional_keys": info["functional_keys"],
            "language": info["language"],
        }

    # detail view
    if args.template and summary:
        folder = folders[0]
        info = load_one(folder)
        print(f"\n--- {folder.name} 상세 ---\n")
        print(f"설명: {info['description'][:300]}\n")
        print("기능성 레이아웃:", ", ".join(info["functional_keys"]) or "(없음)")
        print("\n레이아웃별 content_schema:\n")
        for name, layout in info["layouts"].items():
            print(f"■ {name}")
            for line in layout.content_schema.splitlines():
                print(f"    {line}")
            print()

    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  결과 저장: {OUT}")
    print(f"  성공 {len(summary)} / 실패 {failed}\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
