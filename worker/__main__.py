"""Entry point: ``python -m worker``.

Runs one stub worker against the configured database. Ctrl-C stops it, and the
job it was holding returns to the queue when its lease expires.
"""

from __future__ import annotations

import asyncio
import contextlib

from worker.runner import main

if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
