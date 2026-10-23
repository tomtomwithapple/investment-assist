#!/bin/sh
# Installs (or removes) the two investment-assist LaunchAgents:
#
#   com.tommy.investment-assist.weekly   Monday 07:00 local time (WIB): `assist run`
#   com.tommy.investment-assist.regime   daily 07:00 local time (WIB): `assist regime --check`
#
#   sh launchd/install.sh              render both plists, copy them to ~/Library/LaunchAgents, bootstrap
#   sh launchd/install.sh --dry-run    print the rendered plists only; writes nothing
#   sh launchd/install.sh --uninstall  boot both out and remove the plists
#
# The plists in git are templates: this fills in the repo path and the absolute uv path
# (`command -v uv`), since launchd's PATH lacks /opt/homebrew/bin. The repo is the main checkout
# (not a worktree, whose ../ is not the siblings root); ASSIST_REPO overrides it and
# ASSIST_LAUNCH_AGENTS the target dir (tests use both). StartCalendarInterval is in this Mac's
# local time zone, which is WIB.
set -eu
LABELS="com.tommy.investment-assist.weekly com.tommy.investment-assist.regime"
REPO=${ASSIST_REPO:-/Users/tomtomtomtom/Projects/investment-assist}
TEMPLATES=$(cd "$(dirname "$0")" && pwd)
AGENTS=${ASSIST_LAUNCH_AGENTS:-$HOME/Library/LaunchAgents}
DOMAIN=gui/$(id -u)

stamp() { date '+%Y-%m-%d %H:%M:%S'; }
usage() { echo "usage: sh launchd/install.sh [--dry-run|--uninstall]" >&2; }

MODE=install
case "${1:-}" in
    "") ;;
    --dry-run) MODE=dry-run ;;
    --uninstall) MODE=uninstall ;;
    -h|--help) usage; exit 0 ;;
    *) usage; exit 2 ;;
esac
if [ $# -gt 1 ]; then usage; exit 2; fi

if [ "$MODE" = uninstall ]; then
    for LABEL in $LABELS; do
        launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
        rm -f "$AGENTS/$LABEL.plist"
        echo "$(stamp) removed $LABEL ($AGENTS/$LABEL.plist)"
    done
    exit 0
fi

if [ ! -f "$REPO/launchd/job.sh" ]; then
    echo "no launchd/job.sh under $REPO; set ASSIST_REPO to the investment-assist checkout" >&2
    exit 1
fi
UV=$(command -v uv || true)
case "$UV" in
    /*) ;;
    *) echo "uv not found on PATH; install uv (https://docs.astral.sh/uv/) and retry" >&2; exit 1 ;;
esac
UV_DIR=$(dirname "$UV")

render() {
    sed -e "s|__REPO__|$REPO|g" -e "s|__UV_DIR__|$UV_DIR|g" -e "s|__UV__|$UV|g" \
        -e '/<!-- Template:/d' "$TEMPLATES/$1.plist"
}

if [ "$MODE" = dry-run ]; then
    for LABEL in $LABELS; do
        render "$LABEL"
    done
    exit 0
fi

mkdir -p "$AGENTS"
for LABEL in $LABELS; do
    render "$LABEL" > "$AGENTS/$LABEL.plist"
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    launchctl bootstrap "$DOMAIN" "$AGENTS/$LABEL.plist"
    echo "$(stamp) installed $LABEL ($AGENTS/$LABEL.plist)"
done
echo "  repo: $REPO   uv: $UV"
echo "  logs: $REPO/launchd/weekly.log, $REPO/launchd/regime.log"
echo "  remove: sh launchd/install.sh --uninstall"
