#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

FAIL=0

# Build list of scannable text files (skip binaries, raw_inputs, target, .venv, .git, *.local.yaml)
mapfile -t FILES < <(
  find . \
    -path './.git' -prune -o \
    -path './.venv' -prune -o \
    -path './target' -prune -o \
    -path './raw_inputs' -prune -o \
    -path './__pycache__' -prune -o \
    -path '*/__pycache__' -prune -o \
    -path './.pytest_cache' -prune -o \
    -path './.mypy_cache' -prune -o \
    -path './.ruff_cache' -prune -o \
    -path './.hypothesis' -prune -o \
    -name '.coverage*' -prune -o \
    -name '*.local.yaml' -prune -o \
    -name '*.png' -prune -o \
    -name '*.jpg' -prune -o \
    -name '*.jpeg' -prune -o \
    -name '*.ico' -prune -o \
    -name '*.pdf' -prune -o \
    -name '*.docx' -prune -o \
    -name '*.odt' -prune -o \
    -name '*.doc' -prune -o \
    -type f -print
)

if [[ ${#FILES[@]} -eq 0 ]]; then
  exit 0
fi

# 1. Check for tracked/present *.local.yaml if git repo
if [[ -d .git ]]; then
  TRACKED_LOCAL="$(git ls-files 'authors/*.local.yaml' || true)"
  if [[ -n "$TRACKED_LOCAL" ]]; then
    echo "ERROR: Private local author profile tracked in git: $TRACKED_LOCAL" >&2
    FAIL=1
  fi
fi

# 2. Check for secret keys / private keys
SECRET_HITS="$(grep -nEI '(sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36}|BEGIN (RSA|OPENSSH|EC|DSA) PRIVATE KEY)' "${FILES[@]}" 2>/dev/null || true)"
if [[ -n "$SECRET_HITS" ]]; then
  echo "ERROR: Potential secret detected:" >&2
  echo "$SECRET_HITS" >&2
  FAIL=1
fi

# 3. Check for machine-specific home paths (excluding this scanner itself)
PATH_FILES=()
for f in "${FILES[@]}"; do
  [[ "$f" == "./scripts/scan_secrets_and_paths.sh" ]] && continue
  PATH_FILES+=("$f")
done

if [[ ${#PATH_FILES[@]} -gt 0 ]]; then
  PATH_HITS="$(grep -nE '(/home/[a-zA-Z0-9._-]+/|/Users/[a-zA-Z0-9._-]+/|C:\\Users\\[a-zA-Z0-9._-]+\\)' "${PATH_FILES[@]}" 2>/dev/null || true)"
  if [[ -n "$PATH_HITS" ]]; then
    echo "ERROR: Machine-specific path detected:" >&2
    echo "$PATH_HITS" >&2
    FAIL=1
  fi
fi

# 4. Check for private emails in non-local tracked author profiles
if [[ -d authors ]]; then
  for af in authors/*.yaml; do
    [[ -e "$af" ]] || continue
    [[ "$af" == *.local.yaml ]] && continue
    if grep -nEI '([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}|^\s*(email|consent)\s*:)' "$af" >/dev/null 2>&1; then
      echo "ERROR: Private email/consent found in tracked author file: $af" >&2
      FAIL=1
    fi
  done
fi

exit "$FAIL"
