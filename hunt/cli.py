"""Command line: `python -m hunt <command>`."""
from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time


def _setup_logging(verbose: bool, log_file: str | None = None) -> None:
    if log_file:
        # pythonw.exe (the windowless scheduled task) has no console: send all output,
        # including tracebacks and the run summary, to the log file instead
        f = open(log_file, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = f
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)


def cmd_init(args) -> None:
    from hunt.bootstrap import init_db
    init_db()
    print("Database migrated; profile, master resume, answer library and seed boards loaded.")


def cmd_serve(args) -> None:
    import uvicorn
    from hunt.config import get_settings
    s = get_settings()
    uvicorn.run("hunt.api.app:get_app", factory=True, host=args.host or s.host, port=args.port or s.port, log_level="info")


def cmd_run(args) -> None:
    from hunt.bootstrap import init_db
    from hunt.pipeline.runner import RunAlreadyActive, run_pipeline
    from hunt.pipeline.scheduler import is_scheduled_hour
    if args.scheduled and not is_scheduled_hour():
        print("Not the scheduled hour in America/Chicago; exiting (external cron covers both DST offsets).")
        return
    init_db()
    try:
        run_id = run_pipeline(trigger="schedule" if args.scheduled else "cli", dry_run=args.dry_run,
                              only=args.stages.split(",") if args.stages else None, max_minutes=args.max_minutes)
    except RunAlreadyActive as e:
        print(f"Skipped: {e}")
        sys.exit(0)
    _print_run(run_id)


def _print_run(run_id: int) -> None:
    from hunt.db import session_scope
    from hunt.models import PipelineRun
    with session_scope() as s:
        r = s.get(PipelineRun, run_id)
        print(f"\nRun #{r.id}: {r.status} ({'dry run' if r.dry_run else r.trigger})")
        for st in r.stages:
            res = st.checkpoint or {}
            brief = {k: v for k, v in res.items() if not isinstance(v, (dict, list))}
            print(f"  {st.stage:18} {st.status:10} {json.dumps(brief)[:300]}")
            if st.error:
                print(f"  {'':18} ERROR {st.error[:300]}")


def cmd_keygen(args) -> None:
    from hunt.security import generate_key
    print(generate_key())


def cmd_dry_run(args) -> None:
    """End-to-end demonstration without contacting any real employer:
    real discovery, verification, eligibility, scoring and resume tailoring, plus
    real browser submissions against the local mock ATS only."""
    import os
    os.environ["HUNT_ENABLE_MOCK_ATS"] = "true"
    port = args.mock_port
    os.environ["HUNT_MOCK_ATS_BASE"] = f"http://127.0.0.1:{port}/mock-ats"
    from hunt import config
    config.get_settings.cache_clear()
    import uvicorn
    from hunt.bootstrap import init_db
    from hunt.mock_ats.app import standalone_app
    from hunt.pipeline.runner import run_pipeline
    from hunt.testdata import ensure_mock_jobs

    server = uvicorn.Server(uvicorn.Config(standalone_app(), host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)
    init_db()
    ensure_mock_jobs(f"http://127.0.0.1:{port}/mock-ats")
    run_id = run_pipeline(trigger="dry-run", dry_run=True, max_minutes=args.max_minutes)
    server.should_exit = True
    _print_run(run_id)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="hunt", description="Internship Hunt")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--log-file", help="append all output to this file (used by the windowless scheduled task)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="migrate database and load profile/resume/seeds").set_defaults(fn=cmd_init)
    sp = sub.add_parser("serve", help="run the dashboard + API + daily scheduler")
    sp.add_argument("--host")
    sp.add_argument("--port", type=int)
    sp.set_defaults(fn=cmd_serve)
    rp = sub.add_parser("run", help="run the pipeline once")
    rp.add_argument("--dry-run", action="store_true", help="never contact real employers")
    rp.add_argument("--stages", help="comma-separated subset, e.g. discovery,verification")
    rp.add_argument("--scheduled", action="store_true", help="only run during the configured local hour (for external cron)")
    rp.add_argument("--max-minutes", type=int, default=150)
    rp.set_defaults(fn=cmd_run)
    dp = sub.add_parser("dry-run", help="full end-to-end demo against the local mock ATS")
    dp.add_argument("--mock-port", type=int, default=8765)
    dp.add_argument("--max-minutes", type=int, default=40)
    dp.set_defaults(fn=cmd_dry_run)
    sub.add_parser("keygen", help="generate an encryption key for HUNT_SECRET_KEY").set_defaults(fn=cmd_keygen)
    args = p.parse_args(argv)
    _setup_logging(args.verbose, args.log_file)
    try:
        args.fn(args)
    except Exception:  # noqa: BLE001
        logging.getLogger("hunt").exception("command failed")
        raise


if __name__ == "__main__":
    main()
