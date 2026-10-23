"""`assist` command line. Subcommands: doctor (run, brief, regime and journal come later)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import httpx

from assist import doctor


def _doctor(args: argparse.Namespace) -> int:
    today = date.fromisoformat(args.today) if args.today else date.today()
    sources = doctor.load_sources(Path(args.config), root=Path(args.root) if args.root else None)
    client = None if args.no_http else httpx.Client(trust_env=False)
    try:
        statuses = doctor.run_doctor(sources, today, http_client=client)
    finally:
        if client is not None:
            client.close()
    if args.json:
        print(json.dumps([s.to_json() for s in statuses], indent=2))
    else:
        print(doctor.format_report(statuses, today))
    return 0  # a missing, locked or stale source is reported, never a failure


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="assist", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("doctor", help="present / missing / locked / stale per source")
    d.add_argument("--config", default=str(doctor.DEFAULT_CONFIG))
    d.add_argument("--root", help="siblings root (default ../ or $ASSIST_SIBLINGS_ROOT)")
    d.add_argument("--today", help="YYYY-MM-DD to judge staleness against (default today)")
    d.add_argument("--json", action="store_true", help="machine-readable output")
    d.add_argument(
        "--no-http", action="store_true", help="skip local HTTP servers, read the stores directly"
    )
    d.set_defaults(func=_doctor)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
