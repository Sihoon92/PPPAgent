# smoketest — 템플릿 기반 PPT 생성 단계별 실행 점검

사내 PC처럼 제약이 있는 환경에서 **어디까지 동작하는지** 단계별로 확인하기 위한 스크립트 모음입니다.
한 번에 전부 돌리는 대신, 의존성이 적은 단계부터 올라가며 실패 지점을 좁힙니다.

## 실행

```bash
# WSL 안에서, 저장소 루트 기준
./smoketest/run_all.sh              # 0~4·6단계 (LLM 불필요)
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
| 6 | `06_win_convert.py` | Windows PowerPoint | LibreOffice 없이 pptx→이미지 변환이 된다 (사내 모드) |

종료 코드: `0` 통과, `3` 건너뜀(설정 없음), 그 외 실패.
각 단계는 `smoketest/_result_*.json`에 상세 결과를 남깁니다.

## 제약 대입 결과

| 제약 | 영향 | 근거 |
| --- | --- | --- |
| **LibreOffice 없음** | **영향 없음** (번들 템플릿 사용 시) | `soffice`/`unoconvert`는 `ppt_to_images()`에서만 쓰이고, 그 함수는 `ppteval`과 `scripts/template_induct.py`(템플릿 *제작*)에서만 호출됨. 슬라이드 *생성* 경로에는 없음 |
| **LibreOffice 없이 템플릿 제작** | 사내 모드로 가능 | `PPTAGENT_OFFICE_MODE=1`이면 `ppt_to_images()`/`wmf_to_images()`가 WSL→Windows PowerPoint 브리지(`pptagent/winppt.py`)를 탄다. 6단계가 이 경로를 검증 |
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

## 해결된 이슈

**`mcp_slide_validate`의 요소 누락 처리** (`pptagent/mcp_server.py`) — 수정됨

레이아웃에 있는 요소가 입력에서 빠지면 `errors`에 메시지를 넣어두고도, 바로 아래 길이 검사 루프가
그 요소를 다시 참조해 `KeyError`로 탈출했습니다. 모델은 의도한 `"Element X not found in editor output"`
대신 원시 `KeyError: "Element 'X' not found"`를 받아 스스로 고칠 수 없었습니다.
이제 에러가 있으면 길이 검사 전에 반환합니다.

**스키마의 `type` 필드가 깨져 있던 문제** (`pptagent/presentation/layout.py`) — 수정됨

`f"\type: {self.type}"`에서 `\t`가 탭으로 해석돼 "type"의 t를 먹었고,
모델이 읽는 스키마에는 `<TAB>ype: text`로 나갔습니다. `f"\ttype: ..."`으로 고쳤습니다.

**5단계의 스키마 파서** (`smoketest/05_mcp_end_to_end.py`) — 수정됨

`create_slide`는 dict를 반환하므로 MCP 응답은 JSON 문자열이고, 스키마의 줄바꿈은
이스케이프된 `\n` 두 글자입니다. 파서가 이를 평문으로 보고 `splitlines()`를 해서
요소를 0개 뽑았고, 빈 `write_slide([])`가 위 `KeyError`를 유발했습니다.
이제 `json.loads` 후 `["schema"]`를 파싱하고, 요소가 0개면 즉시 실패합니다.

## 산출물

- `smoketest_output.pptx` — 3단계 결과 (LLM 없이 생성)
- `smoketest_mcp_output.pptx` — 5단계 결과
- `win_convert_slide_0001.jpg` — 6단계 결과 (PowerPoint가 렌더링한 첫 슬라이드)
- `_result_*.json` — 단계별 상세 기록

모두 `.gitignore` 처리되어 있습니다.

## 사내 모드 (Windows PowerPoint 브리지)

LibreOffice를 설치할 수 없는 PC에서 `ppt_to_images()`/`wmf_to_images()`를 살리는 경로입니다.
WSL 안의 파이썬이 Windows 쪽 파이썬을 실행하고, 그쪽에서 pywin32로 PowerPoint를 COM 자동화합니다.

| 변수 | 뜻 |
| --- | --- |
| `PPTAGENT_OFFICE_MODE=1` | 브리지 강제. 미설정이면 LibreOffice가 없을 때만 자동으로 브리지를 씀 |
| `PPTAGENT_WIN_PYTHON` | Windows 파이썬 경로. 미설정이면 `PATH`의 `python.exe`를 찾음 |
| `PPTAGENT_WIN_TEMP` | 스테이징 디렉터리. 미설정이면 `/mnt/c/Users/Public` |

필요한 것:

1. **WSL interop** — `powershell.exe -NoProfile -Command "Write-Output ok"`가 WSL 안에서 동작해야 함.
   `systemd=true`인 배포판은 `systemd-binfmt`가 `WSLInterop` 등록을 지워서 `Exec format error`가 납니다.
   `wsl -u root -- bash -c "echo ':WSLInterop:M::MZ::/init:PF' > /proc/sys/fs/binfmt_misc/register"`로 되살릴 수 있고,
   부팅마다 유지하려면 systemd 유닛으로 등록해야 합니다.
2. **Windows 쪽 파이썬 + pywin32** — `py -m pip install pywin32`.
3. **PowerPoint** — COM 자동화는 대화형 데스크톱 세션이 필요합니다. 서비스나 끊긴 RDP 세션에서는 실패합니다.

동작 방식과 주의점:

- pptx→PDF는 `Presentation.SaveAs(ppSaveAsPDF)`, PDF→JPG는 기존 poppler 경로를 그대로 씁니다.
  `ExportAsFixedFormat()`은 late binding에서 옵셔널 COM 파라미터 기본값을 못 만들어 실패합니다.
- WMF/EMF는 PowerPoint에 그려서 `Shape.Export()`로 뽑습니다. Pillow의 GDI 렌더링은 실제 EMF에서
  `cannot render metafile`로 자주 실패해서 쓰지 않습니다.
- 입력 파일과 변환 스크립트는 항상 드라이브 마운트(`/mnt/...`)에 복사한 뒤 넘깁니다.
  WSL의 `/tmp`는 Windows에서 `\\wsl.localhost\...` UNC로 보이고 PowerPoint가 이를 제대로 열지 못합니다.
- 이미 열려 있던 PowerPoint 인스턴스는 종료하지 않습니다. 우리가 띄운 경우에만 `Quit()`합니다.
