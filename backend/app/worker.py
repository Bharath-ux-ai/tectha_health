"""Background reminder worker: `python -m app.worker` (runs forever) or `python -m app.worker --once`."""
import argparse
import logging
import signal
import time

from app.config import settings
from app.db import SessionLocal
from app.services import engine

log = logging.getLogger("tectha.worker")
_stop = False


def _handle(signum, frame):  # noqa: ARG001
    global _stop
    _stop = True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="run a single pass and exit")
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)
    log.info("Reminder worker started (interval %ss)", settings.WORKER_INTERVAL_SECONDS)
    while not _stop:
        try:
            with SessionLocal() as db:
                stats = engine.run_once(db)
            if stats.get("processed") or stats.get("missed_marked"):
                log.info("Pass complete: %s", stats)
        except Exception:
            log.exception("Reminder pass failed; will retry next interval")
        if args.once:
            break
        for _ in range(settings.WORKER_INTERVAL_SECONDS):
            if _stop:
                break
            time.sleep(1)
    log.info("Reminder worker stopped")


if __name__ == "__main__":
    main()
