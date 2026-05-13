#!/usr/bin/env bash
# Newton v4 — preflight check + auto-fix
#
# 사용법:
#   ./scripts/preflight.sh              # 진단만, 자동 복구 X (수동 모드)
#   ./scripts/preflight.sh --auto-fix   # 자동 복구 (Ollama 시작, uv sync, 모델 pull)
#   ./scripts/preflight.sh --yes        # 큰 모델 pull도 확인 없이 (>5GB)
#   ./scripts/preflight.sh --quiet      # 출력 최소화
#   ./scripts/preflight.sh --help
#
# 종료 코드:
#   0 — 모든 검사 통과
#   1 — 한 가지 이상 실패 (자동 복구 불가 또는 거부)
#   2 — 사용법 오류

set -uo pipefail

# ─────────────────────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
REQUIRED_MODELS_FILE="${SCRIPT_DIR}/required-models.txt"

# 최소 버전 요구
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=12
MIN_UV_VERSION="0.11.0"

# Ollama
OLLAMA_HOST="http://localhost:11434"
OLLAMA_START_TIMEOUT=10

# 출력 색상 (TTY일 때만)
if [[ -t 1 ]]; then
    C_RESET='\033[0m'
    C_GREEN='\033[0;32m'
    C_RED='\033[0;31m'
    C_YELLOW='\033[0;33m'
    C_BLUE='\033[0;34m'
    C_DIM='\033[2m'
    C_BOLD='\033[1m'
else
    C_RESET='' C_GREEN='' C_RED='' C_YELLOW='' C_BLUE='' C_DIM='' C_BOLD=''
fi

# 플래그
AUTO_FIX=0
ASSUME_YES=0
QUIET=0

# 카운터
TOTAL_CHECKS=9
CURRENT_CHECK=0
FAILED=0
FIXED=0

# ─────────────────────────────────────────────────────────────
# 인자 파싱
# ─────────────────────────────────────────────────────────────

while [[ $# -gt 0 ]]; do
    case "$1" in
        --auto-fix) AUTO_FIX=1; shift ;;
        --yes|-y)   ASSUME_YES=1; AUTO_FIX=1; shift ;;
        --quiet|-q) QUIET=1; shift ;;
        --help|-h)
            sed -n '2,12p' "$0"
            exit 0
            ;;
        *)
            echo "알 수 없는 인자: $1" >&2
            echo "도움말: $0 --help" >&2
            exit 2
            ;;
    esac
done

# ─────────────────────────────────────────────────────────────
# 출력 헬퍼
# ─────────────────────────────────────────────────────────────

log() { [[ $QUIET -eq 0 ]] && echo -e "$@"; }

start_check() {
    CURRENT_CHECK=$((CURRENT_CHECK + 1))
    local label="$1"
    local padded
    padded=$(printf "%-32s" "$label")
    if [[ $QUIET -eq 0 ]]; then
        printf "[%d/%d] %s " "$CURRENT_CHECK" "$TOTAL_CHECKS" "$padded"
    fi
}

pass() {
    local msg="${1:-}"
    log "${C_GREEN}✓${C_RESET} ${msg}"
}

fail() {
    local msg="${1:-}"
    log "${C_RED}✗${C_RESET} ${msg}"
    FAILED=$((FAILED + 1))
}

warn() {
    local msg="${1:-}"
    log "${C_YELLOW}⚠${C_RESET} ${msg}"
}

fix_msg() {
    local msg="${1:-}"
    log "${C_BLUE}⟳${C_RESET} ${msg}"
    FIXED=$((FIXED + 1))
}

hint() {
    [[ $QUIET -eq 0 ]] && echo -e "    ${C_DIM}$1${C_RESET}"
}

# ─────────────────────────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────────────────────────

# semver 비교: 0 if $1 >= $2, 1 otherwise
version_ge() {
    [[ "$1" == "$2" ]] && return 0
    local IFS=.
    local v1=($1) v2=($2)
    local i
    for ((i=0; i<${#v1[@]} || i<${#v2[@]}; i++)); do
        local a=${v1[i]:-0}
        local b=${v2[i]:-0}
        if ((10#$a > 10#$b)); then return 0; fi
        if ((10#$a < 10#$b)); then return 1; fi
    done
    return 0
}

confirm() {
    local prompt="$1"
    if [[ $ASSUME_YES -eq 1 ]]; then
        log "    ${C_DIM}${prompt} → yes (--yes)${C_RESET}"
        return 0
    fi
    read -r -p "    ${prompt} [y/N] " ans
    [[ "$ans" =~ ^[Yy]$ ]]
}

# ─────────────────────────────────────────────────────────────
# 헤더
# ─────────────────────────────────────────────────────────────

log "${C_BOLD}Newton v4 — preflight${C_RESET}"
log "${C_DIM}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}"
if [[ $AUTO_FIX -eq 1 ]]; then
    log "${C_DIM}모드: auto-fix$([[ $ASSUME_YES -eq 1 ]] && echo " + assume-yes")${C_RESET}"
fi
log ""

# ─────────────────────────────────────────────────────────────
# Check 1 — Python ≥3.12
# ─────────────────────────────────────────────────────────────

start_check "python ≥${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}"
if command -v python3 >/dev/null 2>&1; then
    PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')
    PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
    if [[ $PY_MAJOR -gt $MIN_PYTHON_MAJOR ]] || \
       { [[ $PY_MAJOR -eq $MIN_PYTHON_MAJOR ]] && [[ $PY_MINOR -ge $MIN_PYTHON_MINOR ]]; }; then
        pass "$PY_VER"
    else
        fail "$PY_VER (요구: ≥${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR})"
        hint "Ubuntu: sudo apt install python3.12"
    fi
else
    fail "python3 not found"
    hint "Ubuntu: sudo apt install python3 python3-pip"
fi

# ─────────────────────────────────────────────────────────────
# Check 2 — uv ≥0.11
# ─────────────────────────────────────────────────────────────

start_check "uv ≥${MIN_UV_VERSION}"
if command -v uv >/dev/null 2>&1; then
    UV_VER=$(uv --version 2>/dev/null | awk '{print $2}')
    if version_ge "$UV_VER" "$MIN_UV_VERSION"; then
        pass "$UV_VER"
    else
        fail "$UV_VER (요구: ≥${MIN_UV_VERSION})"
        hint "업데이트: curl -LsSf https://astral.sh/uv/install.sh | sh"
    fi
else
    fail "uv not found"
    hint "설치: curl -LsSf https://astral.sh/uv/install.sh | sh"
fi

# ─────────────────────────────────────────────────────────────
# Check 3 — git + user.name/email
# ─────────────────────────────────────────────────────────────

start_check "git + user config"
if command -v git >/dev/null 2>&1; then
    GIT_NAME=$(git config --global user.name 2>/dev/null || echo "")
    GIT_EMAIL=$(git config --global user.email 2>/dev/null || echo "")
    if [[ -n "$GIT_NAME" && -n "$GIT_EMAIL" ]]; then
        pass "${GIT_NAME} <${GIT_EMAIL}>"
    else
        fail "user.name/email 미설정"
        hint 'git config --global user.name "Your Name"'
        hint 'git config --global user.email "you@example.com"'
    fi
else
    fail "git not found"
    hint "Ubuntu: sudo apt install git"
fi

# ─────────────────────────────────────────────────────────────
# Check 4 — Ollama 바이너리
# ─────────────────────────────────────────────────────────────

start_check "ollama binary"
if command -v ollama >/dev/null 2>&1; then
    OLLAMA_VER=$(ollama --version 2>/dev/null | awk '{print $NF}')
    pass "$OLLAMA_VER"
else
    fail "ollama not found"
    hint "설치: curl -fsSL https://ollama.com/install.sh | sh"
fi

# ─────────────────────────────────────────────────────────────
# Check 5 — Ollama 서버 :11434 (auto-fix 가능)
# ─────────────────────────────────────────────────────────────

start_check "ollama server"
if curl -fsS -m 3 "${OLLAMA_HOST}/api/tags" >/dev/null 2>&1; then
    pass "up @ ${OLLAMA_HOST}"
else
    if [[ $AUTO_FIX -eq 1 ]] && command -v ollama >/dev/null 2>&1; then
        fix_msg "starting ollama serve..."
        nohup ollama serve > /tmp/ollama-preflight.log 2>&1 &
        # 부팅 대기
        for i in $(seq 1 $OLLAMA_START_TIMEOUT); do
            sleep 1
            if curl -fsS -m 2 "${OLLAMA_HOST}/api/tags" >/dev/null 2>&1; then
                log "    ${C_GREEN}✓${C_RESET} up after ${i}s"
                break
            fi
            if [[ $i -eq $OLLAMA_START_TIMEOUT ]]; then
                fail "시작 실패 (${OLLAMA_START_TIMEOUT}s timeout)"
                hint "로그 확인: tail /tmp/ollama-preflight.log"
            fi
        done
    else
        fail "down @ ${OLLAMA_HOST}"
        hint "수동: nohup ollama serve > /tmp/ollama.log 2>&1 &"
        hint "또는: $0 --auto-fix"
    fi
fi

# ─────────────────────────────────────────────────────────────
# Check 6 — NVIDIA GPU (경고만, 실패 X)
# ─────────────────────────────────────────────────────────────

start_check "nvidia gpu"
if command -v nvidia-smi >/dev/null 2>&1; then
    GPU_INFO=$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | head -1)
    if [[ -n "$GPU_INFO" ]]; then
        pass "$GPU_INFO"
    else
        warn "nvidia-smi 출력 없음"
    fi
else
    warn "nvidia-smi not found (CPU-only 모드로 진행)"
fi

# ─────────────────────────────────────────────────────────────
# Check 7 — ~/newton-v4 git repo
# ─────────────────────────────────────────────────────────────

start_check "newton-v4 repo"
if [[ -d "${PROJECT_ROOT}/.git" ]]; then
    BRANCH=$(git -C "${PROJECT_ROOT}" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "?")
    pass "branch=${BRANCH}"
else
    fail "git repo not found at ${PROJECT_ROOT}"
    hint "Step 1.1 안내 참조"
fi

# ─────────────────────────────────────────────────────────────
# Check 8 — .venv 동기화 (auto-fix 가능)
# ─────────────────────────────────────────────────────────────

start_check ".venv synced"
VENV_DIR="${PROJECT_ROOT}/.venv"
if [[ -d "${VENV_DIR}" ]]; then
    # uv가 sync 필요한지 빠르게 dry-check (uv.lock vs .venv)
    if (cd "${PROJECT_ROOT}" && uv sync --extra dev --frozen --quiet 2>/dev/null); then
        PKG_COUNT=$(find "${VENV_DIR}/lib" -maxdepth 3 -name "site-packages" -exec ls {} \; 2>/dev/null | wc -l)
        pass "${PKG_COUNT} packages"
    else
        if [[ $AUTO_FIX -eq 1 ]]; then
            fix_msg "uv sync --extra dev..."
            if (cd "${PROJECT_ROOT}" && uv sync --extra dev --quiet); then
                log "    ${C_GREEN}✓${C_RESET} synced"
            else
                fail "uv sync 실패"
            fi
        else
            fail "out of sync"
            hint "수동: cd ${PROJECT_ROOT} && uv sync --extra dev"
            hint "또는: $0 --auto-fix"
        fi
    fi
else
    if [[ $AUTO_FIX -eq 1 ]]; then
        fix_msg ".venv 생성 + uv sync..."
        if (cd "${PROJECT_ROOT}" && uv sync --extra dev --quiet); then
            log "    ${C_GREEN}✓${C_RESET} created"
        else
            fail "uv sync 실패"
        fi
    else
        fail ".venv 없음"
        hint "수동: cd ${PROJECT_ROOT} && uv sync --extra dev"
    fi
fi

# ─────────────────────────────────────────────────────────────
# Check 9 — 필수 Ollama 모델 (auto-fix 가능, 큰 모델은 확인)
# ─────────────────────────────────────────────────────────────

start_check "required models"
if [[ ! -f "${REQUIRED_MODELS_FILE}" ]]; then
    warn "required-models.txt 없음 — skip"
elif ! curl -fsS -m 3 "${OLLAMA_HOST}/api/tags" >/dev/null 2>&1; then
    fail "Ollama down — skip"
else
    # 현재 받아둔 모델 목록
    INSTALLED=$(curl -fsS "${OLLAMA_HOST}/api/tags" | python3 -c '
import json, sys
data = json.load(sys.stdin)
for m in data.get("models", []):
    print(m["name"])
' 2>/dev/null)

    # 필수 모델 파싱
    MISSING=()
    MISSING_SIZES=()
    TOTAL=0
    FOUND_COUNT=0
    while IFS= read -r line; do
        # 주석/빈 줄 skip
        line=$(echo "$line" | sed 's/#.*//' | xargs)
        [[ -z "$line" ]] && continue
        TOTAL=$((TOTAL + 1))
        # "<model>  <size>" 형태
        model=$(echo "$line" | awk '{print $1}')
        size=$(echo "$line" | awk '{print $2}')
        if echo "$INSTALLED" | grep -qFx "$model"; then
            FOUND_COUNT=$((FOUND_COUNT + 1))
        else
            MISSING+=("$model")
            MISSING_SIZES+=("${size:-?}")
        fi
    done < "${REQUIRED_MODELS_FILE}"

    if [[ ${#MISSING[@]} -eq 0 ]]; then
        pass "${FOUND_COUNT}/${TOTAL}"
    else
        if [[ $AUTO_FIX -eq 1 ]]; then
            warn "${FOUND_COUNT}/${TOTAL} (missing: ${MISSING[*]})"
            for i in "${!MISSING[@]}"; do
                model="${MISSING[$i]}"
                size="${MISSING_SIZES[$i]}"
                # 큰 모델 (>5GB) 확인
                size_int=${size%.*}
                if [[ "$size_int" =~ ^[0-9]+$ ]] && [[ $size_int -gt 5 ]]; then
                    if ! confirm "pull ${model} (~${size}GB)?"; then
                        log "    ${C_YELLOW}⚠${C_RESET} skipped ${model}"
                        FAILED=$((FAILED + 1))
                        continue
                    fi
                fi
                fix_msg "pulling ${model}..."
                if ollama pull "${model}" 2>&1 | tail -3; then
                    log "    ${C_GREEN}✓${C_RESET} ${model}"
                else
                    fail "${model} pull 실패"
                fi
            done
        else
            fail "${FOUND_COUNT}/${TOTAL} (missing: ${MISSING[*]})"
            hint "수동: $(for m in "${MISSING[@]}"; do echo -n "ollama pull $m; "; done)"
            hint "또는: $0 --auto-fix"
        fi
    fi
fi

# ─────────────────────────────────────────────────────────────
# 결과
# ─────────────────────────────────────────────────────────────

log ""
log "${C_DIM}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}"

if [[ $FAILED -eq 0 ]]; then
    if [[ $FIXED -gt 0 ]]; then
        log "${C_GREEN}${C_BOLD}✓ 통과 (auto-fix: ${FIXED}건)${C_RESET}"
    else
        log "${C_GREEN}${C_BOLD}✓ 모든 검사 통과${C_RESET}"
    fi
    exit 0
else
    log "${C_RED}${C_BOLD}✗ ${FAILED}건 실패${C_RESET}"
    if [[ $AUTO_FIX -eq 0 ]]; then
        log "${C_DIM}자동 복구 시도: $0 --auto-fix${C_RESET}"
    fi
    exit 1
fi
