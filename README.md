<div align="center">
  <img src="resource/pptagent-logo.jpg" width="200px" alt="DeepPresenter">
  <h1>DeepPresenter (PPTAgent)</h1>
  <p>An agentic framework that turns a prompt and reference files into a finished PowerPoint deck.</p>
</div>

> Fork of [icip-cas/PPTAgent](https://github.com/icip-cas/PPTAgent).
> This README covers installation and usage only. See the upstream repository for papers, benchmarks, and case studies.

## Requirements

| Item | Notes |
| --- | --- |
| OS | Linux or macOS. **Windows is not supported — run it inside WSL2.** |
| Python | 3.11 or newer |
| Docker | Required. Agent tools run inside a sandbox container. |
| Node.js | Required by the HTML → PPTX converter (`deeppresenter/html2pptx`). |
| poppler | Required for PDF handling (`pdfinfo` must be on `PATH`). |
| LLM access | Any OpenAI-compatible endpoint — a hosted API, or a self-hosted server such as Ollama, llama.cpp, or vLLM. |

On macOS the onboarding wizard can install most of these for you (Homebrew, Node.js, Docker, poppler, Playwright, llama.cpp). On Linux you install them yourself.

## Installation

Pick one of the three options below.

### Option 1 — CLI only (quickest)

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Interactive first-time setup (models, API keys, dependency checks)
uvx pptagent onboard
```

### Option 2 — From source (development)

```bash
git clone https://github.com/Sihoon92/PPPAgent.git
cd PPPAgent

uv venv --python 3.12
source .venv/bin/activate
uv pip install -e .

# Runtime dependencies
sudo playwright install-deps          # Linux only
playwright install chromium
npm install --prefix deeppresenter/html2pptx
modelscope download forceless/fasttext-language-id

# Sandbox image used by the agent runtime
docker pull forceless/deeppresenter-sandbox
docker tag forceless/deeppresenter-sandbox deeppresenter-sandbox
```

If Docker Hub is slow, pull through the mirror instead:

```bash
docker pull docker.1ms.run/forceless/deeppresenter-sandbox
docker tag docker.1ms.run/forceless/deeppresenter-sandbox deeppresenter-sandbox
```

### Option 3 — Docker Compose (server)

```bash
docker pull forceless/deeppresenter-host
docker pull forceless/deeppresenter-sandbox
docker tag forceless/deeppresenter-host deeppresenter-host
docker tag forceless/deeppresenter-sandbox deeppresenter-sandbox

docker compose up -d
```

The web UI is then served at <http://localhost:7861>.

## Configuration

Two files drive the runtime:

| File | Purpose |
| --- | --- |
| `~/.config/deeppresenter/config.yaml` | LLM endpoints and generation options |
| `~/.config/deeppresenter/mcp.json` | MCP tool servers and their API keys |

`pptagent onboard` creates and validates both interactively. To write them by hand, copy the templates:

```bash
cp deeppresenter/config.yaml.example ~/.config/deeppresenter/config.yaml
cp deeppresenter/mcp.json.example    ~/.config/deeppresenter/mcp.json
```

### Required models

`config.yaml` must define `research_agent`, `design_agent`, and `long_context_model`, each with `base_url`, `model`, and `api_key`:

```yaml
research_agent:
  base_url: "https://openrouter.ai/api/v1"
  model: "anthropic/claude-sonnet-4.5"
  api_key: "your_key"
```

### Optional, but improves quality

- **`vision_model`** — lets the design agent look at the slides it renders.
- **`t2i_model`** — better generated imagery.
- **Tavily / SerpAPI** — better web search. Set `TAVILY_API_KEY` / `SERPAPI_KEY` in `mcp.json`.
- **MinerU** — better PDF parsing. Set `MINERU_API_KEY`, or `MINERU_API_URL` for a local deployment, in `mcp.json`.

For a fully offline run, deploy MinerU locally and set `offline_mode: true` in `config.yaml` so network-dependent tools are never loaded.

### Self-hosted models: set `context_window`

Self-hosted servers silently truncate prompts that exceed their configured context length, which kills the agent loop with `No tool call returned from the model`. Set `context_window` in `config.yaml` **below** what the server actually serves:

```yaml
# Example for OLLAMA_CONTEXT_LENGTH=16384
context_window: 14000
```

Ollama defaults to 4096 tokens. Check the `CONTEXT` column of `ollama ps`, and after raising it confirm the model still reports 100% GPU.

Remaining tunables live in [`deeppresenter/utils/constants.py`](deeppresenter/utils/constants.py).

## Usage

### CLI

```bash
# Smallest possible task — use this to verify your setup
pptagent generate "Single Page with Title: Hello World" -o hello.pptx

# With attachments, page count, and an interactive outline step
pptagent generate "Q4 Report" \
  -f data.xlsx \
  -f charts.pdf \
  -p "10-12" \
  --planner \
  -o report.pptx
```

| Command | Description |
| --- | --- |
| `pptagent onboard` | Interactive configuration wizard |
| `pptagent generate` | Generate a presentation |
| `pptagent serve` | Start the bundled local model service |
| `pptagent config` | Show the current configuration |
| `pptagent clean` | Remove config and cache directories |

`generate` options:

| Option | Default | Description |
| --- | --- | --- |
| `-o`, `--output` | *(required)* | Output path, e.g. `deck.pptx` |
| `-f`, `--file` | — | Attachment file; repeat for multiple |
| `-p`, `--pages` | auto | Page count, e.g. `8` or `5-10` |
| `-a`, `--aspect` | `16:9` | `16:9`, `4:3`, `A1`, `A2`, `A3`, `A4` |
| `-l`, `--lang` | `en` | `en` or `zh` |
| `--planner` | off | Draft an outline and let you revise it before research starts |

### Web UI

From a source checkout:

```bash
python webui.py
```

Then open <http://localhost:7861>. The Docker Compose deployment serves the same UI on that port.

### MCP server

The legacy template-based generator is exposed as an MCP server via the `pptagent-mcp` command, so you can call it from any MCP client.

## Where files go

- Config: `~/.config/deeppresenter/`
- Workspaces and intermediate artifacts: `~/.cache/deeppresenter/` — override with `DEEPPRESENTER_WORKSPACE_BASE`
- Each run keeps its HTML, images, and `intermediate_output.json` in its own workspace, which is useful when a run fails midway.

## Troubleshooting

- If PPTX conversion silently falls back to PDF, Playwright's Chromium is probably missing — rerun `playwright install chromium`.
- If the run dies before the agent loop starts, Docker is likely unreachable from your shell.
- A worked example covering Windows/WSL2 + local Ollama is in [`docs/troubleshooting/`](docs/troubleshooting/2026-08-17-deeppresenter-wsl-ollama-context-mismatch.md).

## License

MIT — see [LICENSE](LICENSE).

<details>
<summary>Citation</summary>

```bibtex
@inproceedings{zheng-etal-2025-pptagent,
    title = "{PPTA}gent: Generating and Evaluating Presentations Beyond Text-to-Slides",
    author = "Zheng, Hao and Guan, Xinyan and Kong, Hao and Zhang, Wenkai and
      Zheng, Jia and Zhou, Weixiang and Lin, Hongyu and Lu, Yaojie and
      Han, Xianpei and Sun, Le",
    booktitle = "Proceedings of the 2025 Conference on Empirical Methods in Natural Language Processing",
    year = "2025",
    address = "Suzhou, China",
    publisher = "Association for Computational Linguistics",
    url = "https://aclanthology.org/2025.emnlp-main.728/",
    doi = "10.18653/v1/2025.emnlp-main.728",
    pages = "14413--14429",
}

@misc{zheng2026deeppresenterenvironmentgroundedreflectionagentic,
      title={DeepPresenter: Environment-Grounded Reflection for Agentic Presentation Generation},
      author={Hao Zheng and Guozhao Mo and Xinru Yan and Qianhao Yuan and Wenkai Zhang and
        Xuanang Chen and Yaojie Lu and Hongyu Lin and Xianpei Han and Le Sun},
      year={2026},
      eprint={2602.22839},
      archivePrefix={arXiv},
      primaryClass={cs.AI},
      url={https://arxiv.org/abs/2602.22839},
}
```

</details>
