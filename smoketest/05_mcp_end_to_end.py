#!/usr/bin/env python3
"""Stage 5 — drive the real pptagent MCP server end to end. NEEDS AN LLM.

Spawns `pptagent-mcp` over stdio and walks the documented tool sequence:

    list_templates -> set_template -> create_slide -> write_slide
                   -> generate_slide -> save_generated_slides

generate_slide is where the server calls its own `coder` model
(pptagent/pptgen.py:501), so this stage fails without a reachable endpoint.
The server also tests the connection at startup (mcp_server.py:89), which means
a bad config shows up as a spawn failure, not a tool failure.

Configure one of:
    export PPTAGENT_MODEL=qwen2.5:14b
    export PPTAGENT_API_BASE=http://127.0.0.1:11434/v1
    export PPTAGENT_API_KEY=ollama
or:
    export CONFIG_FILE=$HOME/.config/deeppresenter/config.yaml

Run:  python smoketest/05_mcp_end_to_end.py [--template default]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "_result_05_mcp.json"


def text_of(result) -> str:
    return "".join(c.text for c in result.content if getattr(c, "type", "") == "text")


def parse_schema(schema: str) -> list[dict]:
    """Turn the plain-text content_schema into element descriptors.

    The schema format comes from Element.get_schema()
    (pptagent/presentation/layout.py:33-41).
    """
    elements: list[dict] = []
    cur: dict | None = None
    for raw in schema.splitlines():
        line = raw.strip()
        if line.startswith("Element:"):
            cur = {"name": line.split(":", 1)[1].strip(), "type": "text", "quantity": 1,
                   "chars": 30}
            elements.append(cur)
        elif cur is None:
            continue
        elif line.startswith("type:"):
            cur["type"] = line.split(":", 1)[1].strip()
        elif line.startswith("suggested_characters:"):
            cur["chars"] = int(re.sub(r"\D", "", line.split(":", 1)[1]) or 30)
        elif "quantity of the element is" in line:
            m = re.search(r"is\s+(\d+)", line)
            if m:
                cur["quantity"] = int(m.group(1))
    return elements


FILLER = [
    "사내 PPT 자동 생성 검토",
    "템플릿 기반 파이프라인 점검",
    "오프라인 환경에서의 동작 확인",
    "다음 단계 계획",
]


async def drive(template: str, workspace: Path) -> dict:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = dict(os.environ)
    env["WORKSPACE"] = str(workspace)
    env.setdefault("FASTMCP_LOG_LEVEL", "CRITICAL")

    params = StdioServerParameters(command="pptagent-mcp", args=[], env=env)
    report: dict = {}

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), timeout=300)
            tools = [t.name for t in (await session.list_tools()).tools]
            print(f"  [OK  ] 서버 기동, 도구 {len(tools)}개: {', '.join(tools)}")
            report["tools"] = tools

            # 1. list_templates
            r = await session.call_tool("list_templates", {})
            names = re.findall(r'"name"\s*:\s*"([^"]+)"', text_of(r))
            print(f"  [OK  ] list_templates → {', '.join(names) or '(파싱 실패)'}")
            report["templates"] = names

            # 2. set_template
            r = await session.call_tool("set_template", {"template_name": template})
            body = text_of(r)
            layouts = re.findall(r'"([^"]+)"', body)
            avail = [x for x in layouts if x.endswith(("text", "image")) or x == "opening"]
            print(f"  [OK  ] set_template({template}) → 레이아웃 {len(avail)}개")
            report["layouts"] = avail

            layout = next((x for x in avail if x == "opening"), None) or next(
                (x for x in avail if x.endswith("text")), None
            )
            if layout is None:
                raise RuntimeError(f"텍스트 레이아웃을 찾지 못함: {avail}")

            # 3. create_slide
            r = await session.call_tool("create_slide", {"layout": layout})
            schema_body = text_of(r)
            elements = parse_schema(schema_body)
            print(f"  [OK  ] create_slide({layout[:40]}) → 요소 {len(elements)}개")
            for el in elements:
                print(f"           · {el['name']} ({el['type']}, {el['quantity']}개, ~{el['chars']}자)")
            report["elements"] = elements
            if any(el["type"] == "image" for el in elements):
                raise RuntimeError("이미지 요소가 있는 레이아웃입니다. 텍스트 전용으로 다시 시도하세요.")

            # 4. write_slide
            payload = [
                {"name": el["name"],
                 "data": [FILLER[i % len(FILLER)][: max(el["chars"], 8)]
                          for i in range(el["quantity"])]}
                for el in elements
            ]
            r = await session.call_tool(
                "write_slide", {"structured_slide_elements": payload}
            )
            print(f"  [{'FAIL' if r.isError else 'OK  '}] write_slide → {text_of(r)[:160]}")
            if r.isError:
                raise RuntimeError(text_of(r))

            # 5. generate_slide  ← 여기서 서버 내부 coder LLM이 돈다
            print("  ...  generate_slide 실행 중 (서버 내부 LLM 호출, 수십 초 걸릴 수 있음)")
            r = await asyncio.wait_for(session.call_tool("generate_slide", {}), timeout=900)
            print(f"  [{'FAIL' if r.isError else 'OK  '}] generate_slide → {text_of(r)[:160]}")
            if r.isError:
                raise RuntimeError(text_of(r))

            # 6. save
            out_name = "smoketest_mcp_output.pptx"
            r = await session.call_tool("save_generated_slides", {"pptx_path": out_name})
            print(f"  [{'FAIL' if r.isError else 'OK  '}] save_generated_slides → {text_of(r)[:200]}")
            if r.isError:
                raise RuntimeError(text_of(r))
            report["output"] = str(workspace / out_name)
            return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", default="default")
    ap.add_argument("--workspace", help="기본값: 임시 디렉터리")
    args = ap.parse_args()

    print("\n=== Stage 5: MCP 전 구간 (LLM 필요) ===\n")

    has_env = os.getenv("PPTAGENT_MODEL") or os.getenv("CONFIG_FILE")
    if not has_env:
        print("  [SKIP] LLM 설정이 없습니다. 아래 중 하나를 설정한 뒤 다시 실행하세요.\n")
        print("    export PPTAGENT_MODEL=qwen2.5:14b")
        print("    export PPTAGENT_API_BASE=http://127.0.0.1:11434/v1")
        print("    export PPTAGENT_API_KEY=ollama")
        print("  또는")
        print("    export CONFIG_FILE=$HOME/.config/deeppresenter/config.yaml\n")
        return 3

    print(f"  모델: {os.getenv('PPTAGENT_MODEL') or '(CONFIG_FILE의 research_agent)'}")
    print(f"  엔드포인트: {os.getenv('PPTAGENT_API_BASE') or '(config)'}\n")

    tmp = None
    if args.workspace:
        ws = Path(args.workspace).resolve()
        ws.mkdir(parents=True, exist_ok=True)
    else:
        tmp = tempfile.TemporaryDirectory(prefix="ppt-mcp-")
        ws = Path(tmp.name)

    try:
        report = asyncio.run(drive(args.template, ws))
    except Exception as e:
        print(f"\n  [FAIL] {type(e).__name__}: {str(e)[:600]}\n")
        OUT.write_text(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
        return 1

    out_file = Path(report["output"])
    if out_file.exists():
        keep = HERE / "smoketest_mcp_output.pptx"
        keep.write_bytes(out_file.read_bytes())
        print(f"\n  [OK  ] 산출물 {keep} ({keep.stat().st_size:,} bytes)")
        report["kept"] = str(keep)
    else:
        print(f"\n  [WARN] 산출물을 찾지 못함: {out_file}")

    report["ok"] = True
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  결과 저장: {OUT}\n")
    if tmp:
        tmp.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
