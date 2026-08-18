#!/usr/bin/env bash
# Run the offline smoke tests in order and print a summary.
#
#   ./smoketest/run_all.sh            # stages 0-4 (no LLM needed)
#   ./smoketest/run_all.sh --with-llm # also stage 5 (needs PPTAGENT_MODEL or CONFIG_FILE)
#
# Stage 5 is skipped by default because it is the only one that needs a model.

set -u

cd "$(dirname "$0")/.." || exit 1

PY="${PY:-}"
if [ -z "$PY" ]; then
  if [ -x ./.venv/bin/python ]; then PY=./.venv/bin/python; else PY=python3; fi
fi

STAGES=(
  "00_env_probe.py"
  "01_load_template.py"
  "02_validate_content.py"
  "03_build_slide_no_llm.py"
  "04_docker_sandbox.py"
)
[ "${1:-}" = "--with-llm" ] && STAGES+=("05_mcp_end_to_end.py")

echo "인터프리터: $PY"
"$PY" -V

declare -a NAMES=() CODES=()
for s in "${STAGES[@]}"; do
  echo
  echo "════════════════════════════════════════════════════════════"
  echo " $s"
  echo "════════════════════════════════════════════════════════════"
  "$PY" "smoketest/$s"
  code=$?
  NAMES+=("$s")
  CODES+=("$code")
done

echo
echo "════════════════════════════════════════════════════════════"
echo " 요약"
echo "════════════════════════════════════════════════════════════"
fail=0
for i in "${!NAMES[@]}"; do
  c="${CODES[$i]}"
  case "$c" in
    0) label="PASS" ;;
    3) label="SKIP" ;;
    *) label="FAIL"; fail=1 ;;
  esac
  printf "  [%s] %s (exit=%s)\n" "$label" "${NAMES[$i]}" "$c"
done

echo
if [ "$fail" -eq 0 ]; then
  echo "  전부 통과했습니다."
else
  echo "  실패한 단계가 있습니다. 위 로그의 [FAIL] 줄을 확인하세요."
fi
echo "  상세 결과: smoketest/_result_*.json"
echo
exit "$fail"
