from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from marketplace_pricer.config import Settings
from marketplace_pricer.db import DB


def _parse_json_arg(raw: str) -> dict:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON for --filters: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SystemExit("--filters must be a JSON object (e.g. '{\"city\":\"boston\"}')")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="marketplace-pricer")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db", help="Create/upgrade local SQLite schema")

    sub.add_parser("facebook-login", help="Open a browser to login and save Playwright storage state")

    wl = sub.add_parser("watchlist", help="Manage watchlists")
    wl_sub = wl.add_subparsers(dest="watchlist_cmd", required=True)
    wl_add = wl_sub.add_parser("add", help="Add a watchlist")
    wl_add.add_argument("--name", required=True)
    wl_add.add_argument("--source", required=True, choices=["facebook", "craigslist_email", "nextdoor"])
    wl_add.add_argument("--query", required=True)
    wl_add.add_argument("--filters", default="{}")
    wl_add.add_argument("--interval", type=int, default=300, help="Scan interval seconds")
    wl_add.add_argument("--inactive", action="store_true")

    wl_sub.add_parser("list", help="List watchlists")

    inv = sub.add_parser("inventory", help="Record buys/sells for reporting")
    inv_sub = inv.add_subparsers(dest="inventory_cmd", required=True)
    inv_add = inv_sub.add_parser("add", help="Add an inventory transaction")
    inv_add.add_argument("--kind", required=True, choices=["buy", "sell"])
    inv_add.add_argument("--amount-cents", required=True, type=int)
    inv_add.add_argument("--fees-cents", type=int, default=0)
    inv_add.add_argument("--listing-key")
    inv_add.add_argument("--notes")

    scan = sub.add_parser("scan", help="Run scanners")
    scan_sub = scan.add_subparsers(dest="scan_cmd", required=True)
    scan_sub.add_parser("once", help="Scan all due watchlists once")
    scan_run = scan_sub.add_parser("run", help="Run scanner loop")
    scan_run.add_argument("--sleep", type=int, default=10, help="Seconds between loop iterations")

    ui = sub.add_parser("ui", help="Run local mispricing dashboard")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=7331)
    ui.add_argument("--open", action="store_true", help="Open the dashboard in your browser")

    report = sub.add_parser("report", help="Reporting")
    report_sub = report.add_subparsers(dest="report_cmd", required=True)
    weekly = report_sub.add_parser("weekly", help="Weekly P&L from inventory table")
    weekly.add_argument("--weeks", type=int, default=8, help="Number of weeks to show (UTC weeks starting Monday)")

    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        from dotenv import load_dotenv
    except ModuleNotFoundError:
        pass
    else:
        load_dotenv()

    parser = build_parser()
    args = parser.parse_args(argv)

    settings = Settings()
    db = DB(Path(settings.sqlite_path))

    if args.cmd == "init-db":
        db.init_schema()
        print(f"Initialized DB at {settings.sqlite_path}")
        return 0

    if args.cmd == "watchlist":
        db.init_schema()
        if args.watchlist_cmd == "add":
            watchlist_id = db.add_watchlist(
                name=args.name,
                source=args.source,
                query=args.query,
                filters=_parse_json_arg(args.filters),
                scan_interval_seconds=args.interval,
                active=not args.inactive,
            )
            print(f"Added watchlist id={watchlist_id}")
            return 0
        if args.watchlist_cmd == "list":
            watchlists = db.list_watchlists(active_only=False)
            for w in watchlists:
                print(
                    f"{w.id}\t{'active' if w.active else 'inactive'}\t{w.source}\t{w.name}\tq={w.query}\tfilters={w.filters}"
                )
            return 0

    if args.cmd == "facebook-login":
        from marketplace_pricer.facebook_auth import run_facebook_login

        run_facebook_login(settings)
        return 0

    if args.cmd == "scan":
        db.init_schema()
        from marketplace_pricer.scanner import Scanner

        scanner = Scanner(settings=settings, db=db)
        if args.scan_cmd == "once":
            summary = scanner.scan_due_watchlists_once()
            print(
                f"[scan] watchlists={summary.watchlists_scanned} listings={summary.listings_seen} "
                f"new={summary.listings_new} alerts={summary.alerts_sent}"
            )
            return 0
        if args.scan_cmd == "run":
            scanner.run_forever(sleep_seconds=args.sleep)
            return 0

    if args.cmd == "report":
        db.init_schema()
        if args.report_cmd == "weekly":
            from marketplace_pricer.reporting import print_weekly_report

            print_weekly_report(db, weeks=int(args.weeks))
            return 0

    if args.cmd == "ui":
        db.init_schema()
        try:
            import uvicorn
        except ModuleNotFoundError as exc:
            raise SystemExit("Missing dependency: uvicorn. Install UI deps and retry.") from exc

        from marketplace_pricer.ui.app import create_app

        host = str(args.host)
        port = int(args.port)
        url = f"http://{host}:{port}"
        print(f"[ui] starting dashboard at {url}")
        if args.open:
            try:
                import webbrowser

                webbrowser.open(url)
            except Exception:
                pass

        app = create_app(settings=settings, db=db)
        uvicorn.run(app, host=host, port=port, log_level="info")
        return 0

    if args.cmd == "inventory":
        db.init_schema()
        if args.inventory_cmd == "add":
            db.record_inventory(
                kind=args.kind,
                amount_cents=args.amount_cents,
                fees_cents=args.fees_cents,
                listing_unique_key=args.listing_key,
                notes=args.notes,
            )
            print("Recorded inventory transaction")
            return 0

    print("Unknown command", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
