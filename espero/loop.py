"""One loop runner for every long-running paper (and live) loop.

A forward test runs for weeks on a laptop. Before this, any exception that
escaped a step (a FetchError after the retries, "database is locked", a pandas
surprise) ended the process, and the test stopped silently. Now a failed step
is logged with where it failed, the loop backs off and tries again, and only
Ctrl-C (or SystemExit) stops it. Each step's state changes are transactional
(see `Journal.transaction`), so retrying after a failure is safe.
"""
from __future__ import annotations

import time
import traceback
from datetime import datetime, timezone
from typing import Callable, Optional

MAX_BACKOFF_S = 900.0


def run_loop(step: Callable[[], None], interval: float, label: str = "loop",
             sleep: Callable[[float], None] = time.sleep, log: Callable[[str], None] = print,
             max_backoff: float = MAX_BACKOFF_S, max_steps: Optional[int] = None) -> int:
    """Call `step()` every `interval` seconds until interrupted.

    A step that raises is logged (type, message, innermost frame) and retried
    after `interval`, doubling per consecutive failure up to `max_backoff`.
    Returns the number of failed steps; `max_steps` exists for tests."""
    failures = streak = done = 0
    while max_steps is None or done < max_steps:
        try:
            step()
            if streak:
                log(f"{label}: recovered after {streak} failed step{'s' if streak > 1 else ''}")
            streak = 0
            wait = interval
        except Exception as exc:  # noqa: BLE001 - the whole point: one bad step is not the end
            failures += 1
            streak += 1
            wait = min(max(interval, 1.0) * 2 ** (streak - 1), max(max_backoff, interval))
            frame = traceback.extract_tb(exc.__traceback__)[-1] if exc.__traceback__ else None
            where = f" at {frame.filename.rsplit('/', 1)[-1]}:{frame.lineno}" if frame else ""
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            log(f"{stamp} UTC {label}: step failed{where}: {type(exc).__name__}: {exc}; "
                f"retrying in {wait:.0f}s ({streak} in a row)")
        done += 1
        if max_steps is not None and done >= max_steps:
            break
        sleep(wait)
    return failures
