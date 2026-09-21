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

echo "Installing Fenox"
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

if [ "${INSTALL_SERVICE}" -eq 1 ] && command -v systemctl >/dev/null 2>&1; then
  UNIT_DIR="${HOME}/.config/systemd/user"
  mkdir -p "${UNIT_DIR}"
  sed "s|%h/.local/share/fenox/venv/bin/fenox|${VENV_DIR}/bin/fenox|" \
    "${REPO_DIR}/packaging/fenox.service" > "${UNIT_DIR}/fenox.service" 2>/dev/null || true
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
  echo "  systemctl --user daemon-reload && systemctl --user enable --now fenox"
fi
