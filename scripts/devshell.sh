#!/usr/bin/env bash
# Project dev shell — activates everything needed to run PPTAgent in one step.
#
#   From Windows : double-click run.cmd (or `.\run.cmd` in a terminal)
#   From WSL     : source scripts/devshell.sh
#
# run.cmd starts bash with --init-file, which replaces ~/.bashrc, so load the
# user's own rc first and layer the project environment on top of it.

if [ -n "${PS1-}" ] && [ -f "$HOME/.bashrc" ]; then
    # shellcheck disable=SC1091
    . "$HOME/.bashrc"
fi

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || return 1

# 1. Project overrides. Sourced first so .env wins over the defaults below.
if [ -f "$REPO/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    . "$REPO/.env"
    set +a
fi

# 2. Virtualenv. This also puts .venv/bin on PATH, which is what lets the
#    smoketest spawn the `pptagent-mcp` console script by name.
if [ -f "$REPO/.venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    . "$REPO/.venv/bin/activate"
else
    echo "  [!] .venv 없음 — uv venv --python 3.12 && uv pip install -e ."
fi

# 3. Config and office mode.
export CONFIG_FILE="${CONFIG_FILE:-$HOME/.config/deeppresenter/config.yaml}"
export PPTAGENT_OFFICE_MODE="${PPTAGENT_OFFICE_MODE:-1}"

# 4. Report what is actually in effect.
mark() { [ -n "$2" ] && echo "  [OK  ] $1  $2" || echo "  [WARN] $1  미설정"; }

echo
echo "  PPTAgent dev shell — $REPO"
mark "python        " "$(command -v python)"
mark "pptagent-mcp  " "$(command -v pptagent-mcp)"
if [ -f "$CONFIG_FILE" ]; then
    mark "CONFIG_FILE   " "$CONFIG_FILE"
else
    echo "  [WARN] CONFIG_FILE    $CONFIG_FILE (없음 — pptagent onboard 또는 .env 사용)"
fi
mark "OFFICE_MODE   " "$PPTAGENT_OFFICE_MODE"
[ -n "${PPTAGENT_MODEL-}" ] && mark "PPTAGENT_MODEL" "$PPTAGENT_MODEL @ ${PPTAGENT_API_BASE:-?}"
echo
echo "  pptagent generate \"Hello World\" -o hello.pptx"
echo "  ./smoketest/run_all.sh [--with-llm]"
echo
