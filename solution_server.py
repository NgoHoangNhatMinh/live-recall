#!/usr/bin/env python3
"""
CS3103 Assignment 4 - LiveRecall server entry point.

Required evaluator command:
    python solution_server.py --port 8765

This file is wiring only, and it stays that way. Every piece of real logic
lives in a module under liverecall/ with exactly one owner, so that four people
can work at once without colliding in the file the evaluator starts:

    liverecall/model.py          FROZEN - records + revision ordering rule
    liverecall/app.py            FROZEN - config bounds + dependency container
    liverecall/caption_state.py  A      - revision state, final durability
    liverecall/history.py        A      - bounded finals window, HISTORY/resume
    liverecall/hub.py            B      - client registry and fan-out
    liverecall/client_session.py B      - bounded queues, writer task, overload
    liverecall/ingest.py         D      - parsing/validation, source handler
    liverecall/metrics.py        D      - counters and observability

See RESPONSIBILITIES.md for the division of work and the day-one decisions.

Add nothing to this file except wiring.
"""

from __future__ import annotations

import argparse
import asyncio
import json

import websockets

from liverecall.app import App, Config
from liverecall.client_session import serve_client
from liverecall.ingest import handle_source, parse_client_hello


async def read_hello(ws, timeout: float) -> dict | None:
    """Read the first frame of a connection, which must be a hello."""
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        hello = json.loads(raw)
    except (asyncio.TimeoutError, json.JSONDecodeError, TypeError):
        return None
    return hello if isinstance(hello, dict) else None


def make_handler(app: App):
    """Build the per-connection handler bound to this server's App."""

    async def handler(ws) -> None:
        hello = await read_hello(ws, app.config.hello_timeout)
        if hello is None:
            await ws.close(code=1008, reason="Expected a valid hello message")
            return

        msg_type = hello.get("type")
        if msg_type == "SOURCE_HELLO":
            await handle_source(ws, hello, app)
        elif msg_type == "CLIENT_HELLO":
            await serve_client(ws, parse_client_hello(hello, app.config.session), app)
        else:
            await ws.close(code=1008, reason="Expected SOURCE_HELLO or CLIENT_HELLO")

    return handler


async def log_metrics_periodically(app: App) -> None:
    """Print a metrics line at a fixed interval, for experiment runs."""
    interval = app.config.metrics_interval_seconds
    if interval <= 0:
        return
    while True:
        await asyncio.sleep(interval)
        print(app.metrics.log_line(), flush=True)


async def main_async(port: int, app: App) -> None:
    async with websockets.serve(
        make_handler(app),
        "0.0.0.0",
        port,
        max_size=2**20,
        ping_interval=20,
        ping_timeout=20,
    ):
        print(f"LiveRecall listening on ws://0.0.0.0:{port}", flush=True)
        logger = asyncio.create_task(log_metrics_periodically(app))
        try:
            await asyncio.Future()
        finally:
            logger.cancel()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--quiet-metrics",
        action="store_true",
        help="Disable the periodic metrics log line",
    )
    args = parser.parse_args()

    config = Config(metrics_interval_seconds=0.0 if args.quiet_metrics else 5.0)
    try:
        asyncio.run(main_async(args.port, App(config)))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
