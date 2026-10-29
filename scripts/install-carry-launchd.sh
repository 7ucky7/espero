#!/usr/bin/env bash
# Run the two #12 carry paper books under launchd, so they survive closed terminal
# tabs, app restarts and logins: taker (paper) and maker (paper, its perp leg
# mirrored with resting orders on the Hyperliquid TESTNET).
#
#   ./scripts/install-carry-launchd.sh               # install both and start them
#   ./scripts/install-carry-launchd.sh --uninstall   # stop both and remove them
#   ./scripts/install-carry-launchd.sh --status      # running? last exit?
#   ./scripts/install-carry-launchd.sh --print       # render the plists to stdout, change nothing
#
# The books (carry-taker.db, carry-maker.db) live in the repo root unless STATE_DIR
# is set. Logs go to ~/Library/Logs/espero/carry-taker.log and carry-maker.log.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE="$REPO/deploy/launchd/com.espero.carry.plist.template"
STATE_DIR="${STATE_DIR:-$REPO}"
LOG_DIR="${ESPERO_LOG_DIR:-$HOME/Library/Logs/espero}"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
DOMAIN="gui/$(id -u)"
BOOKS="taker maker"

label() { echo "com.espero.carry-$1"; }
plist() { echo "$HOME/Library/LaunchAgents/$(label "$1").plist"; }

render() {  # render <costs>
    local costs="$1" execute=""
    [ "$costs" = maker ] && execute="<string>--execute-testnet</string>"
    sed -e "s|__LABEL__|$(label "$costs")|g" \
        -e "s|__PYTHON__|$PYTHON|g" \
        -e "s|__REPO__|$REPO|g" \
        -e "s|__COSTS__|$costs|g" \
        -e "s|__STATE__|$STATE_DIR/carry-$costs.db|g" \
        -e "s|__NAME__|carry-$costs|g" \
        -e "s|__LOG_DIR__|$LOG_DIR|g" \
        -e "s|__EXECUTE__|$execute|g" \
        "$TEMPLATE"
}

case "${1:-}" in
    --print)
        for b in $BOOKS; do render "$b"; done
        exit 0 ;;
    --uninstall)
        for b in $BOOKS; do
            launchctl bootout "$DOMAIN/$(label "$b")" 2>/dev/null || true
            rm -f "$(plist "$b")"
            echo "removed $(label "$b")"
        done
        exit 0 ;;
    --status)
        for b in $BOOKS; do
            echo "== $(label "$b")"
            launchctl print "$DOMAIN/$(label "$b")" 2>/dev/null | grep -E "^\s+(state|pid|last exit code|runs) =" \
                || echo "   not loaded"
        done
        exit 0 ;;
    "") ;;
    *)
        echo "unknown option $1" >&2
        exit 2 ;;
esac

if ! "$PYTHON" -c "import espero" >/dev/null 2>&1; then
    echo "$PYTHON cannot import espero; install the package into it first" >&2
    exit 1
fi
mkdir -p "$LOG_DIR" "$STATE_DIR" "$HOME/Library/LaunchAgents"

for b in $BOOKS; do
    render "$b" > "$(plist "$b")"
    plutil -lint "$(plist "$b")" >/dev/null
    launchctl bootout "$DOMAIN/$(label "$b")" 2>/dev/null || true
    launchctl bootstrap "$DOMAIN" "$(plist "$b")"
    launchctl enable "$DOMAIN/$(label "$b")"
    echo "installed $(label "$b")  ->  $STATE_DIR/carry-$b.db, log $LOG_DIR/carry-$b.log"
done
echo "status:  ./scripts/install-carry-launchd.sh --status"
echo "follow:  tail -f $LOG_DIR/carry-maker.log"
