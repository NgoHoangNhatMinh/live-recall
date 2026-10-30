"""Owner B: deterministic tests for the per-client queue and overload policy.

No real sockets. `FakeWS.send()` blocks until the test opens its gate, and
`FakeWS.ping()` returns a future the test resolves by hand, so lag and
backpressure are driven exactly rather than by sleeping on a real network.
"""

from __future__ import annotations

import asyncio
import functools
import json
from dataclasses import replace

from liverecall.app import Config
from liverecall.client_session import ClientSession
from liverecall.metrics import Metrics
from liverecall.model import CaptionUpdate


class FakeWS:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.gate = asyncio.Event()
        self.gate.set()
        self.pings: list[asyncio.Future] = []
        self.closed_with: int | None = None

    async def send(self, wire: str) -> None:
        await self.gate.wait()
        self.sent.append(json.loads(wire))

    async def ping(self) -> asyncio.Future:
        fut = asyncio.get_running_loop().create_future()
        self.pings.append(fut)
        return fut

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed_with = code

    def answer_pings(self) -> None:
        for fut in self.pings:
            if not fut.done():
                fut.set_result(0.0)


def upd(segment: int, revision: int, final: bool = False) -> CaptionUpdate:
    return CaptionUpdate.create(
        session="L1", segment=segment, revision=revision, final=final,
        source_ts=0.0, text=f"s{segment}r{revision}",
    )


def make(config: Config | None = None):
    ws = FakeWS()
    metrics = Metrics()
    session = ClientSession(
        ws=ws, client_id=1, config=config or Config(), metrics=metrics,
        initial_frames=('{"type":"HISTORY","items":[]}',),
    )
    return ws, session, metrics


def keys(ws: FakeWS) -> list[tuple]:
    return [(m["segment"], m["revision"], m["final"]) for m in ws.sent if m["type"] == "CAPTION_UPDATE"]


def run_async(test):
    """Run an async test on a fresh loop; avoids a pytest-asyncio dependency."""
    @functools.wraps(test)
    def wrapper():
        asyncio.run(test())
    return wrapper


async def settle() -> None:
    for _ in range(20):
        await asyncio.sleep(0)


@run_async
async def test_normal_mode_delivers_every_revision_in_order():
    ws, session, metrics = make()
    task = asyncio.create_task(session.run())
    for u in (upd(1, 1), upd(1, 2), upd(1, 3, True), upd(2, 1)):
        session.offer(u)
    await settle()
    assert ws.sent[0]["type"] == "HISTORY"
    assert keys(ws) == [(1, 1, False), (1, 2, False), (1, 3, True), (2, 1, False)]
    assert not session.overloaded
    assert metrics.get("provisionals_coalesced") == 0
    session.close()
    await task


@run_async
async def test_blocked_socket_engages_and_compacts_but_keeps_every_final():
    ws, session, metrics = make(replace(Config(), queue_soft_limit=4))
    ws.gate.clear()  # socket stops draining
    task = asyncio.create_task(session.run())
    await settle()
    for seg in range(1, 4):
        for rev in range(1, 4):
            session.offer(upd(seg, rev, final=(rev == 3)))
    assert session.overloaded
    assert metrics.get("overload_engaged") == 1
    ws.gate.set()
    ws.answer_pings()
    for _ in range(10):
        await settle()
        ws.answer_pings()
    got = keys(ws)
    # every final survives, in order, and nothing older follows a newer revision
    assert [k for k in got if k[2]] == [(1, 3, True), (2, 3, True), (3, 3, True)]
    for seg in (1, 2, 3):
        revs = [r for s, r, _ in got if s == seg]
        assert revs == sorted(revs)
    assert len(got) < 9
    session.close()
    await task


@run_async
async def test_overloaded_offer_coalesces_in_place():
    ws, session, metrics = make(replace(Config(), queue_soft_limit=1))
    ws.gate.clear()
    task = asyncio.create_task(session.run())
    await settle()
    session.offer(upd(5, 1))
    session.offer(upd(5, 2))  # depth 2 > soft 1: engage
    assert session.overloaded
    depth = session.depth
    session.offer(upd(5, 3))
    session.offer(upd(5, 4, True))
    assert session.depth == depth  # overwritten in place, not appended
    assert metrics.get("provisionals_coalesced") == 2
    ws.gate.set()
    for _ in range(10):
        await settle()
        ws.answer_pings()
    assert keys(ws)[-1] == (5, 4, True)
    session.close()
    await task


@run_async
async def test_final_is_never_coalesced_away():
    ws, session, _ = make(replace(Config(), queue_soft_limit=1))
    ws.gate.clear()
    task = asyncio.create_task(session.run())
    await settle()
    session.offer(upd(1, 3, True))
    session.offer(upd(2, 1))
    session.offer(upd(2, 2))
    ws.gate.set()
    for _ in range(10):
        await settle()
        ws.answer_pings()
    assert (1, 3, True) in keys(ws)
    session.close()
    await task


@run_async
async def test_hard_limit_disconnects_instead_of_growing():
    ws, session, metrics = make(replace(Config(), queue_soft_limit=2, queue_hard_limit=5))
    ws.gate.clear()
    task = asyncio.create_task(session.run())
    await settle()
    for seg in range(1, 10):
        session.offer(upd(seg, 1, True))  # finals cannot be shed
    await settle()
    assert metrics.get("clients_disconnected_overflow") == 1
    assert ws.closed_with == 1013
    assert session.depth == 0
    ws.gate.set()
    await task


@run_async
async def test_unanswered_ping_engages_and_answered_pings_clear():
    cfg = replace(Config(), overload_lag_high=0.05, overload_lag_low=0.02,
                  overload_clear_hold=0.1, probe_interval=0.02)
    ws, session, metrics = make(cfg)
    task = asyncio.create_task(session.run())
    await settle()
    ws.answer_pings()  # baseline RTT
    await asyncio.sleep(0.03)
    session.offer(upd(1, 1))
    await settle()
    assert ws.pings and not ws.pings[-1].done()  # client stops answering
    await asyncio.sleep(0.08)
    session.offer(upd(1, 2))
    await settle()
    assert session.overloaded
    # client catches up: pongs return promptly from now on
    for _ in range(30):
        ws.answer_pings()
        await asyncio.sleep(0.01)
    assert not session.overloaded
    assert metrics.get("overload_cleared") == 1
    session.close()
    await task
