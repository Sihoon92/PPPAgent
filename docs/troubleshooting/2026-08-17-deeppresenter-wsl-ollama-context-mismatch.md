# Trouble: DeepPresenter가 Windows/WSL + Ollama 환경에서 실행되지 않던 문제 (4중 원인)

- **일자**: 2026-08-17
- **영향 범위**: `pptagent generate` 전체 파이프라인 (Research → Design → HTML → PPTX). Windows 호스트 + WSL2(Ubuntu) + 로컬 Ollama 조합에서 발생.
- **심각도**: high (기능 자체가 동작 불가)
- **상태**: resolved
- **관련 파일**: `deeppresenter/agents/env.py`, `deeppresenter/utils/webview.py`, `deeppresenter/utils/config.py`, `deeppresenter/utils/constants.py`, `deeppresenter/agents/agent.py`, `deeppresenter/cli/dependency.py`

## 1. 문제 배경

Windows 11 + WSL2(Ubuntu) 환경에서 이 저장소를 처음 구동하려 했다. LLM은 외부 API 대신 **Windows 호스트에서 도는 Ollama**를 WSL에서 게이트웨이 IP로 호출하는 구성이다.

README가 "Windows is not supported, use WSL"이라고만 안내하고 있어, WSL 안에 `.venv`와 의존성을 갖추면 바로 될 것으로 기대했다. 실제로는 **서로 다른 층위의 원인 4개**가 순차적으로 드러났고, 하나를 고칠 때마다 다음 원인이 나타났다.

환경:

```text
Host    : Windows 11, RAM 31.1GB, RTX 4070 SUPER (VRAM 12GB)
WSL     : Ubuntu (WSL2), Python 3.12.14 (.venv, uv)
LLM     : Ollama on Windows host, WSL에서 http://172.17.32.1:11434/v1 로 접근
Package : deeppresenter 1.1.37
```

## 2. 증상 (What)

문제를 고칠 때마다 실패 지점이 뒤로 밀렸다. 시간 순서대로:

**(1) Docker 접근 불가 — 에이전트 루프 진입 전 사망**

```text
ERROR [deeppresenter-loop-4fe525c1] Docker is not accessible:
  Error while fetching server API version:
  UnixHTTPConnectionPool(host='localhost', port=None): Read timed out. (read timeout=60)
```

**(2) Playwright 브라우저 부재 — PPTX 변환 실패 (조용한 폴백)**

```text
Error: browserType.launch: Executable doesn't exist at
  ~/.cache/ms-playwright/chromium_headless_shell-1200/chrome-headless-shell-linux64/chrome-headless-shell
    at html2pptx (deeppresenter/html2pptx/html2pptx.js:2981:13)
```

**(3) 툴 콜 미발생 — 10회 재시도 후 종료**

```text
ValueError: All models failed after 10 retries:
[' No tool call returned from the model, got ChatCompletionMessage(
    content='', tool_calls=None,
    reasoning='Thinking Process: 1. **Goal:** Create a single-page presentation about "Hello World"...')']
  at deeppresenter/agents/agent.py:220 → deeppresenter/utils/config.py:287
```

부수적으로, `offline_mode: false` 상태에서는 아래 오류가 히스토리를 오염시켜 모델을 혼란에 빠뜨렸다.

```text
search_web  → 401 Unauthorized                       (TAVILY_API_KEY 미설정)
write_file  → Input validation error: 'path' is a required property
finalize    → Outcome /content/mlops_manifesto.md does not exist   (경로 환각)
```

## 3. 근본 원인 (Why)

### 원인 A — Docker Desktop의 WSL 통합 미등록

`deeppresenter/agents/env.py:230`의 `Environment.__aenter__`가 `docker.from_env()`를 호출하고, 실패 시 `sys.exit(1)`로 즉시 종료한다. 우회 경로가 없는 필수 의존성이다.

`%APPDATA%\Docker\settings-store.json`에 WSL 통합 키가 아예 없었고, Docker Desktop 자체도 실행 중이 아니었다(`AutoStart: false`).

주의할 함정: WSL 안의 `/usr/bin/docker`는 **Docker Desktop이 심어둔 스텁**이다. `command -v docker`는 성공하지만 실행하면 "The command 'docker' could not be found in this WSL 2 distro" 안내만 출력한다. 파일 존재 확인만으로 "docker 사용 가능"이라 판단하면 오진한다.

### 원인 B — Playwright 브라우저가 두 벌 필요

이 프로젝트는 Playwright를 **두 곳에서 각각** 쓴다.

| 사용처 | 패키지 | 요구 chromium 빌드 |
|---|---|---|
| `deeppresenter/utils/webview.py` (Python) | Python `playwright` | 1208 |
| `deeppresenter/html2pptx/` (Node) | Node `playwright` 1.57.0 | **1200** |

`playwright install chromium`(Python)만 실행하면 1208만 받아지고, Node 쪽은 1200을 찾다 실패한다.

**이 실패가 조용하다는 점이 위험하다.** `deeppresenter/main.py:206`이 html2pptx 실패를 잡아 PDF 변환으로 폴백하므로, `generate`는 성공한 것처럼 끝나지만 제대로 된 .pptx가 나오지 않는다. 흔적은 워크스페이스의 `.html2pptx-error.txt`에만 남는다.

### 원인 C — 컨텍스트 윈도우 불일치 (본 건의 핵심)

이번 트러블의 진짜 원인이다. deeppresenter가 가정하는 컨텍스트와 Ollama가 실제로 제공하는 컨텍스트가 **10배 어긋나 있었다.**

```text
deeppresenter/utils/constants.py:23   CONTEXT_LENGTH_LIMIT = 200_000
deeppresenter/utils/config.py:432     context_window = 200000 // 5 = 40,000
                                        (context_folding=true, max_context_folds=5)

ollama ps                             CONTEXT = 4,096
                                        (OLLAMA_CONTEXT_LENGTH 미설정 시 기본값)
```

deeppresenter는 40,000 토큰까지 쓸 수 있다고 믿기 때문에 `agent.py:341`의 컨텍스트 폴딩(요약 압축)을 발동시키지 않는다. 그동안 Ollama는 4,096 초과분을 **에러 없이 조용히 잘라낸다.** 모델은 시스템 프롬프트와 툴 정의를 잃은 채 응답하게 되고, 결과적으로 툴 콜을 만들지 못한다.

실제 프롬프트 크기를 `.history/`에서 측정한 결과:

```text
첫 호출 (system + tools) : ~3,458 ~ 3,913 tok   ← 4,096에 겨우 턱걸이
누적 히스토리            : 20,427 / 39,462 / 55,195 tok   ← 진행될수록 폭증
```

첫 턴은 통과하지만 몇 턴 지나면 반드시 무너진다. 관찰된 "초반엔 툴 콜이 나오다 갑자기 멈춘다"는 패턴과 정확히 일치한다.

결정적 증거: `.history/Research-config.json`에 저장된 도달 컨텍스트 값이 **정확히 4096**에서 멈춰 있었다 (`agent.py:445`가 `self.context_length`를 기록).

> **오진 주의.** 이 문제의 에러 메시지는 `No tool call returned from the model`뿐이라 "모델 능력 부족"으로 판단하기 쉽다. 실제로 이번 조사에서 두 번 그렇게 오판했다. 그러나 격리 테스트(툴 1개 + 짧은 프롬프트)에서는 `gemma4:e2b`조차 정상적으로 tool_calls를 반환했다. 모델을 바꾸기 전에 **`ollama ps`의 CONTEXT 열을 먼저 볼 것.**

참고로 이 프로젝트가 로컬 모델에 권장하는 실행 힌트가 이미 정답을 암시하고 있었다 — `deeppresenter/cli/commands.py:156`:

```text
llama-server -hf {LOCAL_MODEL} -c 100000 --reasoning-budget 0
```

`-c 100000`, 즉 컨텍스트 100k를 잡는다.

### 원인 D — 컨텍스트 확대에 따른 VRAM 초과

원인 C를 고치려 컨텍스트를 키우면 KV 캐시가 커져 모델이 GPU에서 밀려난다. RTX 4070 SUPER(12GB) + `gemma4:12b` 실측:

| OLLAMA_CONTEXT_LENGTH | ollama ps 결과 | 판정 |
|---|---|---|
| 4096 | 8.1GB, 100% GPU | 컨텍스트 부족 |
| 32768 | 9.0GB, **60%/40% CPU/GPU** | VRAM 초과, 매우 느림 |
| **16384** | **8.4GB, 100% GPU** | 채택 |

### 부수 원인 — `search_web` 401이 히스토리를 오염시킴

`deeppresenter/mcp.json`에서 `search`가 유일한 `network: true` 서버이며, `TAVILY_API_KEY`/`SERPAPI_KEY`가 비어 있으면 매 호출이 401을 반환한다. 실패한 툴 응답이 히스토리에 쌓이면 모델이 "API 키가 없어 진행 불가"라는 추론에 갇혀 루프를 돈다.

`env.py:68`이 `if server.network and config.offline_mode: continue`로 처리하므로, `offline_mode: true`면 이 서버를 아예 로드하지 않는다.

## 4. 기술적 해결

| # | 변경 위치 | 변경 내용 | 효과 |
|---|---|---|---|
| 1 | `%APPDATA%\Docker\settings-store.json` | `EnableIntegrationWithDefaultWslDistro: true`, `IntegratedWslDistros: ["Ubuntu"]` 추가 후 Docker Desktop 재시작 | `env.py:230`의 `docker.from_env()`가 WSL에서 소켓에 접속 가능 |
| 2 | `deeppresenter/html2pptx/` | `npx playwright install chromium` (Node 패키지 디렉터리에서 실행) | Node playwright 1.57.0이 요구하는 빌드 1200을 확보. 기존 1208은 Python용으로 유지 |
| 3 | Windows 환경변수 | `OLLAMA_CONTEXT_LENGTH=16384` | Ollama가 4,096 대신 16,384로 모델 적재. 12b가 100% GPU에 유지되는 상한 |
| 4 | `~/.config/deeppresenter/config.yaml` | **`context_window: 14000` 추가** | Ollama 한도(16,384)에 부딪히기 전에 `agent.py:341`의 폴딩이 먼저 발동 |
| 5 | `~/.config/deeppresenter/config.yaml` | `offline_mode: true` | `search` MCP 서버 미로드 → 401로 인한 히스토리 오염 제거 |
| 6 | `~/.config/deeppresenter/config.yaml` | 에이전트 3종 모델을 `gemma4:12b`로 상향 | 15개 툴 에이전트 루프에 필요한 지시 준수 능력 확보 |
| 7 | WSL Ubuntu | `apt install poppler-utils`, Linux Node.js 설치 | `pdfinfo` 및 `webview.py:206`의 `node` 실행에 필요 |

**4번이 핵심이다.** 3번만 적용하고 4번을 빠뜨리면, 컨텍스트를 아무리 키워도 deeppresenter는 여전히 40,000까지 폴딩하지 않으므로 결국 같은 벽에 부딪힌다. 두 값은 반드시 **짝으로** 맞춰야 한다.

최종 설정:

```yaml
# ~/.config/deeppresenter/config.yaml
context_folding: true
context_window: 14000        # < OLLAMA_CONTEXT_LENGTH(16384)
offline_mode: true

research_agent:      { base_url: "http://172.17.32.1:11434/v1", model: "gemma4:12b" }
design_agent:        { base_url: "http://172.17.32.1:11434/v1", model: "gemma4:12b" }
long_context_model:  { base_url: "http://172.17.32.1:11434/v1", model: "gemma4:12b" }
vision_model:        { base_url: "http://172.17.32.1:11434/v1", model: "gemma4:e2b" }
```

## 5. 검증

**단계별 검증 (수정 직후)**

```text
docker (WSL)     : client=28.0.1 server=28.0.1
docker.sock      : http=200  0.0098s          (수정 전: 20s 타임아웃, http=000)
python docker SDK: from_env OK in 0.0s
                   sandbox image: ['deeppresenter-sandbox:latest']
html2pptx 단독   : cli exit=0, out.pptx 45,084 bytes
ollama ps        : gemma4:12b  8.4GB  100% GPU  CONTEXT 16384
```

**엔드투엔드 실행**

```bash
cd /mnt/c/Users/sihoo/PythonProject/PPTAgent
source .venv/bin/activate
pptagent generate "Single Page with Title: Hello World" -o hello.pptx
```

```text
✓ Generated: ~/.cache/deeppresenter/6230fd28/manuscript.pptx
✓ Copied to: /mnt/c/Users/sihoo/PythonProject/PPTAgent/hello.pptx
generate exit=0     56,148 bytes     툴 콜 121회     소요 ~63분
```

**산출물 검증** (python-pptx로 실제 파싱)

```text
slides: 1
size: 13.33 x 7.50 in (16:9)
slide 1: 14 shapes
  "Hello World: The Dawn of Creation"
  The "Hello World" program is the universal rite of passage for every programmer.
  Validation — Confirms that the compiler, interpreter, and environment are correctly configured.
  Momentum   — Provides the first victory, transforming a complex task into a manageable journey.
  Tradition  — Since "The C Programming Language" (Kernighan & Ritchie, 1978)...
```

워크스페이스에 `research/` → `.manuscript.md` → `slides/` → `manuscript.pptx` + `manuscript.pdf`가 모두 생성되었고, `.html2pptx-error.txt`는 **없다**. PDF 폴백이 아니라 정상 HTML→PPTX 경로로 산출되었다는 뜻이다.

## 6. 재발 방지 / 후속 조치

- [x] `deeppresenter/config.yaml.example`에 `context_window` 항목과 로컬 모델 주의사항 주석 추가
- [ ] LibreOffice 설치 (`sudo apt install -y libreoffice`) — 미설치 시 `unoconvert/soffice is not installed, pptx to images conversion will not work` 경고와 함께 시각 기반 reflection 품질 저하. 실행 자체는 가능
- [ ] 웹 검색 품질이 필요하면 `TAVILY_API_KEY` 설정 후 `offline_mode: false`로 전환
- [ ] 성능 개선 검토 — 1페이지에 약 63분(툴 콜 121회) 소요. 다중 페이지 시 선형 이상으로 증가 예상

**운영상 주의 — Docker 소켓 프록시 취약성**

조사 중 WSL의 docker 소켓이 두 차례 끊겼다. 프로세스는 살아 있으나 소켓이 응답하지 않는 상태였다.

```text
root 27307 ... pts/2  Ssl+  docker-desktop-user-distro proxy --distro-name Ubuntu
                      ^^^^  pts의 포그라운드 프로세스 그룹에 묶여 있음
```

추정: Docker Desktop의 WSL 통합 프록시가 특정 WSL 세션의 pty에 종속되어, 짧은 세션을 반복 개폐하면 소켓 서빙이 끊긴다. 터미널 하나를 열어두고 그 안에서 작업하는 일반적 사용 패턴에서는 드물게 발생한다.

증상은 항상 `Docker is not accessible ... Read timed out`이고 해법은 Docker Desktop 재시작이다. 60초를 기다렸다 실패하는 대신 즉시 판별하려면 실행 전 프리플라이트를 둔다:

```bash
CODE=$(curl -s -m 15 --unix-socket /var/run/docker.sock http://localhost/version -o /dev/null -w '%{http_code}')
[ "$CODE" = "200" ] || { echo "ABORT: docker socket not serving. Restart Docker Desktop."; exit 9; }
```

참고로 Docker Desktop CLI의 `docker desktop restart`는 이 환경에서 **종료만 하고 재기동에 실패**했다. `Docker Desktop.exe`를 직접 실행하는 편이 확실하다.

## 7. 참고

- 원본 저장소: https://github.com/icip-cas/PPTAgent
- `deeppresenter/agents/env.py:230` — Docker 필수 의존 지점
- `deeppresenter/utils/webview.py:206` — `node` 서브프로세스 호출 지점
- `deeppresenter/main.py:206` — html2pptx 실패 시 PDF 폴백 (조용한 실패의 원인)
- `deeppresenter/utils/config.py:430-434` — `context_window` 기본값 산출 로직
- `deeppresenter/agents/agent.py:341` — 컨텍스트 폴딩 발동 조건
