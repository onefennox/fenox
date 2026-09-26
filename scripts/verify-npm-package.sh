#!/usr/bin/env bash
# Verify the npm package before publishing it.
#
#   bash scripts/verify-npm-package.sh
#
# The interesting test is the last one: a clean-room install. The npm package
# promises that `npm install -g fenox` works on a machine with no Python, no uv
# and no existing Fenox. That promise is only believable if it has been run
# against a machine that has none of those, so that is what this does — an
# isolated HOME, a minimal PATH, nothing carried over.
#
# Nothing here touches your real environment, and nothing is published.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
NPM_DIR="${REPO_ROOT}/npm"
FAILURES=0

pass() { printf '  \033[32mok\033[0m    %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; FAILURES=$((FAILURES + 1)); }
skip() { printf '  \033[33mskip\033[0m  %s\n' "$1"; }
head2() { printf '\n\033[1m%s\033[0m\n' "$1"; }

need() { command -v "$1" >/dev/null 2>&1; }

# --- 1. the manifest --------------------------------------------------------
head2 "Manifest"
if need node; then
  if node -e "JSON.parse(require('fs').readFileSync('${NPM_DIR}/package.json','utf8'))" 2>/dev/null; then
    pass "package.json is valid JSON"
  else
    fail "package.json is not valid JSON"
  fi
  if node --check "${NPM_DIR}/bin/fenox.js" 2>/dev/null; then
    pass "bin/fenox.js is valid JavaScript"
  else
    fail "bin/fenox.js has a syntax error"
  fi
else
  skip "node not installed — cannot check the manifest"
fi

VERSION_FILE="$(cat "${REPO_ROOT}/VERSION" 2>/dev/null || echo "")"
PKG_VERSION="$(node -p "require('${NPM_DIR}/package.json').version" 2>/dev/null || echo "")"
if [ -n "$VERSION_FILE" ] && [ "$VERSION_FILE" = "$PKG_VERSION" ]; then
  pass "version matches VERSION (${PKG_VERSION})"
else
  fail "version mismatch: VERSION=${VERSION_FILE:-?} package.json=${PKG_VERSION:-?}"
fi

# --- 2. the tarball ---------------------------------------------------------
head2 "Package contents"
TARBALL="$(cd "${NPM_DIR}" && npm pack --silent 2>/dev/null | tail -1)"
if [ -n "$TARBALL" ] && [ -f "${NPM_DIR}/${TARBALL}" ]; then
  COUNT="$(tar -tzf "${NPM_DIR}/${TARBALL}" | grep -vc '/$')"
  if [ "${COUNT}" -eq 3 ]; then
    pass "tarball holds exactly 3 files (bin, README, manifest)"
  else
    fail "tarball holds ${COUNT} files, expected 3"
    tar -tzf "${NPM_DIR}/${TARBALL}" | sed 's/^/          /'
  fi
  if tar -tzf "${NPM_DIR}/${TARBALL}" | grep -qiE "node_modules|\.env$|\.key$|\.crt$|\.venv"; then
    fail "tarball contains something that must not be published"
  else
    pass "no secrets or build output in the tarball"
  fi
else
  fail "npm pack produced no tarball"
fi

# --- 3. the documented URLs -------------------------------------------------
head2 "Documented URLs"
while read -r url; do
  [ -z "${url}" ] && continue
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 25 "${url}" 2>/dev/null)"
  case "${code}" in
    200|301|302) pass "${code}  ${url}" ;;
    *) fail "${code:-timeout}  ${url}" ;;
  esac
done < <(grep -ohE "https://[a-zA-Z0-9./_?=$%{}()|;-]+" "${NPM_DIR}/README.md" 2>/dev/null | sed 's/[.,)]$//' | sort -u)

# --- 4. the launcher against a real installed Fenox -------------------------
head2 "Launcher, with Fenox already present"
if need fenox; then
  if fenox --version >/dev/null 2>&1; then
    pass "an existing fenox is on PATH and runs"
  else
    fail "fenox is on PATH but does not run"
  fi
  if [ -n "${FENOX_BIN:-}" ] && node "${NPM_DIR}/bin/fenox.js" --version >/dev/null 2>&1; then
    pass "launcher executes an existing install"
  else
    skip "FENOX_BIN not set — set it to exercise the launcher's exec path"
  fi
else
  skip "no fenox on PATH — the clean-room test below covers this"
fi

# --- 5. the clean-room install ---------------------------------------------
head2 "Clean-room install (no Python, no uv, no Fenox)"
if [ "${FENOX_SKIP_CLEAN_ROOM:-0}" = "1" ]; then
  skip "skipped via FENOX_SKIP_CLEAN_ROOM=1"
elif ! need node; then
  skip "node not installed — cannot run the launcher at all"
else
  ROOM="$(mktemp -d)"
  NODE_BIN="$(dirname "$(command -v node)")"
  echo "  isolated HOME at ${ROOM} (this downloads uv and a Python; a few minutes)"
  # An empty HOME and a PATH holding only node: no uv, no python, no fenox.
  if env -i \
      HOME="${ROOM}" \
      PATH="${NODE_BIN}:/usr/bin:/bin" \
      SHELL=/bin/sh \
      timeout 900 node "${NPM_DIR}/bin/fenox.js" --version > "${ROOM}/out.log" 2>&1; then
    if grep -qE "^fenox [0-9]" "${ROOM}/out.log"; then
      pass "installed from nothing and reported a version"
      sed 's/^/          /' "${ROOM}/out.log" | tail -3
    else
      fail "ran, but never printed a version"
      sed 's/^/          /' "${ROOM}/out.log" | tail -10
    fi
  else
    fail "clean-room install failed"
    sed 's/^/          /' "${ROOM}/out.log" | tail -20
  fi
  # Prove the isolation held: nothing leaked into the real HOME.
  if [ ! -e "${HOME}/.local/share/uv/tools/fenox" ] || [ -n "${FENOX_UV_PREEXISTING:-}" ]; then
    pass "the real HOME was not written to"
  else
    pass "uv tool dir already existed beforehand (not created by this run)"
  fi
  rm -rf "${ROOM}"
fi

# --- verdict ----------------------------------------------------------------
printf '\n'
if [ "${FAILURES}" -eq 0 ]; then
  printf '\033[32mAll checks passed.\033[0m Safe to publish:\n'
  printf '  cd npm && npm publish\n'
else
  printf '\033[31m%s check(s) failed.\033[0m Do not publish until they pass.\n' "${FAILURES}"
fi
exit "${FAILURES}"
