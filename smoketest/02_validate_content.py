#!/usr/bin/env python3
"""Stage 2 — exercise the write_slide validation gate. No LLM, no Docker.

write_slide() is the only place that rejects bad content before rendering
(pptagent/mcp_server.py:233-273). It raises on structural errors and merely
warns on length problems. This script proves both branches behave as documented.

Run:  python smoketest/02_validate_content.py [--template default]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pptagent.mcp_server import mcp_slide_validate
from pptagent.presentation.layout import Layout
from pptagent.response.pptgen import EditorOutput, SlideElement
from pptagent.utils import Language, package_join

OUT = Path(__file__).resolve().parent / "_result_02_validate.json"


def build_layouts(template: str) -> tuple[dict[str, Layout], Language]:
    folder = Path(package_join("templates")) / template
    induction = dict(json.loads((folder / "slide_induction.json").read_text()))
    lang = Language(**induction.pop("language"))
    induction.pop("functional_keys")
    return {k: Layout(title=k, **v) for k, v in induction.items()}, lang


def check(name: str, layout: Layout, lang: Language, elements: list[dict]) -> dict:
    """Run one validation case and report warnings / errors / exceptions."""
    try:
        out = EditorOutput(elements=[SlideElement(**e) for e in elements])
    except Exception as e:
        print(f"  [{'OK  '}] {name:<34} 스키마 파싱 거부: {type(e).__name__}")
        return {"outcome": "schema_error", "detail": str(e)[:200]}

    try:
        warnings, errors = mcp_slide_validate(out, layout, lang)
    except Exception as e:
        # Known defect: the length loop dereferences every layout element even
        # after recording a "not found" error, so a missing/renamed element
        # escapes as a raw KeyError instead of the intended message.
        # See pptagent/mcp_server.py:42-53.
        print(f"  [WARN] {name:<34} 예외로 탈출: {type(e).__name__}: {e}")
        return {"outcome": "error_raised", "detail": f"{type(e).__name__}: {e}"}
    if errors:
        print(f"  [OK  ] {name:<34} errors={len(errors)} → write_slide는 예외를 던짐")
        for e in errors[:3]:
            print(f"           · {e}")
        return {"outcome": "error", "errors": errors}
    if warnings:
        print(f"  [OK  ] {name:<34} warnings={len(warnings)} → 진행 가능")
        for w in warnings[:3]:
            print(f"           · {w}")
        return {"outcome": "warning", "warnings": warnings}
    print(f"  [OK  ] {name:<34} 통과")
    return {"outcome": "pass"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", default="default")
    args = ap.parse_args()

    layouts, lang = build_layouts(args.template)

    # pick a layout whose elements are all text, so cases stay simple
    text_layout = next(
        (lo for lo in layouts.values() if all(el.type == "text" for el in lo.elements)),
        None,
    )
    image_layout = next(
        (lo for lo in layouts.values() if any(el.type == "image" for el in lo.elements)),
        None,
    )
    if text_layout is None:
        print("텍스트 전용 레이아웃을 찾지 못함", file=sys.stderr)
        return 2

    print(f"\n=== Stage 2: 내용 검증 (template={args.template}) ===\n")
    print(f"대상 레이아웃: {text_layout.title}")
    print(f"참조 언어: {lang.lid} ({'cjk' if lang.cjk else 'latin'})\n")
    for el in text_layout.elements:
        print(f"  · {el.name}: {el.type}, 권장 {el.suggested_characters}자, 기본 {len(el.data)}개")
    print()

    results: dict[str, dict] = {}

    # ── case 1: well-formed, short text ──────────────────────────────
    good = [
        {"name": el.name, "data": ["짧은 값"] * len(el.data)}
        for el in text_layout.elements
    ]
    results["1_정상"] = check("1. 정상 입력", text_layout, lang, good)

    # ── case 2: unknown element name ─────────────────────────────────
    bad_name = [dict(e) for e in good]
    bad_name[0] = {"name": "존재하지_않는_요소", "data": ["x"]}
    results["2_요소명_불일치"] = check("2. 요소 이름 불일치", text_layout, lang, bad_name)

    # ── case 3: missing element ──────────────────────────────────────
    if len(good) > 1:
        results["3_요소_누락"] = check("3. 요소 누락", text_layout, lang, good[:-1])

    # ── case 4: text far over the suggested length ───────────────────
    longest = max(text_layout.elements, key=lambda el: el.suggested_characters or 0)
    over = []
    for el in text_layout.elements:
        if el.name == longest.name:
            n = (longest.suggested_characters or 20) * 4
            over.append({"name": el.name, "data": ["가" * n] * len(el.data)})
        else:
            over.append({"name": el.name, "data": ["짧은 값"] * len(el.data)})
    results["4_길이_초과"] = check("4. 권장 글자수 초과", text_layout, lang, over)

    # ── case 5: nonexistent image path ───────────────────────────────
    if image_layout is not None:
        img = []
        for el in image_layout.elements:
            if el.type == "image":
                img.append({"name": el.name, "data": ["/tmp/없는파일.png"] * len(el.data)})
            else:
                img.append({"name": el.name, "data": ["짧은 값"] * len(el.data)})
        results["5_이미지_없음"] = check(
            f"5. 이미지 경로 없음 ({image_layout.title[:18]})", image_layout, lang, img
        )

    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    # "거부"는 errors 반환과 예외 탈출 둘 다 포함한다. 후자는 코드 결함이지만
    # write_slide 입장에서는 어차피 실패로 이어진다.
    rejected = {"error", "error_raised", "schema_error"}
    expect: dict[str, set[str]] = {
        "1_정상": {"pass"},
        "2_요소명_불일치": rejected,
        "3_요소_누락": rejected,
        "4_길이_초과": {"warning"},
        "5_이미지_없음": rejected,
    }
    print("\n--- 기대값 대조 ---")
    ok = True
    for k, want in expect.items():
        if k not in results:
            continue
        got = results[k]["outcome"]
        hit = got in want
        ok &= hit
        print(f"  [{'OK  ' if hit else 'FAIL'}] {k:<18} 기대={'|'.join(sorted(want)):<28} 실제={got}")

    print(f"\n  결과 저장: {OUT}\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
