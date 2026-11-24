#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

OUT_DIR="${CASPER_VERIFY_DIR:-$ROOT/target/verify}"
VENV_BIN="$ROOT/.venv/bin"
PYTHON="$VENV_BIN/python"
RUFF="$VENV_BIN/ruff"
MYPY="$VENV_BIN/mypy"
PYTEST="$VENV_BIN/pytest"

if [[ ! -x "$PYTHON" ]]; then
  PYTHON="$(command -v python3)"
fi
if [[ ! -x "$RUFF" ]]; then
  RUFF="$(command -v ruff || true)"
fi
if [[ ! -x "$MYPY" ]]; then
  MYPY="$(command -v mypy || true)"
fi
if [[ ! -x "$PYTEST" ]]; then
  PYTEST="$PYTHON -m pytest"
fi

ALL_TIERS=(smoke unit integration system security perf stress torture)
ALL_STAGES=(lint-ruff type-mypy spec-sync secret-scan "${ALL_TIERS[@]}" coverage)

usage() {
  cat <<'EOF'
Usage: scripts/verify.sh [--quick | --tier <t1,t2> | --only <stage...> | --match <expr> | --failed | --list | --status | --report]
EOF
}

MODE="full"
TIERS_ARG=""
ONLY_ARGS=()
MATCH_EXPR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --quick)
      MODE="quick"
      shift
      ;;
    --tier)
      MODE="tier"
      TIERS_ARG="${2:-}"
      shift 2
      ;;
    --only)
      MODE="only"
      shift
      while [[ $# -gt 0 && "$1" != --* ]]; do
        ONLY_ARGS+=("$1")
        shift
      done
      ;;
    --match)
      MATCH_EXPR="${2:-}"
      shift 2
      ;;
    --failed)
      MODE="failed"
      shift
      ;;
    --list)
      printf '%s\n' "${ALL_STAGES[@]}"
      exit 0
      ;;
    --status)
      if [[ -f "$OUT_DIR/STATUS" ]]; then
        cat "$OUT_DIR/STATUS"
        exit 0
      else
        echo "NO_RUN"
        exit 1
      fi
      ;;
    --report)
      if [[ -f "$OUT_DIR/report.md" ]]; then
        cat "$OUT_DIR/report.md"
        exit 0
      else
        echo "No report found at $OUT_DIR/report.md" >&2
        exit 1
      fi
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

mkdir -p "$OUT_DIR"

STAGES=()
case "$MODE" in
  quick)
    STAGES=(lint-ruff type-mypy spec-sync secret-scan smoke unit)
    ;;
  tier)
    IFS=',' read -r -a STAGES <<< "$TIERS_ARG"
    ;;
  only)
    STAGES=("${ONLY_ARGS[@]}")
    ;;
  failed)
    if [[ -f "$OUT_DIR/summary.tsv" ]]; then
      while IFS=$'\t' read -r st res _rest; do
        if [[ "$res" == "FAIL" ]]; then
          STAGES+=("$st")
        fi
      done < <(tail -n +2 "$OUT_DIR/summary.tsv")
    fi
    if [[ ${#STAGES[@]} -eq 0 ]]; then
      echo "PASS 0/0 0s skips=0"
      exit 0
    fi
    ;;
  full)
    STAGES=(lint-ruff type-mypy spec-sync secret-scan "${ALL_TIERS[@]}" coverage)
    ;;
esac

export CASPER_IN_VERIFY=1

START_TS="$(date +%s)"
TOTAL="${#STAGES[@]}"
PASSED=0
FAILED=0
TOTAL_SKIPS=0
FAILED_STAGES=()

printf 'stage\tstatus\tduration_s\tskips\n' > "$OUT_DIR/summary.tsv"

stage_dir_name() {
  echo "$1" | tr '/:' '__'
}

parse_skips() {
  local logfile="$1"
  local skips=0
  if grep -Eo '[0-9]+ skipped' "$logfile" >/dev/null 2>&1; then
    skips="$(grep -Eo '[0-9]+ skipped' "$logfile" | awk '{s+=$1} END{print s+0}')"
  fi
  echo "$skips"
}

run_pytest_target() {
  local target="$1"
  local logfile="$2"
  local junit="$3"
  local extra_args=()
  if [[ -n "$MATCH_EXPR" ]]; then
    extra_args+=(-k "$MATCH_EXPR")
  fi
  $PYTEST "$target" -q --tb=short --junitxml="$junit" "${extra_args[@]}" >"$logfile" 2>&1
}

run_stage() {
  local stage="$1"
  local sdir="$OUT_DIR/$(stage_dir_name "$stage")"
  mkdir -p "$sdir"
  local logfile="$sdir/log"
  local failfile="$sdir/fail.txt"
  local statusfile="$sdir/status"
  local junit="$sdir/junit.xml"
  rm -f "$failfile" "$junit"

  local t0 t1 dur rc=0 skips=0
  t0="$(date +%s)"

  case "$stage" in
    lint-ruff)
      if [[ -n "$RUFF" ]]; then
        "$RUFF" check . >"$logfile" 2>&1 || rc=$?
      else
        echo "ruff not found" >"$logfile"
        rc=1
      fi
      ;;
    type-mypy)
      if [[ -n "$MYPY" ]]; then
        "$MYPY" src/ >"$logfile" 2>&1 || rc=$?
      else
        echo "mypy not found" >"$logfile"
        rc=1
      fi
      ;;
    spec-sync)
      "$PYTHON" scripts/build_spec.py --check >"$logfile" 2>&1 || rc=$?
      ;;
    secret-scan)
      bash scripts/scan_secrets_and_paths.sh >"$logfile" 2>&1 || rc=$?
      ;;
    smoke|unit|integration|system|security|perf|stress|torture)
      local tdir="tests/$stage"
      if [[ -d "$tdir" ]] && find "$tdir" -name 'test_*.py' -print -quit | grep -q .; then
        run_pytest_target "$tdir" "$logfile" "$junit" || rc=$?
        skips="$(parse_skips "$logfile")"
      else
        echo "No tests in $tdir (0 collected)" >"$logfile"
        rc=0
      fi
      ;;
    coverage)
      $PYTEST tests \
        --cov=src/casper \
        --cov-branch \
        --cov-report=term-missing \
        --cov-report=json:"$OUT_DIR/coverage.json" \
        -q --tb=short >"$logfile" 2>&1 || rc=$?
      skips="$(parse_skips "$logfile")"
      if [[ $rc -eq 0 ]]; then
        "$PYTHON" - "$OUT_DIR/coverage.json" >>"$logfile" 2>&1 <<'PY' || rc=$?
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
totals = data["totals"]
line_pct = totals.get("percent_covered_lines")
if line_pct is None:
    stmts = totals.get("num_statements", 0)
    covered = totals.get("covered_lines", 0)
    line_pct = (100.0 * covered / stmts) if stmts else 100.0
branches = totals.get("num_branches", 0)
cov_branches = totals.get("covered_branches", 0)
branch_pct = (100.0 * cov_branches / branches) if branches else 100.0
print(f"Coverage summary: line={line_pct:.2f}% (min 90.00%), branch={branch_pct:.2f}% (min 85.00%)")
if line_pct < 90.0 or branch_pct < 85.0:
    sys.stderr.write(f"Coverage threshold failed: line={line_pct:.2f}% branch={branch_pct:.2f}%\n")
    sys.exit(1)
PY
      fi
      ;;
    *)
      local candidate=""
      if [[ -e "tests/${stage}.py" ]]; then
        candidate="tests/${stage}.py"
      elif [[ -e "tests/${stage}" ]]; then
        candidate="tests/${stage}"
      elif [[ -e "$stage" ]]; then
        candidate="$stage"
      else
        echo "Unknown stage or test target: $stage" >"$logfile"
        rc=1
      fi
      if [[ -n "$candidate" ]]; then
        run_pytest_target "$candidate" "$logfile" "$junit" || rc=$?
        skips="$(parse_skips "$logfile")"
      fi
      ;;
  esac

  t1="$(date +%s)"
  dur=$((t1 - t0))
  TOTAL_SKIPS=$((TOTAL_SKIPS + skips))

  if [[ $rc -eq 0 ]]; then
    echo "PASS" >"$statusfile"
    PASSED=$((PASSED + 1))
    printf '%s\tPASS\t%s\t%s\n' "$stage" "$dur" "$skips" >> "$OUT_DIR/summary.tsv"
  else
    echo "FAIL" >"$statusfile"
    tail -n 40 "$logfile" > "$failfile"
    FAILED=$((FAILED + 1))
    FAILED_STAGES+=("$stage")
    printf '%s\tFAIL\t%s\t%s\n' "$stage" "$dur" "$skips" >> "$OUT_DIR/summary.tsv"
  fi
}

for st in "${STAGES[@]}"; do
  run_stage "$st"
done

END_TS="$(date +%s)"
ELAPSED=$((END_TS - START_TS))

# Aggregate JUnit XML + Markdown report
"$PYTHON" - "$OUT_DIR" "$PASSED" "$FAILED" "$TOTAL" "$ELAPSED" "$TOTAL_SKIPS" <<'PY'
import sys, xml.etree.ElementTree as ET
from pathlib import Path

out_dir = Path(sys.argv[1])
passed, failed, total, elapsed, skips = map(int, sys.argv[2:7])

# Build combined junit.xml
root = ET.Element("testsuites", name="casper-verify")
for sub in sorted(out_dir.iterdir()):
    j = sub / "junit.xml"
    if j.is_file():
        try:
            tree = ET.parse(j)
            r = tree.getroot()
            if r.tag == "testsuites":
                for child in list(r):
                    root.append(child)
            elif r.tag == "testsuite":
                root.append(r)
        except ET.ParseError:
            pass
ET.ElementTree(root).write(out_dir / "junit.xml", encoding="utf-8", xml_declaration=True)

# Build report.md
lines = [
    "# Casper Verification Report",
    "",
    f"- Passed: {passed}/{total}",
    f"- Failed: {failed}/{total}",
    f"- Duration: {elapsed}s",
    f"- Skips: {skips}",
    "",
    "| Stage | Status | Duration (s) | Skips |",
    "|---|---|---:|---:|",
]
tsv = (out_dir / "summary.tsv").read_text(encoding="utf-8").splitlines()[1:]
for row in tsv:
    cols = row.split("\t")
    if len(cols) == 4:
        lines.append(f"| `{cols[0]}` | **{cols[1]}** | {cols[2]} | {cols[3]} |")
(out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
PY

if [[ $FAILED -eq 0 ]]; then
  SUMMARY="PASS ${PASSED}/${TOTAL} ${ELAPSED}s skips=${TOTAL_SKIPS}"
  echo "$SUMMARY" > "$OUT_DIR/STATUS"
  echo "$SUMMARY"
  exit 0
else
  JOINED="$(IFS=,; echo "${FAILED_STAGES[*]}")"
  FIRST_DIR="$(stage_dir_name "${FAILED_STAGES[0]}")"
  SUMMARY="FAIL ${FAILED}/${TOTAL}: ${JOINED} -> target/verify/${FIRST_DIR}/fail.txt"
  echo "$SUMMARY" > "$OUT_DIR/STATUS"
  echo "$SUMMARY"
  exit 1
fi
