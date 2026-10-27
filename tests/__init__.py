"""Test package. Logging is silenced here: the suite deliberately triggers
retries, stale caches and broken symbols, and the warnings those produce are
the code working, not the suite failing. A test that needs to inspect a log
line uses `self.assertLogs`, which re-enables capture for its own block."""
import logging

logging.disable(logging.CRITICAL)
