"""Entry point for the 1-second Nifty / Bank Nifty scalping stream worker."""

from __future__ import annotations

import asyncio
import logging

from trading_shared.strategies.scalping_desk.stream_runner import run_scalping_stream_forever

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")


def main() -> None:
    asyncio.run(run_scalping_stream_forever())


if __name__ == "__main__":
    main()
