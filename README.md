# Team 23 - LiveRecall

## Team members

- Ngo Hoang Nhat Minh / A0301185N / Owner A - revision state, final durability,
  bounded history, HISTORY/resume semantics
- Xinyang / A0281296W / Owner B - per-client queues, fan-out, overload and
  backpressure policy
- Jordon / A0281173H / Owner C - browser client: revision display, recall
  windows, reconnect and recovery
- Jihan / _(student ID)_ / Owner D - source ingest and validation, server
  observability, public experiments, report

See `RESPONSIBILITIES.md` for the detailed division of work.

## Ubuntu setup

Ubuntu is required for the network-impairment test because it uses `tc/netem`.
From a fresh Ubuntu environment:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip iproute2
```

Check that the required tools are available:

```bash
python3 --version
tc -V
```

## Install

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

The mandatory path only requires `websockets`. ASR and `ffmpeg` dependencies
are not required.

## Required server

Start the server from the repository root:

```bash
python solution_server.py --port 8765
```

The required WebSocket endpoint is `ws://127.0.0.1:8765`.

## Browser client

With the server running, serve the browser files from a second terminal:

```bash
python -m http.server 8000 --directory client
```

Open `http://127.0.0.1:8000` in a browser. The client:

- renders one line per caption segment and replaces it in place as newer
  revisions arrive, so a segment never appears as duplicate lines;
- distinguishes provisional captions (dimmed, italic, dashed rule) from final
  ones (solid, green rule), with a legend below the transcript;
- keeps 90 s of finalized captions locally and answers "What did I miss?" from
  that local state, defaulting to 30 s with 15/30/60 s options;
- reconnects automatically with exponential backoff and shows the connection
  state;
- resumes using its latest **finalized** `(segment, revision)` watermark, and
  merges the returned `HISTORY` through the same acceptance rules as live
  updates, so a recovered final is never displayed twice.

## Unit tests

70 tests using stdlib `unittest`, so they add no dependency beyond
`requirements.txt`. Run from the repository root:

```bash
python -m unittest discover -s tests -t .
```

| File | Tests | Covers |
|---|---|---|
| `tests/test_caption_state.py`      | 18 | Revision invariants, final durability, eviction bounds |
| `tests/test_history.py`            | 24 | Watermark filtering, time/count bounds, binary-search fast path |
| `tests/test_ingest_validation.py`  | 15 | Field validation, malformed and unknown input |
| `tests/test_ingest_sessions.py`    |  7 | Session fallback and mismatch handling |
| `tests/test_client_session.py`     |  6 | Coalescing, finals never shed, hard limit, lag hysteresis |

## Public deterministic tests

Run each test with three independent server runs. The `--runs 3` option
restarts the server for every run; use the generated results with
`analyse_results.py` and report the median.

T1 - Basic correctness:

```bash
python run_demo.py --clients 20 --duration 20 --runs 3 --output-stem t1
```

T2 - Public scale:

```bash
python run_demo.py --clients 100 --duration 40 --runs 3 --output-stem t2
```

T3 - Slow readers:

```bash
python run_demo.py --clients 100 --duration 60 --runs 3 \
  --slow-percent 10 --slow-ms 500 --output-stem t3
```

Optional memory observation during T3:

```bash
python monitor_server.py --match solution_server.py --duration 60 --output t3_memory.csv
```

T4 - Reconnect:

```bash
python run_demo.py --clients 100 --duration 60 --runs 3 \
  --disconnect-percent 20 --disconnect-at 15 --disconnect-seconds 5 \
  --output-stem t4
```

T5 - Network impairment (Ubuntu only):

```bash
sudo ./network_profiles/delay_loss.sh lo
python run_demo.py --clients 100 --duration 40 --runs 3 --output-stem t5
sudo ./network_profiles/reset.sh lo
```

Run the submission check before submitting:

```bash
python submission_check.py
python submission_check.py --final
```

## Mandatory deterministic application demo

Use three terminals:

1. Start the server:

   ```bash
   python solution_server.py --port 8765
   ```

2. Serve the browser client:

   ```bash
   python -m http.server 8000 --directory client
   ```

3. Generate deterministic captions for a long enough demo:

   ```bash
   python caption_source.py --duration 120
   ```

Open `http://127.0.0.1:8000` in at least two browser tabs/windows. The
application demonstrates visually distinct provisional and final captions,
in-place replacement of older revisions of the same segment, 15/30/60-second
recall with a 30-second default served from local state, and automatic
reconnect with incremental recovery and no duplicate final captions. Open
another tab while the source is running to show late-join history.

**Before any measured run, check the port is free:**

```bash
ss -ltnp | grep 8765        # must print nothing
```

`run_demo.py` defaults to port 8765. If a demo server is already listening
there, run_demo's own server loses the bind and exits, but its readiness probe
is a plain TCP connect and succeeds against the existing process — so the run
silently measures a server it does not control. A `0.00%` Normal Update
Coverage row is the signature of this. Alternatively give test runs their own
port with `--port 8766`.

## Design notes

Server logic lives in `liverecall/`, one module per owner; `solution_server.py`
is wiring only. See `RESPONSIBILITIES.md` for the division of work and the
agreed bounds.

- **Revision/deduplication state:** implemented in
  `liverecall/caption_state.py`. A final revision is durable, a higher revision
  replaces a lower one, and a repeated revision is rejected. Rejected updates
  are never published, so they cannot reach history or a client queue. Live
  per-segment state is bounded by an eviction ceiling whose watermark keeps
  evicted segments rejected.
- **Bounded server history:** implemented in `liverecall/history.py`. A rolling
  window of finalized captions bounded both by age (90 s) and by item count
  (1500), so a bursty source cannot inflate it. The count bound is what makes it
  bounded rather than merely time-limited.
- **Reconnect/late-join recovery:** implemented. `HISTORY` returns finals
  strictly newer than the client's `(last_segment, last_revision)` watermark and
  no older than the requested `history_seconds`, ordered oldest to newest. A
  client offline for longer than the retained window has missed finals that no
  bounded history can return; that case is counted as
  `history_unrecoverable_gap` rather than hidden.
- **Per-client buffering:** implemented in `liverecall/client_session.py`. Each
  client has its own bounded queue and writer task, so the source task never
  awaits a socket and one slow receiver cannot stall the broadcast path.
- **Overload/backpressure policy:** implemented. Lag is measured as WebSocket
  ping/pong round-trip time above each connection's observed baseline, because
  application queue depth turned out not to be observable: `await ws.send()`
  returns once a frame reaches the asyncio transport, which buffers ~32 KB, so a
  slow client's backlog accumulates in transport and kernel buffers. A client is
  treated as overloaded above `overload_lag_high` (0.25 s) and returns to normal
  only after staying below `overload_lag_low` (0.08 s) for
  `overload_clear_hold` (2 s), which stops the policy oscillating. While
  overloaded, at most `overload_inflight_frames` (3) frames may be unconfirmed,
  so the rest wait in our queue where they can still be coalesced. Coalescing is
  semantic: a newer provisional revision replaces a queued older revision of the
  same segment in place, bounding provisional backlog by the number of active
  segments rather than by the revision rate. **Finals are never shed** — because
  `last_segment` is a watermark, a dropped final leaves a gap no bounded history
  can repair. All bounds live in `Config` in `liverecall/app.py`.
- **Observability:** `liverecall/metrics.py` emits counters printed every 5 s
  (disable with `--quiet-metrics`), including `overload_engaged` /
  `overload_cleared`, `provisionals_coalesced`, `provisionals_dropped`,
  `peak_queue_depth`, `history_items` and `history_unrecoverable_gap`. These are
  the evidence that the overload policy engages because of measured lag and
  stands down afterwards, rather than running unconditionally.

## Optional ASR bonus

Not attempted. Keep any ASR or `ffmpeg` dependencies separate from the
mandatory deterministic server path.
