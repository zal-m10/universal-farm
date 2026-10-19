#!/bin/bash
# Universal Farm — uninstaller.
# Removes all farm files, results, state, and the `farm` command.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/zal-m10/universal-farm/main/uninstall.sh | bash
#   or (from a local clone):
#   bash uninstall.sh
#
# What it removes:
#   - ~/universal-farm (repo + venv + all farm code)
#   - ~/harbor-fixed (legacy dir, if present)
#   - /usr/local/bin/farm and ~/.local/bin/farm (the launcher)
#   - Results: /root/*_keys.txt, *_keys_export.txt, account.json
#   - Progress: /root/*_farm_progress.txt
#   - State: ~/.farm_tui.json
#   - Temp logs: /tmp/{farm,dahl-farm,mistral-farm,gonka-farm}-*.log, /tmp/signup-fail-*.png
#
# What it does NOT touch:
#   - 9Router (/var/lib/9router, the 9router npm package, systemd service)
#   - System packages (python3, git, curl, playwright chromium)
#   - Your proxies list outside the repo (if you keep one elsewhere)
set -u

INSTALL_DIR="$HOME/universal-farm"
LEGACY_DIR="$HOME/harbor-fixed"

SUDO=""
if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
fi

echo "=== Universal Farm uninstaller ==="
echo ""
echo "This will DELETE:"
echo "  - $INSTALL_DIR"
[ -d "$LEGACY_DIR" ] && echo "  - $LEGACY_DIR (legacy)"
echo "  - farm command (/usr/local/bin/farm or ~/.local/bin/farm)"
echo "  - All farmed keys, progress files, and Telegram/bot state"
echo ""
printf "Type DELETE to confirm: "
# Read from /dev/tty so it works when piped via curl | bash.
if [ -c /dev/tty ]; then
    read -r CONFIRM </dev/tty
else
    read -r CONFIRM
fi
if [ "$CONFIRM" != "DELETE" ]; then
    echo "Cancelled."
    exit 0
fi
echo ""

# 1. Kill any running farm processes first.
echo "[1/4] Stopping running farms..."
pkill -f "dahl_farm.py" 2>/dev/null || true
pkill -f "gonka_farm.py" 2>/dev/null || true
pkill -f "mistral_farm.py" 2>/dev/null || true
pkill -f "tools.tokenharbor.cli" 2>/dev/null || true
pkill -f "inject_monitor.py" 2>/dev/null || true
sleep 1
echo "  done"

# 2. Remove install directories.
echo "[2/4] Removing farm code..."
for d in "$INSTALL_DIR" "$LEGACY_DIR"; do
    if [ -d "$d" ]; then
        rm -rf "$d"
        echo "  removed $d"
    fi
done

# 3. Remove the `farm` launcher.
echo "[3/4] Removing 'farm' command..."
for bin in "/usr/local/bin/farm" "$HOME/.local/bin/farm"; do
    if [ -f "$bin" ] || [ -L "$bin" ]; then
        $SUDO rm -f "$bin"
        echo "  removed $bin"
    fi
done

# 4. Remove results, progress, state, and temp logs.
echo "[4/4] Removing results and state..."
for f in "$HOME"/dahl_keys.txt \
         "$HOME"/mistral_keys.txt \
         "$HOME"/gonka_keys.txt \
         "$HOME"/dahl_keys_export.txt \
         "$HOME"/mistral_keys_export.txt \
         "$HOME"/gonka_keys_export.txt \
         "$HOME"/dahl_farm_progress.txt \
         "$HOME"/mistral_farm_progress.txt \
         "$HOME"/gonka_farm_progress.txt \
         "$HOME"/.farm_tui.json \
         "$HOME"/dahl_farm.py \
         "$HOME"/mistral_farm.py \
         "$HOME"/gonka_farm.py; do
    if [ -f "$f" ]; then
        rm -f "$f"
        echo "  removed $f"
    fi
done
# Temp logs and failure screenshots.
rm -f /tmp/farm-*.log /tmp/dahl-farm-*.log /tmp/mistral-farm-*.log \
      /tmp/gonka-farm-*.log /tmp/signup-fail-*.png 2>/dev/null || true
rm -f /tmp/farm.pid 2>/dev/null || true
echo "  cleaned /tmp logs"

echo ""
echo "=== Uninstall complete ==="
echo "9Router (if installed) was left untouched."
