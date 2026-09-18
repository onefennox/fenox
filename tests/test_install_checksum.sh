#!/usr/bin/env bash
# Tests for release-checksum resolution in install.sh.
#
# Runs completely offline and installs nothing: install.sh is sourced in
# library-only mode (FENOX_INSTALL_LIB_ONLY=1), which defines the helper
# functions and returns before any download/build/install step. `fetch` is then
# stubbed to serve fixtures from a local directory, so the assertions below
# exercise the real get_expected_sum from the shipped script.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_SH="$HERE/../install.sh"
ASSET="fenox-linux-x86_64"
TAG="v9.9.9"

TMPROOT="$(mktemp -d)"
trap 'rm -rf "$TMPROOT"' EXIT

digest() { # digest <char> -> a 64-char hex-looking digest
  local s; printf -v s '%64s' ''; printf '%s' "${s// /$1}"
}

PASS=0
FAIL=0
check() { # check <desc> <expected> <actual>
  if [ "$2" = "$3" ]; then
    PASS=$((PASS + 1)); printf '  \033[32mok\033[0m   %s\n' "$1"
  else
    FAIL=$((FAIL + 1)); printf '  \033[31mFAIL\033[0m %s\n' "$1"
    printf '       expected: %s\n       actual:   %s\n' "$2" "$3"
  fi
}

# --- load the code under test --------------------------------------------------
export FENOX_INSTALL_LIB_ONLY=1
export HOME="$TMPROOT/home"
mkdir -p "$HOME"
# shellcheck source=../install.sh
. "$INSTALL_SH"
set +e   # install.sh turns on `set -e`; the assertions below need failing commands

if ! declare -F get_expected_sum > /dev/null; then
  echo "❌ get_expected_sum not defined — did sourcing install.sh change?" >&2
  exit 1
fi

FIXTURES=""
fetch() { # fetch <url> <out> — offline stand-in for curl/wget
  local url="$1" out="$2" name
  name="$(basename "${url%%\?*}")"
  [ -f "$FIXTURES/$name" ] || return 1
  if [ "$out" = "-" ]; then cat "$FIXTURES/$name"; else cp "$FIXTURES/$name" "$out"; fi
}

fixtures() { # fixtures <name> — fresh fixture directory, exposed as $FIXTURES
  FIXTURES="$TMPROOT/$1"
  rm -rf "$FIXTURES"; mkdir -p "$FIXTURES"
}

SUM_SUMS="$(digest a)"   # digest served by SHA256SUMS
SUM_FILE="$(digest b)"   # digest served by the per-asset .sha256

run() { # run <desc> <expected-rc> <expected-digest>
  local out rc
  out="$(get_expected_sum "$TAG" "$ASSET")"; rc=$?
  check "$1 (exit)" "$2" "$rc"
  check "$1 (digest)" "$3" "$out"
}

echo "installer checksum resolution"

# 1. The aggregate SHA256SUMS is preferred and matched exactly.
fixtures exact
printf '%s  fenox-linux-aarch64\n%s  %s\n' "$(digest c)" "$SUM_SUMS" "$ASSET" > "$FIXTURES/SHA256SUMS"
printf '%s  %s\n' "$SUM_FILE" "$ASSET" > "$FIXTURES/$ASSET.sha256"
run "SHA256SUMS preferred over .sha256" 0 "$SUM_SUMS"

# 2. sha256sum's binary-mode marker (<digest> *<name>) still matches.
fixtures binary_marker
printf '%s *%s\n' "$SUM_SUMS" "$ASSET" > "$FIXTURES/SHA256SUMS"
run "binary-mode '*' marker accepted" 0 "$SUM_SUMS"

# 3. A SHA256SUMS entry for another architecture must never match.
fixtures wrong_arch
printf '%s  fenox-linux-aarch64\n' "$(digest c)" > "$FIXTURES/SHA256SUMS"
run "other architecture ignored" 1 ""

# 4. A "<asset>.sha256" entry is not the asset itself — exact matching only.
fixtures suffix_entry
printf '%s  %s.sha256\n' "$(digest c)" "$ASSET" > "$FIXTURES/SHA256SUMS"
run "'<asset>.sha256' entry ignored" 1 ""

# 5. A malformed SHA256SUMS digest falls through to the per-asset file
#    instead of aborting the installer.
fixtures malformed
printf '%s  %s\n' "not-a-real-digest" "$ASSET" > "$FIXTURES/SHA256SUMS"
printf '%s  %s\n' "$SUM_FILE" "$ASSET" > "$FIXTURES/$ASSET.sha256"
run "malformed SHA256SUMS falls back" 0 "$SUM_FILE"

# 6. SHA256SUMS missing entirely -> per-asset .sha256.
fixtures fallback_only
printf '%s  %s\n' "$SUM_FILE" "$ASSET" > "$FIXTURES/$ASSET.sha256"
run "per-asset .sha256 fallback" 0 "$SUM_FILE"

# 7. Garbage in SHA256SUMS with no fallback -> refuse, do not guess.
fixtures garbage
printf 'this is not a checksum file\n' > "$FIXTURES/SHA256SUMS"
run "garbage SHA256SUMS refused" 1 ""

# 8. Nothing published at all -> refuse.
fixtures nothing
run "no checksum published -> refuse" 1 ""

# 9. A short digest from the per-asset file is rejected (length-validated).
fixtures shortsum
printf 'abc123  %s\n' "$ASSET" > "$FIXTURES/$ASSET.sha256"
run "short digest rejected" 1 ""

# --- the guard must not have run an install ------------------------------------
check "library-only guard installed nothing" "" "$(ls "$HOME/.local/bin" 2>/dev/null | tr '\n' ' ')"

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
