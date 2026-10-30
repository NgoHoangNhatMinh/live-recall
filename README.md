# Team 23 - LiveRecall

## Team members

- Ngo Hoang Nhat Minh / A0301185N / Owner A - revision state, final durability,
  bounded history, HISTORY/resume semantics
- Xinyang / _(student ID)_ / Owner B - per-client queues, fan-out, overload and
  backpressure policy
- Jordon / _(student ID)_ / Owner C - browser client: revision display, recall
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

Open `http://127.0.0.1:8000` in a browser. The starter client connects to the
server using session `L1`, sends `CLIENT_HELLO`, and displays received
caption updates. The supplied browser is intentionally naive: it appends each
revision as a separate line and its recall/reconnect behavior remains TODO.

## Unit tests

Server-side invariants are covered by stdlib `unittest`, so no extra
dependency is needed. Run from the repository root:

```bash
python -m unittest discover -s tests -t .
```

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
completed application should demonstrate visually distinct provisional and
final captions, replacement of older revisions for the same
`(session, segment)`, 15/30/60-second recall with a 30-second default, and
automatic reconnect/recovery without duplicate final captions. Open another
tab while the source is running to demonstrate late-join history.

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
- **Per-client buffering:** in place. Each client has its own bounded queue and
  writer task, so the source task never awaits a socket and one slow receiver
  cannot stall the broadcast path.
- **Overload/backpressure policy:** in progress. The current shedding rule is a
  placeholder that drops the oldest provisional frames and never a final.
  Semantic coalescing, a lag trigger based on measured backlog, and rapid
  convergence after overload are still to be built.

## Optional ASR bonus

Not attempted. Keep any ASR or `ffmpeg` dependencies separate from the
mandatory deterministic server path.
