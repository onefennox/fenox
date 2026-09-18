#!/usr/bin/env bash
# Fenox Mobile installer
#
# One-liner (no repo needed):
#   curl -fsSL https://raw.githubusercontent.com/onefennox/fenox-mobile/main/install.sh | bash
#
# From a clone:
#   git clone https://github.com/onefennox/fenox-mobile.git && cd fenox-mobile && bash install.sh
#
# Fast path  : download a prebuilt, checksum-verified binary from GitHub Releases
# Fallback   : build from this repo's source with PyInstaller
#
# Supported: Linux (x86_64, aarch64) and WSL. macOS and Windows are not.
set -euo pipefail

REPO="onefennox/fenox-mobile"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}" 2>/dev/null)" 2>/dev/null && pwd || pwd)"
SRC="$REPO_DIR/src/fenox_mobile_source.py"
BIN_DIR="$HOME/.local/bin"

# --- platform guard -----------------------------------------------------------
# Fenox ships prebuilt binaries for Linux (x86_64 + aarch64) and runs under WSL.
# Other platforms have no build, so refuse rather than installing something that
# cannot start.
case "$(uname -s)" in
  Linux) ;;
  Darwin)
    echo "❌ macOS is not supported — fenox targets Linux and WSL only."
    echo "   There is no macOS build, and the Linux binaries cannot run here."
    exit 1 ;;
  *)
    echo "❌ Unsupported OS: $(uname -s) — fenox supports Linux and WSL."
    echo "   (A native Windows client is planned as a separate GUI app.)"
    exit 1 ;;
esac

ARCH="$(uname -m)"; [ "$ARCH" = "arm64" ] && ARCH="aarch64"
[ "$ARCH" = "x86_64" ] || [ "$ARCH" = "aarch64" ] || { echo "❌ Unsupported arch: $ARCH (fenox ships x86_64 and aarch64)"; exit 1; }

mkdir -p "$BIN_DIR"

sha256_of() { # sha256_of <file> -> lowercase digest
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | cut -d' ' -f1
  else echo "❌ Need sha256sum (or shasum) to verify the download." >&2; return 1; fi
}

fetch() { # fetch <url> <out>
  if command -v curl >/dev/null 2>&1; then curl -fsSL "$1" -o "$2"
  elif command -v wget >/dev/null 2>&1; then wget -qO "$2" "$1"
  else return 1; fi
}

get_latest_tag() {
  fetch "https://api.github.com/repos/$REPO/releases/latest" - 2>/dev/null |
    grep -oE '"tag_name":\s*"v[^"]+"' | head -1 | grep -oE 'v[^"]+' || true
}

get_expected_sum() { # get_expected_sum <tag> <asset> -> sha256 digest on stdout, else non-zero
  # NOTE: one assignment per `local` — bash expands every word in a single
  # `local a=1 b="$a"` before assigning any of them, so `$tag` below must be
  # declared on its own line. Under `set -u` the single-line form aborts here.
  local tag="$1"
  local asset="$2"
  local base="https://github.com/$REPO/releases/download/$tag"
  local tmp
  local sum=""
  tmp="$(mktemp)"

  # Prefer the aggregate SHA256SUMS; fall back to a per-asset .sha256 file.
  # Compare the asset name exactly — a "<asset>.sha256" entry must not match.
  if fetch "$base/SHA256SUMS" "$tmp" 2>/dev/null; then
    sum="$(awk -v a="$asset" '$2 == a || $2 == "*" a { print $1; exit }' "$tmp" 2>/dev/null || true)"
  fi
  if [ "${#sum}" != "64" ]; then
    rm -f "$tmp"
    if fetch "$base/$asset.sha256" "$tmp" 2>/dev/null; then
      sum="$(awk '{ print $1; exit }' "$tmp" 2>/dev/null || true)"
    fi
  fi

  rm -f "$tmp"
  [ "${#sum}" = "64" ] && { echo "$sum"; return 0; }
  return 1
}

install_binary() { # install_binary <file>
  local f="$1"
  chmod +x "$f"
  for dest in "$BIN_DIR/fenox-mobile" /usr/local/bin/fenox-mobile; do
    if [ -f "$dest" ] && [ ! -L "$dest" ]; then
      cp "$dest" "$dest.bak-$(date +%Y%m%d%H%M%S)" 2>/dev/null || true
      break
    fi
  done
  mv "$f" "$BIN_DIR/fenox-mobile"
  ln -sf "$BIN_DIR/fenox-mobile" "$BIN_DIR/fenox"
}

finish() { # finish <version>
  "$BIN_DIR/fenox-mobile" --generate-aliases >/dev/null 2>&1 || true
  echo ""
  echo "✅ fenox-mobile v$1 installed → $BIN_DIR/fenox-mobile (alias: fenox)"
  echo "   Run 'fenox init' for first-run setup. Try: fenox connect | fenox devices"
}

# --- Test hook: source the helpers above without performing an install --------
if [ "${FENOX_INSTALL_LIB_ONLY:-0}" = "1" ]; then
  return 0 2>/dev/null || exit 0
fi

# --- Mode A: piped/remote (no repo on disk) — download release binary ---------
if [ ! -f "$SRC" ]; then
  TAG="$(get_latest_tag)"
  [ -n "$TAG" ] || { echo "❌ Could not determine the latest release. Install from a clone instead:"; echo "   git clone https://github.com/$REPO.git && cd fenox-mobile && bash install.sh"; exit 1; }
  VER="${TAG#v}"
  BASE="https://github.com/$REPO/releases/download/$TAG"
  ASSET="fenox-mobile-linux-$ARCH"
  TMP="$(mktemp -d)"
  echo "📥 Downloading prebuilt $ASSET $TAG ..."
  fetch "$BASE/$ASSET" "$TMP/fenox-mobile" || { echo "❌ Download failed. Build from source instead: git clone https://github.com/$REPO.git"; rm -rf "$TMP"; exit 1; }
  EXPECTED="$(get_expected_sum "$TAG" "$ASSET")" || { echo "❌ No checksum file — refusing to install."; rm -rf "$TMP"; exit 1; }
  actual="$(sha256_of "$TMP/fenox-mobile")" || { rm -rf "$TMP"; exit 1; }
  [ "$EXPECTED" = "$actual" ] || { echo "❌ Checksum mismatch — refusing to install."; rm -rf "$TMP"; exit 1; }
  install_binary "$TMP/fenox-mobile"
  rm -rf "$TMP"
  finish "$VER"
  exit 0
fi

# --- Mode B: inside a repo clone ----------------------------------------------
FENOX_VERSION="$(cat "$REPO_DIR/VERSION" 2>/dev/null || echo dev)"

# Fast path: prebuilt release binary
if [ "${FENOX_BUILD_FROM_SOURCE:-0}" != "1" ] && [ "$FENOX_VERSION" != "dev" ]; then
  BASE="https://github.com/$REPO/releases/download/v$FENOX_VERSION"
  ASSET="fenox-mobile-linux-$ARCH"
  TMP="$(mktemp -d)"
  echo "📥 Downloading prebuilt $ASSET v$FENOX_VERSION ..."
  if fetch "$BASE/$ASSET" "$TMP/fenox-mobile"; then
    EXPECTED="$(get_expected_sum "v$FENOX_VERSION" "$ASSET")" || EXPECTED=""
    actual="$(sha256_of "$TMP/fenox-mobile")" || actual=""
    if [ -n "$EXPECTED" ] && [ "$EXPECTED" = "$actual" ]; then
      install_binary "$TMP/fenox-mobile"
      rm -rf "$TMP"
      finish "$FENOX_VERSION"
      exit 0
    fi
    if [ -z "$EXPECTED" ]; then
      echo "❌ No checksum published for $ASSET — refusing to install. Falling back to source build..."
    else
      echo "❌ Checksum mismatch — refusing to install. Falling back to source build..."
    fi
  else
    echo "⚠️  No release binary found for v$FENOX_VERSION — building from source..."
  fi
  rm -rf "$TMP"
fi

# Fallback: build from source
BUILD_ENV="$HOME/.fenox_build_env"
if [ ! -x "$BUILD_ENV/bin/pyinstaller" ]; then
  echo "🔧 Creating build venv at $BUILD_ENV ..."
  python3 -m venv "$BUILD_ENV"
  "$BUILD_ENV/bin/pip" install --quiet --upgrade pip
fi
"$BUILD_ENV/bin/pip" install --quiet pyinstaller rich

python3 -m py_compile "$SRC"   # fail fast — never ship an empty binary
echo "✅ Source compiles ($(wc -l < "$SRC") lines, v$FENOX_VERSION)"

echo "🏗  Building binary with PyInstaller (1-2 min)..."
OUT_DIR="$REPO_DIR/dist"
rm -rf "$OUT_DIR" "$REPO_DIR/build" "$REPO_DIR"/fenox-mobile.spec
(cd "$REPO_DIR" && "$BUILD_ENV/bin/pyinstaller" --onefile --name fenox-mobile \
  --distpath "$OUT_DIR" --workpath "$REPO_DIR/build" --specpath "$REPO_DIR" \
  --hidden-import rich "$SRC" >/dev/null)

[ -f "$OUT_DIR/fenox-mobile" ] || { echo "❌ Build failed"; exit 1; }
install_binary "$OUT_DIR/fenox-mobile"
finish "$FENOX_VERSION"
