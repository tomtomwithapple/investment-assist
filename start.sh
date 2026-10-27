#!/bin/sh
# One step from a checkout to the local pages (PLAN S29):
#
#   ./start.sh                  uv sync, assist doctor, assist run --no-send if out/ is stale,
#                               then assist status on http://127.0.0.1:8790/ and open the browser
#   ./start.sh --run            run even when out/ is already today's
#   ./start.sh --no-run         never run; serve whatever out/ holds
#   ./start.sh --send           let the run send its Telegram summary (assist run)
#   ./start.sh --no-open        do not open the browser
#   ./start.sh --port 8799      serve on another port
#   ./start.sh --install-jobs   also install the launchd jobs (sh launchd/install.sh) after the sync
#
# out/ is stale when it holds no stance JSON or the newest out/*/*.json as_of is before today.
# The doctor is informational and a failed run is reported: the pages still start on whatever
# out/ holds. Ctrl-C (or SIGTERM) stops the server. Without --install-jobs this never touches
# ~/Library/LaunchAgents. Env: ASSIST_START_TODAY (YYYY-MM-DD, tests pin the date),
# ASSIST_START_TIMEOUT (seconds to wait for the pages, default 30), UV, OPEN and CURL (commands).
set -eu
cd "$(dirname "$0")"
REPO=$(pwd)

stamp() { date '+%Y-%m-%d %H:%M:%S'; }
usage() {
    echo "usage: ./start.sh [--run|--no-run] [--send] [--no-open] [--port N] [--install-jobs]" >&2
}

RUN=auto
SEND=no
OPEN_BROWSER=yes
PORT=8790
INSTALL_JOBS=no
while [ $# -gt 0 ]; do
    case "$1" in
        --run) [ "$RUN" = skip ] && { usage; exit 2; }; RUN=force ;;
        --no-run) [ "$RUN" = force ] && { usage; exit 2; }; RUN=skip ;;
        --send) SEND=yes ;;
        --no-open) OPEN_BROWSER=no ;;
        --install-jobs) INSTALL_JOBS=yes ;;
        --port)
            case "${2:-}" in
                ''|*[!0-9]*) usage; exit 2 ;;
            esac
            PORT=$2; shift ;;
        -h|--help) usage; exit 0 ;;
        *) usage; exit 2 ;;
    esac
    shift
done

UV=${UV:-uv}
OPEN=${OPEN:-open}
CURL=${CURL:-curl}
TODAY=${ASSIST_START_TODAY:-$(date +%Y-%m-%d)}
TIMEOUT=${ASSIST_START_TIMEOUT:-30}
URL=http://127.0.0.1:$PORT/

if ! command -v "$UV" >/dev/null 2>&1; then
    echo "uv not found on PATH; install uv (https://docs.astral.sh/uv/) and retry" >&2
    exit 1
fi

echo "$(stamp) uv sync in $REPO"
"$UV" sync || { echo "$(stamp) uv sync failed" >&2; exit 1; }

if [ "$INSTALL_JOBS" = yes ]; then
    echo "$(stamp) installing the launchd jobs"
    sh launchd/install.sh || echo "$(stamp) launchd/install.sh failed (exit $?), continuing" >&2
fi

echo "$(stamp) assist doctor"
"$UV" run assist doctor || echo "$(stamp) doctor exited $?, continuing"

# Newest as_of in out/*/*.json, empty when out/ holds none.
newest_as_of() {
    for f in out/*/*.json; do
        [ -f "$f" ] && cat "$f"
    done | sed -n 's/.*"as_of": *"\([0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}\)".*/\1/p' | sort | tail -n 1
}

if [ "$RUN" = auto ]; then
    NEWEST=$(newest_as_of)
    if [ -z "$NEWEST" ]; then
        echo "$(stamp) out/ holds no stance, running"
        RUN=force
    elif [ "$(echo "$NEWEST" | tr -d -)" -lt "$(echo "$TODAY" | tr -d -)" ]; then
        echo "$(stamp) out/ is from $NEWEST, before $TODAY, running"
        RUN=force
    else
        echo "$(stamp) out/ is current ($NEWEST), not running (--run forces it)"
    fi
fi
if [ "$RUN" = force ]; then
    if [ "$SEND" = yes ]; then set -- run; else set -- run --no-send; fi
    echo "$(stamp) assist $*"
    code=0
    "$UV" run assist "$@" || code=$?
    if [ "$code" -ne 0 ]; then
        echo "$(stamp) run failed (exit $code); serving whatever out/ holds" >&2
    fi
fi

SERVER=
TMP=${TMPDIR:-/tmp}
LOG=$(mktemp "${TMP%/}/assist-start.XXXXXX")
cleanup() {
    if [ -n "$SERVER" ] && kill -0 "$SERVER" 2>/dev/null; then
        kill "$SERVER" 2>/dev/null || true
        wait "$SERVER" 2>/dev/null || true
    fi
}
trap cleanup EXIT
trap 'echo "$(stamp) stopped"; exit 130' INT
trap 'echo "$(stamp) stopped"; exit 143' TERM

echo "$(stamp) assist status --port $PORT (server log: $LOG)"
"$UV" run assist status --port "$PORT" >"$LOG" 2>&1 &
SERVER=$!

waited=0
until "$CURL" -fsS -o /dev/null --max-time 2 "$URL" 2>/dev/null; do
    if ! kill -0 "$SERVER" 2>/dev/null; then
        echo "$(stamp) the server exited before $URL answered; its log:" >&2
        tail -n 20 "$LOG" >&2
        exit 1
    fi
    if [ "$waited" -ge "$TIMEOUT" ]; then
        echo "$(stamp) $URL did not answer within ${TIMEOUT}s; server log tail:" >&2
        tail -n 20 "$LOG" >&2
        exit 1
    fi
    sleep 1
    waited=$((waited + 1))
done

echo "$(stamp) pages on $URL (Ctrl-C stops them)"
if [ "$OPEN_BROWSER" = yes ]; then
    "$OPEN" "$URL" || echo "$(stamp) could not open a browser; visit $URL" >&2
fi

code=0
wait "$SERVER" || code=$?
SERVER=
echo "$(stamp) server exited ($code)"
exit "$code"
