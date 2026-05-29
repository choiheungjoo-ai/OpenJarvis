#!/usr/bin/env bash
# block-2.1-probe.sh
# Step 2.1 investigation harness. Read-only. Touches nothing.
# Run from the repo root:  bash block-2.1-probe.sh
# Gathers the five investigation findings the decision memo needs.
#
# OpenJarvis-source location: this assumes the forked OpenJarvis package
# sits somewhere under the repo. Adjust OJ_ROOT if the probe finds nothing.

set -uo pipefail

REPO_ROOT="${1:-$HOME/newton-v4}"
cd "$REPO_ROOT" || { echo "FATAL: cannot cd to $REPO_ROOT"; exit 1; }

# Try to locate the OpenJarvis package root. Newton's own package is newton/.
# Everything that is NOT newton/, tests/, docs/, migrations/, scripts/ is
# candidate OpenJarvis territory. Override by passing a 2nd arg.
OJ_ROOT="${2:-}"

line() { printf '\n========== %s ==========\n' "$1"; }

line "0. CONTEXT"
echo "repo root : $REPO_ROOT"
echo "branch    : $(git branch --show-current 2>/dev/null)"
echo "HEAD      : $(git log --oneline -1 2>/dev/null)"
echo "git clean : $(test -z "$(git status --porcelain)" && echo yes || echo NO-DIRTY)"

line "0b. PACKAGE LAYOUT (top 2 levels, dirs only)"
find . -maxdepth 2 -type d \
  -not -path '*/.git*' -not -path '*/.venv*' -not -path '*/node_modules*' \
  -not -path '*/__pycache__*' | sort

# Heuristic: find the upstream package dir(s). Look for a top-level dir that
# is not one of Newton's own and contains an __init__.py.
if [ -z "$OJ_ROOT" ]; then
  for d in */; do
    d="${d%/}"
    case "$d" in
      newton|tests|docs|migrations|scripts|data|config|.git|.venv|node_modules) continue ;;
    esac
    if [ -f "$d/__init__.py" ] || find "$d" -maxdepth 2 -name '__init__.py' -print -quit | grep -q .; then
      OJ_ROOT="$OJ_ROOT $d"
    fi
  done
fi
echo
echo "candidate OpenJarvis package dir(s): ${OJ_ROOT:-<none found — pass as 2nd arg>}"

line "1. DOES OPENJARVIS HAVE TOOL / FUNCTION-CALLING CODE? (item 1)"
echo "--- files whose path mentions tool/function/skill ---"
find . -type f -name '*.py' \
  -not -path './newton/*' -not -path './tests/*' \
  -not -path '*/.venv/*' -not -path '*/__pycache__/*' \
  | grep -iE 'tool|function_call|funcall|skill' | sort
echo
echo "--- class/def definitions that look tool-ish (outside newton/) ---"
grep -rn -E 'class .*(Tool|Skill|Function|Registry)|def .*(tool|skill|function_call|dispatch)' \
  --include='*.py' . \
  2>/dev/null \
  | grep -v '^\./newton/' | grep -v '^\./tests/' | grep -v '\.venv/' \
  | head -60

line "2. HOW ARE TOOL CALLS WIRED THROUGH THE LLM ADAPTER / OLLAMA? (item 2)"
echo "--- ollama / llm-adapter touchpoints ---"
grep -rni -E 'ollama|llm.?adapter|chat\(|\.generate\(|tool_calls|tools=' \
  --include='*.py' . 2>/dev/null \
  | grep -v '^\./newton/' | grep -v '\.venv/' | grep -v '^\./tests/' \
  | head -50

line "3. OPENJARVIS DEPENDENCIES (item 3: pydantic v1 vs v2, jsonschema, instructor)"
echo "--- pyproject.toml dependency blocks ---"
if [ -f pyproject.toml ]; then
  awk '/^\[project\]|^\[tool\.poetry\.dependencies\]|dependencies *=/{f=1} f{print} /^\[/&&!/dependencies/&&NR>1{if(seen)f=0} {seen=1}' pyproject.toml 2>/dev/null | head -60
  echo "..."
  grep -niE 'pydantic|jsonschema|instructor|ollama|fastapi' pyproject.toml
fi
echo
echo "--- INSTALLED pydantic version (authoritative) ---"
uv run python -c "import pydantic; print('pydantic', pydantic.VERSION)" 2>/dev/null \
  || python -c "import pydantic; print('pydantic', pydantic.VERSION)" 2>/dev/null \
  || echo "could not import pydantic in env"
echo
echo "--- other relevant installed versions ---"
uv run python - <<'PY' 2>/dev/null || true
for m in ("jsonschema","instructor","ollama","fastapi","sqlalchemy","click","pyyaml"):
    try:
        mod = __import__(m)
        print(m, getattr(mod, "__version__", "?"))
    except Exception as e:
        print(m, "NOT-INSTALLED")
PY

line "3b. PYDANTIC V1-vs-V2 USAGE SIGNALS IN OPENJARVIS SOURCE"
echo "v2 signals (model_config, field_validator, model_dump):"
grep -rn -E 'model_config|field_validator|model_dump|model_validate' \
  --include='*.py' . 2>/dev/null | grep -v '^\./newton/' | grep -v '\.venv/' | wc -l
echo "v1 signals (class Config, @validator, .dict(), .parse_obj):"
grep -rn -E 'class Config:|@validator|\.dict\(\)|parse_obj' \
  --include='*.py' . 2>/dev/null | grep -v '^\./newton/' | grep -v '\.venv/' | wc -l

line "4. IS THERE A REGISTRY NEWTON COULD REGISTER INTO? (item 4)"
grep -rn -E 'class .*Registry|register\(|_registry|REGISTRY' \
  --include='*.py' . 2>/dev/null \
  | grep -v '^\./newton/' | grep -v '\.venv/' | grep -v '^\./tests/' \
  | head -40
echo
echo "(If the above shows a clean, importable registry with a stable register()"
echo " signature, 'register into it' is viable. If it is entangled with skills/"
echo " learning/UI, prefer a SEPARATE Newton registry that dispatches itself.)"

line "5. RISK-LEVEL RE-CHECK INPUT (item 5)"
echo "Enumerate the actual OpenJarvis tools/skills so their real actions can be"
echo "bucketed against the 5 proposed levels (0 SAFE .. 4 WRITE_NETWORK):"
echo
grep -rn -E 'class .*(Tool|Skill)\b' --include='*.py' . 2>/dev/null \
  | grep -v '^\./newton/' | grep -v '\.venv/' | sort
echo
echo "For each tool above, note in the memo: does it (a) only compute/echo [0],"
echo "(b) read local fs/sys [1], (c) write local fs [2], (d) read network [3],"
echo "(e) write/send over network [4]? If NO tool exercises a level, that level"
echo "is a candidate for collapse (doc TERMINOLOGY §12 + block-2 risk matrix)."

line "DONE"
echo "Paste this entire output into the chat, or save it next to the memo:"
echo "  bash block-2.1-probe.sh | tee docs/newton/block-2.1-probe-output.txt"
