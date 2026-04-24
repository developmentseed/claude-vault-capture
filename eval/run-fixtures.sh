#!/usr/bin/env bash
# Run each fixture through curate.py. Uses CAPTURE_MOCK_SDK=1 by default.
# Unset CAPTURE_MOCK_SDK and set CAPTURE_LIVE_TESTS=1 to run against the real API.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$SCRIPT_DIR/.."
FIXTURES="$SCRIPT_DIR/fixtures"
HOOKS="$ROOT/hooks"

export CAPTURE_MOCK_SDK="${CAPTURE_MOCK_SDK:-1}"

if [[ "${CAPTURE_LIVE_TESTS:-0}" == "1" ]]; then
    unset CAPTURE_MOCK_SDK
fi

VAULT_TMP=$(mktemp -d)
LOG_TMP=$(mktemp -d)
trap 'rm -rf "$VAULT_TMP" "$LOG_TMP"' EXIT

export PYTHONPATH="$HOOKS:${PYTHONPATH:-}"

PASS=0
FAIL=0

run_fixture() {
    local name="$1"
    local fixture="$FIXTURES/${name}.txt"
    if [[ ! -f "$fixture" ]]; then
        echo "SKIP $name (fixture not found)"
        return
    fi

    # Build a minimal JSONL transcript from the fixture
    local transcript_tmp
    transcript_tmp=$(mktemp)
    # Treat entire fixture as one user message for mock purposes
    python3 -c "
import json, sys
content = open('$fixture').read()
print(json.dumps({'role': 'user', 'content': content}))
print(json.dumps({'role': 'user', 'content': content}))
print(json.dumps({'role': 'user', 'content': content}))
" > "$transcript_tmp"

    local session_id="fixture-${name}-$(date +%s)"
    local log_file="$LOG_TMP/log-${name}.md"
    local index_file="$LOG_TMP/index-${name}.tsv"

    if VAULT_DIR="$VAULT_TMP" python3 -c "
import sys, pathlib, json
sys.path.insert(0, '$HOOKS')
import curate

msgs = []
with open('$transcript_tmp') as f:
    for line in f:
        msgs.append(json.loads(line))

curate.run_capture(
    transcript=msgs,
    session_id='$session_id',
    cwd='/tmp',
    vault_dir='$VAULT_TMP',
    log_path=pathlib.Path('$log_file'),
    index_path=pathlib.Path('$index_file'),
    date_str='$(date +%Y-%m-%d)',
)
" 2>&1; then
        echo "PASS $name"
        PASS=$((PASS + 1))
    else
        echo "FAIL $name"
        FAIL=$((FAIL + 1))
    fi
    rm -f "$transcript_tmp"
}

for fixture_file in "$FIXTURES"/*.txt; do
    name=$(basename "$fixture_file" .txt)
    run_fixture "$name"
done

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]]
