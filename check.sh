#!/usr/bin/env bash
# Type check (pyrefly strict) and run the tests. Prints only problems and a summary.
set -uo pipefail
cd "$(dirname "$0")"

status=0
types=$(uv run --quiet pyrefly check --summary=none --output-format min-text 2>&1 | grep -v '^ INFO')
if [ -n "$types" ]; then
    echo "$types"
    status=1
fi
echo "types: $([ -z "$types" ] && echo ok || echo "$(grep -c '^ERROR' <<<"$types") errors")"

uv run --quiet pytest "$@" || status=1
exit $status
