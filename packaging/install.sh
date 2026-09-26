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
INSTALL_SYSTEM=0
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
  --system           Install system-wide for all users, using the usual FHS
                     layout: code in /usr/local/lib/fenox, launcher in
                     /usr/local/bin/fenox, data in /var/lib/fenox.
                     Run with sudo:  sudo bash install.sh --system
  --no-service       Do not install the systemd user service
  -h, --help         Show this help

Without --system this installs for the current user only, and never needs root.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --data-dir) DATA_DIR="$2"; VENV_DIR="${DATA_DIR}/venv"; shift 2 ;;
    --system)
      INSTALL_SYSTEM=1
      BIN_DIR="/usr/local/bin"
      DATA_DIR="/var/lib/fenox"
      VENV_DIR="${DATA_DIR}/venv"
      shift
      ;;
    --no-service) INSTALL_SERVICE=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

# Refuse a system install that is not actually elevated, rather than scattering
# files into /usr/local and then failing halfway through.
if [ "${INSTALL_SYSTEM}" -eq 1 ] && [ "$(id -u)" -ne 0 ]; then
  echo "--system needs root. Re-run as: sudo bash install.sh --system" >&2
  exit 1
fi

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
  # Say what to do, not merely that it failed. Hermes and friends go further and
  # install a runtime for you; that is a deliberate non-goal here, because
  # quietly installing a Python on someone's machine is a bigger surprise than
  # telling them the one command that fixes it.
  cat >&2 <<EOF
Python 3.11 or newer is required, and none was found on PATH.

  Debian / Ubuntu : sudo apt install python3.12 python3.12-venv
  Fedora          : sudo dnf install python3.12
  Arch            : sudo pacman -S python
  macOS           : brew install python@3.12

Or install with uv, which manages the Python for you:
  curl -LsSf https://astral.sh/uv/install.sh | sh
  uv tool install "fenox @ git+${REPO_URL}"
EOF
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
# `doctor` exits non-zero when it finds a problem, which is normal during an
# install, so its status must not abort the script.
"${VENV_DIR}/bin/fenox" doctor || true

# If Flutter was not found, offer to record its location now. The answer is read
# from the JSON report rather than the human-readable one: parsing the printed
# table here meant that reformatting the report silently broke the installer.
FOUND_FLUTTER="$("${VENV_DIR}/bin/fenox" doctor --json 2>/dev/null | "${VENV_DIR}/bin/python" -c '
import json, sys
try:
    tools = json.load(sys.stdin).get("tools", [])
except Exception:
    tools = []
print(next((t["path"] for t in tools if t.get("name") == "flutter" and t.get("present")), ""))
' || true)"

if ! "${VENV_DIR}/bin/fenox" config get flutter_path 2>/dev/null | grep -q .; then
  if [ -z "${FOUND_FLUTTER}" ]; then
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

# The most common "it installed but the command isn't there" is simply that
# ~/.local/bin is not on PATH. Offer to fix it rather than printing a line the
# user has to interpret.
case ":${PATH}:" in
  *":${BIN_DIR}:"*)
    echo "  (${BIN_DIR} is already on your PATH)"
    ;;
  *)
    if [ "${INSTALL_SYSTEM}" -eq 1 ]; then
      echo "  WARNING: ${BIN_DIR} is not on your PATH. Add it with:"
      echo "    export PATH=\"${BIN_DIR}:\$PATH\""
    elif [ -t 0 ] && [ -z "${FENOX_SKIP_PROMPTS:-}" ]; then
      echo "  ${BIN_DIR} is not on your PATH."
      printf 'Add it to your shell profile now? [Y/n] '
      read -r ADD_PATH || ADD_PATH="n"
      case "$(printf '%s' "${ADD_PATH:-Y}" | tr '[:upper:]' '[:lower:]')" in
        y|yes|"")
          for profile in "${HOME}/.bashrc" "${HOME}/.zshrc" "${HOME}/.profile"; do
            if [ -f "${profile}" ] && ! grep -qF "${BIN_DIR}" "${profile}" 2>/dev/null; then
              printf '\n# Added by the Fenox installer\nexport PATH="%s:$PATH"\n' "${BIN_DIR}" >> "${profile}"
              echo "  Added to ${profile}. Open a new terminal, or run: source ${profile}"
              break
            fi
          done
          ;;
        *) echo "  Skipped. Add ${BIN_DIR} to your PATH when you want it." ;;
      esac
    else
      echo "  Add ${BIN_DIR} to your PATH to finish:"
      echo "    export PATH=\"${BIN_DIR}:\$PATH\""
    fi
    ;;
esac

if [ "${INSTALL_SERVICE}" -eq 1 ] && [ -f "${HOME}/.config/systemd/user/fenox.service" ]; then
  echo "Or run it in the background:"
  echo "  systemctl --user enable --now fenox"
fi

if [ "${INSTALL_SYSTEM}" -eq 1 ]; then
  echo
  echo "This was a system-wide install. Data lives in ${DATA_DIR} and is owned by root;"
  echo "run the hub as a normal user by pointing FENOX_DATA_DIR at a directory you own."
fi
