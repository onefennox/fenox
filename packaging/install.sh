#!/usr/bin/env bash
# Fenox installer.
#
#   From a checkout:   bash packaging/install.sh
#   One-liner:         curl -fsSL https://raw.githubusercontent.com/onefenox/fenox/main/packaging/install.sh | bash
#
# Installs Fenox into a private virtual environment under the data directory,
# puts a `fenox` launcher on PATH, and optionally installs the systemd user
# service. Linux and WSL only.
set -euo pipefail

REPO_URL="https://github.com/onefenox/fenox.git"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." 2>/dev/null && pwd || pwd)"
BIN_DIR="${HOME}/.local/bin"
DATA_DIR="${FENOX_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/fenox}"
VENV_DIR="${DATA_DIR}/venv"
INSTALL_SERVICE=1

usage() {
  cat <<'EOF'
Usage: install.sh [options]

Options:
  --data-dir DIR     Data and virtual environment location
                     (default: $XDG_DATA_HOME/fenox or ~/.local/share/fenox)
  --no-service       Do not install the systemd user service
  -h, --help         Show this help
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --data-dir) DATA_DIR="$2"; VENV_DIR="${DATA_DIR}/venv"; shift 2 ;;
    --no-service) INSTALL_SERVICE=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

case "$(uname -s)" in
  Linux) ;;
  *) echo "Fenox supports Linux and WSL only." >&2; exit 1 ;;
esac

PYTHON=""
for candidate in python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
      PYTHON="$candidate"; break
    fi
  fi
done
if [ -z "$PYTHON" ]; then
  echo "Python 3.11 or newer is required." >&2
  exit 1
fi

# --- environment detection ----------------------------------------------------
# The hub runs the same on Linux and WSL; on WSL the Windows adb is the one that
# can see USB, so tell the user which environment this is.
if grep -qi microsoft /proc/version 2>/dev/null || [ -n "${WSL_DISTRO_NAME:-}" ]; then
  FENOX_ENV="WSL${WSL_DISTRO_NAME:+ (${WSL_DISTRO_NAME})}"
else
  FENOX_ENV="Linux"
fi

echo "Installing Fenox"
echo "  environment: ${FENOX_ENV}"
echo "  python     : $($PYTHON --version)"
echo "  data dir   : ${DATA_DIR}"
echo "  launcher   : ${BIN_DIR}/fenox"

mkdir -p "${DATA_DIR}" "${BIN_DIR}"

if [ ! -x "${VENV_DIR}/bin/python" ]; then
  "${PYTHON}" -m venv "${VENV_DIR}"
fi
"${VENV_DIR}/bin/python" -m pip install --quiet --upgrade pip

if [ -f "${REPO_DIR}/pyproject.toml" ] && [ -d "${REPO_DIR}/src/fenox" ]; then
  echo "  source     : ${REPO_DIR}"
  "${VENV_DIR}/bin/python" -m pip install --quiet --upgrade "${REPO_DIR}"
else
  echo "  source     : ${REPO_URL}"
  "${VENV_DIR}/bin/python" -m pip install --quiet --upgrade "fenox @ git+${REPO_URL}"
fi

ln -sf "${VENV_DIR}/bin/fenox" "${BIN_DIR}/fenox"

# --- tool detection -----------------------------------------------------------
echo
"${VENV_DIR}/bin/fenox" doctor || true

# If Flutter was not found, offer to record its location now.
if ! "${VENV_DIR}/bin/fenox" config get flutter_path 2>/dev/null | grep -q .; then
  FOUND_FLUTTER="$("${VENV_DIR}/bin/fenox" doctor 2>/dev/null | awk '/^  flutter /{print $3}')"
  if [ -z "${FOUND_FLUTTER}" ] || [ "${FOUND_FLUTTER}" = "not" ]; then
    if [ -t 0 ] && [ -z "${FENOX_SKIP_PROMPTS:-}" ]; then
      printf 'Flutter was not found. Enter the path to your Flutter SDK (blank to skip): '
      read -r FLUTTER_PATH || FLUTTER_PATH=""
      if [ -n "${FLUTTER_PATH}" ]; then
        "${VENV_DIR}/bin/fenox" config set flutter_path "${FLUTTER_PATH}"
      else
        echo "Skipped. You can set it later with: fenox config set flutter_path /path/to/flutter"
      fi
    else
      echo "Set it later with: fenox config set flutter_path /path/to/flutter"
    fi
  fi
fi

# --- service ------------------------------------------------------------------
if [ "${INSTALL_SERVICE}" -eq 1 ] && command -v systemctl >/dev/null 2>&1; then
  "${VENV_DIR}/bin/fenox" service install || true
fi

echo
echo "Fenox installed. Start it with:"
echo "  fenox"
case ":${PATH}:" in
  *":${BIN_DIR}:"*) ;;
  *) echo "  (add ${BIN_DIR} to PATH first)" ;;
esac
if [ "${INSTALL_SERVICE}" -eq 1 ] && [ -f "${HOME}/.config/systemd/user/fenox.service" ]; then
  echo "Or run it in the background:"
  echo "  systemctl --user enable --now fenox"
fi
