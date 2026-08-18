# smoketest — 템플릿 기반 PPT 생성 단계별 실행 점검

사내 PC처럼 제약이 있는 환경에서 **어디까지 동작하는지** 단계별로 확인하기 위한 스크립트 모음입니다.
한 번에 전부 돌리는 대신, 의존성이 적은 단계부터 올라가며 실패 지점을 좁힙니다.

## 실행

```bash
# WSL 안에서, 저장소 루트 기준
./smoketest/run_all.sh              # 0~4단계 (LLM 불필요)
./smoketest/run_all.sh --with-llm   # 5단계까지 (모델 필요)

# 개별 실행
./.venv/bin/python smoketest/00_env_probe.py --net
./.venv/bin/python smoketest/01_load_template.py --template default
./.venv/bin/python smoketest/03_build_slide_no_llm.py --template thu --slides 3
```

인터프리터는 `./.venv/bin/python`을 자동으로 쓰고, 없으면 `python3`로 넘어갑니다.
직접 지정하려면 `PY=/path/to/python ./smoketest/run_all.sh`.

## 단계 구성

| 단계 | 스크립트 | 필요한 것 | 무엇을 증명하는가 |
| --- | --- | --- | --- |
| 0 | `00_env_probe.py` | 없음 | 파이썬·패키지·바이너리·도커·템플릿·네트워크 현황 |
| 1 | `01_load_template.py` | 없음 | 번들 템플릿 6종이 오프라인으로 로드되고 레이아웃/스키마가 나온다 |
| 2 | `02_validate_content.py` | 없음 | `write_slide` 검증 게이트가 오류/경고를 설계대로 구분한다 |
| 3 | `03_build_slide_no_llm.py` | 없음 | **모델 없이 실제 .pptx가 생성된다** — 파이프라인의 핵심 증명 |
| 4 | `04_docker_sandbox.py` | 도커 | sandbox MCP 서버와 실제로 MCP 통신이 된다 |
| 5 | `05_mcp_end_to_end.py` | 도커 + LLM | `pptagent-mcp` 전 구간이 돌아 pptx가 나온다 |

종료 코드: `0` 통과, `3` 건너뜀(설정 없음), 그 외 실패.
각 단계는 `smoketest/_result_*.json`에 상세 결과를 남깁니다.

## 제약 대입 결과

| 제약 | 영향 | 근거 |
| --- | --- | --- |
| **LibreOffice 없음** | **영향 없음** (번들 템플릿 사용 시) | `soffice`/`unoconvert`는 `ppt_to_images()`에서만 쓰이고, 그 함수는 `ppteval`과 `scripts/template_induct.py`(템플릿 *제작*)에서만 호출됨. 슬라이드 *생성* 경로에는 없음 |
| **python-pptx 사용 가능** | 충분 | 슬라이드 편집·저장은 전부 `pptagent-pptx`(python-pptx 포크)로 처리 |
| **도커는 WSL에 있음** | 4·5단계에서만 필요 | sandbox MCP 서버가 유일한 도커 의존성. 1~3단계는 무관 |
| **폐쇄망 가능성** | 이미지 반입 필요 | `deeppresenter-sandbox` 이미지를 `docker save`/`load`로 옮기거나 `SandBox.Dockerfile`로 빌드 |
| **Research 불필요** | 문제 없음 | 템플릿 경로는 원고 마크다운만 있으면 됨. 3단계는 원고도 하드코딩해서 우회 |

`00_env_probe.py`가 이 표를 그대로 자동 판정해 줍니다.

## 3단계가 하는 일

실제 MCP 서버의 `generate_slide()` → `save_generated_slides()` 경로를 그대로 따라가되,
`coder` LLM이 만들어야 할 편집 코드만 사람이 대신 써 넣습니다.

```
deepcopy(템플릿 슬라이드)
  → CodeExecutor.execute_actions(actions, slide, doc)   # pptagent/apis.py:127
  → Presentation.validate(slide)                        # 손대지 않은 문단 삭제 표시
  → Presentation.save(path)                             # python-pptx 기록
  → python-pptx로 다시 열어 텍스트 대조                    # 독립 검증
```

즉 **모델 호출을 제외한 전 구간**이 오프라인에서 검증됩니다.
편집 함수는 `API_TYPES.Agent`의 다섯 개뿐이고, 인자는 요소 이름이 아니라
`div_id`(도형 번호)와 `paragraph_id`(문단 번호) 정수입니다.

## 알려진 이슈

**`mcp_slide_validate`의 요소 누락 처리** (`pptagent/mcp_server.py:38-53`)

레이아웃에 있는 요소가 입력에서 빠지면 `errors`에 메시지를 넣지만, 바로 아래 길이 검사 루프가
그 요소를 다시 참조해 `KeyError`로 탈출합니다. 결과적으로 `write_slide`는 실패하긴 하지만,
의도한 `"Element X not found in editor output"` 대신 원시 `KeyError`가 모델에게 전달됩니다.

```python
for el in layout_elements - editor_elements:
    errors.append(f"Element {el} not found in editor output")   # 기록은 하지만
...
for el in layout.elements:
    ...
    charater_counts = max([len(i) for i in editor_output[el.name].data])  # 여기서 KeyError
```

2단계 스크립트가 이 경로를 `error_raised`로 분류해 잡아냅니다. 기능이 막히는 수준은 아니고,
모델이 받는 오류 메시지 품질 문제입니다. 고치려면 세 번째 루프를 `if errors: return warnings, errors`
뒤로 미루거나 `if el.name not in editor_output: continue`를 넣으면 됩니다.

## 산출물

- `smoketest_output.pptx` — 3단계 결과 (LLM 없이 생성)
- `smoketest_mcp_output.pptx` — 5단계 결과
- `_result_*.json` — 단계별 상세 기록

모두 `.gitignore` 처리되어 있습니다.
