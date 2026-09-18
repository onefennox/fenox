#!/usr/bin/env bash
# End-to-end test of the release -> install path, with no GitHub involved.
#
# Usage:
#   tests/test_release_e2e.sh /path/to/fenox
#
# Build a binary the way .github/workflows/release.yml does, then point this at it:
#   pip install pyinstaller rich
#   pyinstaller --onefile --name fenox --distpath dist --workpath /tmp \
#     --specpath /tmp src/fenox.py
#   tests/test_release_e2e.sh dist/fenox
#
# The test stages a real release layout (binary + .sha256 + SHA256SUMS), serves it
# over loopback HTTP, rewrites install.sh's GitHub URLs at that server, and then
# exercises: the one-liner path (Mode A), the repo-clone path (Mode B), the
# per-asset .sha256 fallback, and tamper detection. Every scenario runs under its
# own throwaway $HOME so nothing on the real machine is touched.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_SH="$HERE/../install.sh"
BINARY="${1:-${FENOX_TEST_BINARY:-}}"

if [ -z "$BINARY" ] || [ ! -f "$BINARY" ]; then
  echo "usage: $0 /path/to/fenox   (see header for how to build it)" >&2
  exit 2
fi
if [ ! -f "$INSTALL_SH" ]; then
  echo "❌ cannot find install.sh at $INSTALL_SH" >&2
  exit 2
fi

ARCH="$(uname -m)"; [ "$ARCH" = "arm64" ] && ARCH="aarch64"
case "$ARCH" in x86_64|aarch64) ;; *) echo "❌ unsupported arch: $ARCH" >&2; exit 2 ;; esac
OTHER_ARCH=$([ "$ARCH" = "x86_64" ] && echo aarch64 || echo x86_64)
ASSET="fenox-linux-$ARCH"
TAG="v1.0.1"

T="$(mktemp -d)"
PORT="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')"
SERVER_PID=""
cleanup() { [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null; rm -rf "$T"; }
trap cleanup EXIT

PASS=0; FAIL=0
check() { # check <desc> <expected> <actual>
  if [ "$2" = "$3" ]; then PASS=$((PASS+1)); printf '  \033[32mok\033[0m   %s\n' "$1"
  else FAIL=$((FAIL+1)); printf '  \033[31mFAIL\033[0m %s\n       expected: %s\n       actual:   %s\n' "$1" "$2" "$3"; fi
}

# --- stage the release layout exactly as release.yml does ----------------------
SERVE="$T/serve"
REL="$SERVE/download/$TAG"
mkdir -p "$REL" "$SERVE/releases"
cp "$BINARY" "$REL/$ASSET"
cp "$BINARY" "$REL/fenox-linux-$OTHER_ARCH"   # decoy: must never be selected
( cd "$REL" && for a in fenox-linux-*; do sha256sum "$a" > "$a.sha256"; done
             cat fenox-linux-*.sha256 > SHA256SUMS )
printf '{"tag_name": "%s"}\n' "$TAG" > "$SERVE/releases/latest.json"
GOOD_SUM="$(cut -d' ' -f1 < "$REL/$ASSET.sha256")"

echo "release staged: $ASSET, sha256 $GOOD_SUM"

# --- serve it over loopback ---------------------------------------------------
python3 -m http.server "$PORT" --bind 127.0.0.1 --directory "$SERVE" >/dev/null 2>&1 &
SERVER_PID=$!
for _ in $(seq 1 50); do
  curl -fsS -o /dev/null "http://127.0.0.1:$PORT/releases/latest.json" 2>/dev/null && break
  sleep 0.2
done
curl -fsS -o /dev/null "http://127.0.0.1:$PORT/releases/latest.json" || { echo "❌ local release server never came up" >&2; exit 1; }

# --- point install.sh at the local server (a copy; the real file is untouched) --
mk_install_copy() { # mk_install_copy <dest>
  sed -e "s|https://api.github.com/repos/\$REPO/releases/latest|http://127.0.0.1:$PORT/releases/latest.json|g" \
      -e "s|https://github.com/\$REPO/releases/download|http://127.0.0.1:$PORT/download|g" \
      "$INSTALL_SH" > "$1"
  if grep -q 'github.com/\$REPO/releases/download' "$1"; then
    echo "❌ URL rewrite failed — install.sh changed shape" >&2; exit 1
  fi
}

# Mode A (one-liner): no repo on disk, so the script must resolve the latest tag.
run_mode_a() { # run_mode_a <home>
  HOME="$1" bash "$T/install-a.sh" > "$T/modeA.log" 2>&1
}
# Mode B (clone): src/ + VERSION present next to the script.
run_mode_b() { # run_mode_b <home>
  HOME="$1" bash "$T/clone/install-b.sh" > "$T/modeB.log" 2>&1
}

mk_install_copy "$T/install-a.sh"
mkdir -p "$T/clone/src"
mk_install_copy "$T/clone/install-b.sh"
printf '1.0.1\n' > "$T/clone/VERSION"
cp "$HERE/../src/fenox.py" "$T/clone/src/"

assert_installed() { # assert_installed <desc> <home>
  local desc="$1" home="$2" got
  got="$(sha256sum "$home/.local/bin/fenox" 2>/dev/null | cut -d' ' -f1)"
  check "$desc: binary installed with the published digest" "$GOOD_SUM" "$got"
  check "$desc: fenox symlink resolves" "$home/.local/bin/fenox" "$(readlink -f "$home/.local/bin/fenox" 2>/dev/null)"
  if HOME="$home" "$home/.local/bin/fenox" --version >/dev/null 2>&1; then
    check "$desc: installed binary runs" "0" "0"
  else
    check "$desc: installed binary runs" "0" "nonzero"
  fi
}

echo
echo "Mode A — one-liner install"
mkdir -p "$T/home-a"
run_mode_a "$T/home-a"; rc=$?
check "Mode A exits 0" "0" "$rc"
assert_installed "Mode A" "$T/home-a"

echo
echo "Mode B — install from a repo clone"
mkdir -p "$T/home-b"
run_mode_b "$T/home-b"; rc=$?
check "Mode B exits 0" "0" "$rc"
assert_installed "Mode B" "$T/home-b"

echo
echo "Fallback — SHA256SUMS missing, per-asset .sha256 used"
mv "$REL/SHA256SUMS" "$T/SHA256SUMS.hidden"
mkdir -p "$T/home-f"
run_mode_a "$T/home-f"; rc=$?
check "fallback exits 0" "0" "$rc"
assert_installed "fallback" "$T/home-f"
mv "$T/SHA256SUMS.hidden" "$REL/SHA256SUMS"

echo
echo "Tamper — served binary no longer matches the published digest"
cp "$REL/$ASSET" "$T/pristine"
printf 'tampered' >> "$REL/$ASSET"
mkdir -p "$T/home-t"
run_mode_a "$T/home-t"; rc=$?
check "tampered download is refused" "1" "$rc"
check "tampered binary was NOT installed" "" "$(ls "$T/home-t/.local/bin/fenox" 2>/dev/null)"
grep -qi 'checksum mismatch' "$T/modeA.log" && check "log explains the refusal" "0" "0" \
  || check "log explains the refusal" "0" "$(tail -1 "$T/modeA.log")"

echo
echo "True digest still accepted after the tamper test"
cp "$T/pristine" "$REL/$ASSET"
mkdir -p "$T/home-r"
run_mode_a "$T/home-r"; rc=$?
check "restored release installs" "0" "$rc"
assert_installed "restored" "$T/home-r"

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
