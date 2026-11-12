#!/bin/sh
# What the investment-assist LaunchAgents run, in this checkout, appending to launchd/<job>.log:
#
#   sh launchd/job.sh weekly   `assist run`: stances → out/, journal, brief, Telegram (Mon 07:00)
#   sh launchd/job.sh regime   `assist regime --check`: Telegram only on a regime change, then the
#                              change-only holding and data health alerts (S90; daily 07:00)
#
# Both jobs fire at 07:00 on Mondays, so each takes launchd/.jobs.lock (lockf, up to 30 minutes)
# and they run one after the other. Exits with the assist exit code (2 for an unknown job).
# launchd's PATH lacks Homebrew, so install.sh puts the absolute uv path in ASSIST_UV.
set -eu
REPO=$(cd "$(dirname "$0")/.." && pwd)

stamp() { date '+%Y-%m-%d %H:%M:%S %Z'; }

JOB=${1:-}
case "$JOB" in
    weekly) set -- run ;;
    regime) set -- regime --check ;;
    *) echo "usage: sh launchd/job.sh weekly|regime" >&2; exit 2 ;;
esac

LOG=$REPO/launchd/$JOB.log
exec >>"$LOG" 2>&1
cd "$REPO"

# Telegram credentials (ASSIST_TELEGRAM_TOKEN, ASSIST_TELEGRAM_CHAT) may live in the gitignored
# .env (chmod 600), as an alternative to the Keychain item; values are never echoed. notify.py
# also reads .env itself (S90), so this export only keeps the env ahead of it.
if [ -f "$REPO/.env" ]; then
    set -a
    . "$REPO/.env"
    set +a
fi

UV=${ASSIST_UV:-$(command -v uv || true)}
if [ -z "$UV" ] || [ ! -x "$UV" ]; then
    echo "$(stamp) uv not found (set ASSIST_UV or put uv on PATH), $JOB not run"
    exit 1
fi
LOCKF=${ASSIST_LOCKF:-/usr/bin/lockf}

echo "$(stamp) $JOB start in $REPO"
code=0
"$LOCKF" -k -t 1800 "$REPO/launchd/.jobs.lock" "$UV" run assist "$@" || code=$?
echo "$(stamp) $JOB end, exit $code"
exit "$code"
