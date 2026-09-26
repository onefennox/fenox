#!/usr/bin/env bash
# Fenox uninstaller.
#
#   From a checkout:   bash packaging/uninstall.sh
#   One-liner:         curl -fsSL https://raw.githubusercontent.com/onefenox/fenox/main/packaging/uninstall.sh | bash
#
# Removes the launcher, the private virtual environment, the systemd service and
# (unless --keep-data is given) the data directory.
#
# What it deliberately never touches: your projects, your Android SDK, the adb
# server or any device, and the repository itself. A tool that uninstalls more
# than it installed is a tool nobody trusts with --purge.
set -euo pipefail

DATA_DIR="${FENOX_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/fenox}"
BIN_DIR="${HOME}/.local/bin"
PURGE=1
ASSUME_YES=0

usage() {
  cat <<'EOF'
Usage: uninstall.sh [options]

Options:
  --keep-data     Keep the data directory (owner credential, database, run
                  history, cached scrcpy server). Use this if you are upgrading
                  rather than starting over.
  --data-dir DIR  Look in DIR instead of the default data location.
  -y, --yes       Do not ask for confirmation.
  -h, --help      Show this help.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --keep-data) PURGE=0; shift ;;
    --data-dir) DATA_DIR="$2"; shift 2 ;;
    -y|--yes) ASSUME_YES=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

# --- what is actually there ------------------------------------------------
TARGETS=()
[ -e "${DATA_DIR}/venv" ] && TARGETS+=("${DATA_DIR}/venv")
[ -e "${DATA_DIR}" ] && TARGETS+=("${DATA_DIR}")
[ -e "${BIN_DIR}/fenox" ] && TARGETS+=("${BIN_DIR}/fenox")
[ -e "${HOME}/.config/systemd/user/fenox.service" ] && TARGETS+=("systemd user service")

if [ ${#TARGETS[@]} -eq 0 ]; then
  echo "Nothing to remove — no Fenox installation found (looked in ${DATA_DIR})."
  exit 0
fi

echo "This will remove:"
for target in "${TARGETS[@]}"; do
  echo "  ${target}"
done
if [ "${PURGE}" -eq 0 ]; then
  echo
  echo "Keeping your data: ${DATA_DIR}"
  echo "  Your owner password, registered devices, projects and run history stay put."
fi

if [ "${ASSUME_YES}" -eq 0 ]; then
  if [ -t 0 ]; then
    printf 'Continue? [y/N] '
    read -r reply || reply="n"
    case "$(printf '%s' "${reply}" | tr '[:upper:]' '[:lower:]')" in
      y|yes) ;;
      *) echo "Cancelled. Nothing was removed."; exit 0 ;;
    esac
  else
    echo
    echo "Not a terminal, so refusing to delete anything. Re-run with -y if you are sure."
    exit 1
  fi
fi

# --- stop anything running -------------------------------------------------
# The service first, then any hub the user started by hand, so nothing is
# writing to the data directory while it is being removed.
if command -v systemctl >/dev/null 2>&1 && [ -e "${HOME}/.config/systemd/user/fenox.service" ]; then
  echo "Stopping the systemd user service…"
  systemctl --user disable --now fenox.service >/dev/null 2>&1 || true
fi

if command -v pkill >/dev/null 2>&1; then
  # Match the module invocation and the console script, not any unrelated process.
  pkill -f "fenox serve" >/dev/null 2>&1 || true
  pkill -f "bin/fenox serve" >/dev/null 2>&1 || true
fi
sleep 1

# --- remove ----------------------------------------------------------------
for target in "${TARGETS[@]}"; do
  case "${target}" in
    "systemd user service")
      rm -f "${HOME}/.config/systemd/user/fenox.service"
      command -v systemctl >/dev/null 2>&1 && systemctl --user daemon-reload >/dev/null 2>&1 || true
      echo "Removed the systemd user service."
      ;;
    "${BIN_DIR}/fenox")
      # Only ever remove our own symlink, never a real executable someone put there.
      if [ -L "${BIN_DIR}/fenox" ]; then
        rm -f "${BIN_DIR}/fenox"
        echo "Removed the launcher at ${BIN_DIR}/fenox."
      else
        echo "Left ${BIN_DIR}/fenox alone: it is a real file, not one of our symlinks."
      fi
      ;;
    *)
      rm -rf "${target}"
      echo "Removed ${target}."
      ;;
  esac
done

echo
if [ "${PURGE}" -eq 1 ]; then
  echo "Fenox is fully removed. Your projects, Android SDK, adb and any connected"
  echo "phone were not touched."
else
  echo "Fenox is removed. Your data is still in ${DATA_DIR} — delete it yourself if"
  echo "you want a completely clean slate."
fi
