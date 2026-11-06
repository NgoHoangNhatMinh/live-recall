# Viva Prep — Team 23, LiveRecall

Friday 6 Nov 2026. **15 minutes total, and setup time counts against it.**
Questions may go to any member; the viva component is marked individually.

---

## 1. Pre-flight — do all of this BEFORE the slot starts

- [ ] Ubuntu VM booted, repo at the submitted commit, `git status` clean
- [ ] `source venv/bin/activate` done in every terminal
- [ ] `ss -ltnp | grep 8765` prints **nothing**
- [ ] Three terminals open with the commands **typed but not run**:
      1. `python solution_server.py --port 8765`
      2. `python -m http.server 8000 --directory client`
      3. `python caption_source.py --duration 600`
- [ ] Terminals 1 and 2 already running; **source started ~60 s before the
      slot** so recall and late-join have real content to show
- [ ] Browser: tab A on `http://127.0.0.1:8000` with a populated transcript;
      a second tab ready to open but **not yet opened** (that's the late-join beat)
- [ ] DevTools console open in tab A (so `HISTORY with N item(s)` is visible)
- [ ] **Rehearse the disconnect beat once.** In tab A's DevTools Console:
      `retryDelay = 8000; ws.close()` — status should read
      `disconnected - retrying in 8s`, then recover on its own. Have that line
      ready to paste; do not type it live
- [ ] Source started with a long duration (`--duration 600`) so it cannot
      expire mid-slot — if it ends you cannot restart it (see the warning in §3)
- [ ] Editor open on `liverecall/` — you may be asked to jump to a file
- [ ] `report.pdf` open in a tab, and the `t*_run0*.json` results to hand
- [ ] `python -m unittest discover -s tests -t .` run once to confirm 70 pass

If setup eats five minutes you lose a third of the slot. Arrive warm.

## 2. Run sheet

| Time | What |
|---|---|
| 0:00–0:30 | One sentence: what LiveRecall is, and that the server is already running |
| 0:30–5:00 | Demo, six beats below |
| 5:00–13:30 | Questions |
| 13:30–15:00 | Buffer — do not plan to use it |

## 3. Presentation script — timed, with speakers

Stage directions are in *italics*. Spoken lines are the ones to rehearse — say
them in your own words, but hit the underlined ideas.

---

### 0:00–0:45 — what it is, and the one design claim

*Server, HTTP server and source are already running. Tab A shows a populated
transcript.*

> "LiveRecall distributes a live caption stream to many students at once.
> Captions arrive as **revisions** — a segment is provisional while the
> recogniser is still refining it, then final. The networking problem is
> delivering that to a hundred clients while staying correct and fresh when
> some of them are slow, some disconnect, and the network degrades.
>
> One design claim shapes everything: **correctness is ranked above freshness.**
> Final caption completeness below 99 % caps the performance mark regardless of
> latency, and the spec treats unbounded state as a correctness failure. So
> every bound in our server is explicit, and every one is in a single `Config`
> class.
>
> The server is one asyncio process: one task per connection, plus a writer
> task and a bounded queue per client. Jordon will show the application first."

---

### 0:45–3:00 — live captions, revision replacement, recall

*Point at the transcript in tab A.*

> "Each caption segment is **one line**, and it's replaced in place as newer
> revisions arrive — watch segment N: `r1`, `r2`, then `r3`."

*Wait for one segment to complete. Point at the colour change.*

> "Provisional is dimmed and italic with a dashed rule; final is solid with a
> green rule. So a student can see at a glance which text is settled. Newer
> revisions **replace** — they never append a duplicate line."

*Scroll up briefly to show earlier segments are retained, then back down.*

> "Now 'What did I miss?'."

*Click 15 s, then 30 s, then 60 s. Point at the list growing each time.*

> "30 seconds is the default, with 15 and 60 available. This is served
> **entirely from local state** — the client keeps 90 seconds of finalized
> captions in memory, so there is no server round trip. That's deliberate:
> the protocol has no mid-connection history request, so the only way to answer
> this instantly is to hold it locally."

---

### 3:00–3:45 — late join

*Open the second tab.*

> "A student arriving mid-lecture. It sends `CLIENT_HELLO` with watermark
> zero-zero…"

*Point at the DevTools console: `HISTORY with N item(s)`.*

> "…and the server returns the recent window — finals only, oldest first. It
> renders that context and then continues live from the same code path."

---

### 3:45–4:45 — disconnect, reconnect, incremental recovery

*In tab A's console, paste the prepared line.*

```js
retryDelay = 8000; ws.close()
```

> "I've dropped this client's connection. The status shows it detected the loss
> and is retrying — and note the server and the lecture are still running, so
> it is genuinely missing content right now."

*Count the gap aloud, ~8 s. Then it reconnects by itself.*

> "It reconnected on its own and resumed from its latest **finalized**
> watermark — not the newest revision it happened to see. So the server sent
> only the finals it actually missed, and **nothing appears twice**, because
> recovered items go through exactly the same acceptance rules as live updates."

---

### 4:45–5:45 — the overload policy and the negative result

*Switch to the T3 metrics log / results, already open.*

> "The hard part isn't the happy path, it's a client that reads slower than
> captions are produced. Our first design triggered on **application queue
> depth** — and measurement killed it. With slow readers lagging thirteen
> seconds, peak queue depth was **one**. `await ws.send()` returns as soon as
> the frame reaches the asyncio transport, so the backlog was sitting in kernel
> and client-library buffers, invisible to us. The policy would never have
> fired.
>
> So we measure lag **directly**: each session pings its own connection. A ping
> goes into the same byte stream as the captions, so its pong can't come back
> until the client has read everything before it. RTT minus the minimum RTT is
> the queueing delay in front of that client — and subtracting the minimum
> means pure network delay doesn't look like overload. Every WebSocket client
> answers pings automatically, so this needs no protocol extension.
>
> Above 250 ms of lag we engage three mechanisms: a newer revision of a segment
> **overwrites its queued older provisional in place**, so the queue holds at
> most one frame per active segment; at most three frames may be unconfirmed,
> which is what forces frames to wait where we can still coalesce them; and we
> pace sends at 0.85 of the client's estimated read rate so its hidden receive
> queue drains. **Finals are never shed** — because resume uses a watermark, a
> dropped final leaves a hole no history can repair.
>
> It clears only after two seconds below 80 ms, so it can't flap."

*Point at the counters.*

> "In T3, `overload_engaged` is exactly **10** — matching the ten slow readers,
> with no normal client affected."

*Hand to Jihan.*

---

### 5:45–6:15 — the numbers

> "Three-run medians on Ubuntu, harness unmodified. At a hundred clients on a
> clean network: **100 % completeness, 100 % update coverage**, P95 29 ms.
>
> With ten percent slow readers, completeness is **99.34 %** — through the gate
> — and the ninety normal clients are untouched at P95 29 ms and 100 %
> freshness. Against the naive baseline at identical parameters, completeness
> went **95.13 to 99.34**, and slow-client lag fell about two thirds. The cost
> was ten milliseconds on normal-client P95, which we think is the writer tasks
> and ping probes.
>
> Duplicate and stale counts were **zero in every run**."

> "Happy to take questions."

---

### If something breaks

- **Transcript frozen / nothing arriving** → check terminal 3: the source may
  have exited. **Do not restart it** (see the traps below). Say "the generator
  has finished its run" and move to the recall and reconnect beats, which work
  from local state and history.
- **`ws is not defined` in the console** → you are in the wrong frame or an
  iframe context; pick the top frame in the console's context dropdown. Fallback:
  stop the HTTP server in terminal 2, which drops nothing — instead use
  Firefox's `File → Work Offline` if available.
- **Reconnect takes too long** → `retryDelay` doubled from an earlier attempt.
  Say so, and reload the tab to reset it, describing it as a late join.
- **Anything unrecoverable** → go to the report tables and the 70-test suite.
  You can discuss every result without a live system.

---

### ⚠️ Two things that will freeze the demo

**Restarting `caption_source.py`.** It always begins at segment 1, and the
server already holds finals for segments 1..N, so `CaptionState.apply()`
rejects every replayed segment. Verified: a second source run against a live
server delivered **0** updates to a connected client. Restarting the server
first does not help — the server accepts them but the *browser* rejects them by
the same durability rule, and the transcript stays frozen until the new source
passes the old high-water segment.

**`Ctrl-C` on the server** kills the source too, with a `ConnectionClosedOK`
traceback. That is expected: `caption_source.py` is the supplied test harness
and has no reconnect logic. If asked, say exactly that — it is not part of our
submission. But it leaves you with no source, and the only way back is a full
restart of everything *including both browser tabs*, which costs you the
remainder of the slot.

**DevTools "Offline" does not work for the disconnect beat.** Chrome's network
emulation applies to new HTTP requests, not to an already-established
WebSocket: the socket stays up and captions keep arriving. Use the console line
above.

## 4. Code location map — for "show me the code"

| Asked about | File | Line |
|---|---|---|
| Final durability check | `liverecall/caption_state.py` | 111 |
| Revision comparison | `liverecall/caption_state.py` | 121 |
| Eviction watermark rejection | `liverecall/caption_state.py` | 98 |
| Unbounded-growth backstop | `liverecall/caption_state.py` | 217 |
| `HISTORY` watermark filter | `liverecall/history.py` | 107 |
| Binary-search suffix | `liverecall/history.py` | 170 |
| Unrecoverable-gap counter | `liverecall/history.py` | 148 |
| Write path: admit → record → publish | `liverecall/ingest.py` | 221 |
| Connect path, no-`await` invariant | `liverecall/client_session.py` | 476 |
| Per-client queue (`offer`) | `liverecall/client_session.py` | 211 |
| Writer task (`run`) | `liverecall/client_session.py` | 274 |
| Lag measurement | `liverecall/client_session.py` | 398 |
| Hysteresis / mode switch | `liverecall/client_session.py` | 412 |
| Coalescing | `liverecall/client_session.py` | 447 |
| In-flight gate | `liverecall/client_session.py` | 338 |
| Fan-out | `liverecall/hub.py` | 49 |
| **All bounds** | `liverecall/app.py` | 41–75 |

## 5. The nine published questions

Lead is whoever owns it; **everyone should be able to attempt all nine.**

**1. Why can an older revision never overwrite a newer one?** *(Minh)*
One admission point, `CaptionState.apply()`, returns the update only if it
advances state and `None` otherwise — and the caller never publishes a `None`.
Three rules in priority order: a final is durable, higher revision replaces
lower, an already-held revision is rejected. The final check sits *before* the
revision comparison, so revision 99 still loses to a final revision 3.

**2. What happens when a client reconnects after 10 seconds offline?** *(Minh)*
It sends `CLIENT_HELLO` with its latest **finalized** `(segment, revision)` —
not the newest revision it saw — and `history_seconds: 60`. The server returns
finals strictly newer than that watermark and no older than the window,
oldest-first, finals only. Those items go through the client's same `accept()`
as live updates, so nothing is shown twice. `HISTORY` is queued as frame zero
before the client is registered for live updates, with no `await` between, so a
live update can neither overtake it nor slip into a gap.

**3. Where is per-client buffering implemented, and how is it bounded?** *(Xinyang)*
`client_session.py`. Each client has its own deque and its own writer task;
`offer()` is synchronous so the source task never awaits a socket. Bounded by
`queue_soft_limit` (32) where the policy starts coalescing and
`queue_hard_limit` (128) where the client is disconnected — it then reconnects
and resumes through `HISTORY`, which is cheaper than dragging a stale backlog.

**4. Why did P95/P99 increase under packet loss even though TCP is reliable?** *(Jihan)*
Because TCP recovers loss by retransmitting, and the WebSocket byte stream must
be delivered in order — so a lost segment head-of-line blocks everything behind
it. Nothing is *lost* at the application layer; it arrives *late*. That's why
P50 rose to 376 ms but P99 to 6.75 s: the tail inflates far more than the
median. T5 completeness of 97.06 % is captions still in flight when the fixed
experiment ended, not lost or stale state — duplicates and stale stayed zero.

**5. What happens when a client consumes more slowly than captions are generated?** *(Xinyang)*
Its pong latency rises above the connection's baseline. Above
`overload_lag_high` (0.25 s) it is marked overloaded; at most
`overload_inflight_frames` (3) frames stay unconfirmed, so the rest wait in our
queue where they can still be coalesced rather than in kernel buffers where
they cannot. Superseded provisionals are replaced in place. It returns to
normal only after staying below 0.08 s for 2 s.

**6. Which provisional revisions can safely be dropped, and why?** *(Xinyang)*
Any provisional revision of a segment for which a newer revision is already
queued — it is superseded and the client will never display it. **Never a
final.** Because `last_segment` is a watermark, a dropped final for segment 10
followed by a delivered 11 moves the watermark to 11, and `items_since` only
ever returns things above it, so segment 10 becomes unrecoverable.

**7. How would your behaviour change if bandwidth were halved?** *(Xinyang)*
The same mechanism engages, because the trigger is measured queueing delay, not
an assumption about the network. Provisional traffic coalesces down toward one
pending revision per active segment, so bytes go to finals and newest state.
Completeness is preserved; update coverage degrades for affected clients and
recovers when they catch up.

**8. Show the code implementing your overload policy.** *(Xinyang)*
`client_session.py` — `_lag` (398), `_update_mode` (412), `_may_send` (338),
`_compact` (447); values in `app.py` 54–75.

**9. Explain one experimental result that surprised your team.** *(anyone — use this one)*
We first keyed the policy on application queue depth. Under 10 % slow readers
lagging ~13 s, `peak_queue_depth` was **1** — because `await ws.send()` returns
once the frame reaches the asyncio transport, which buffers ~32 KB, so the
backlog was in transport and kernel buffers where we could not see it. The
policy would never have fired. We replaced the signal with ping/pong RTT above
baseline; completeness on the slow-reader test went 95.13 % → 99.34 %.

## 5b. Every number in the report, and why it has that value

### What the six columns actually measure

- **P50/P95/P99** — *caption age* = client receive time minus `source_ts`, in
  ms, over every accepted live `CAPTION_UPDATE`, **all clients pooled**.
- **Fresh** — fraction of those with age <= 500 ms.
- **Complete** — unique finals accepted or recovered per client, over
  `segments x clients`. The gated metric.
- **Coverage** — unique `(segment, revision)` from **live** rows only, over
  `segments x 3 x clients`. `HISTORY` items do not count, because it carries
  finals only.

### T1 — 20 clients, 20 s: 4.17 / 12.13 / 14.99 ms, all three at 100%

The no-stress baseline. Ages are single-digit ms because fan-out is one JSON
encode (the wire form is cached on `CaptionUpdate`) plus 20 queue appends
inside one event-loop iteration. The P50-to-P99 spread of ~11 ms is the 20th
client waiting behind the other 19 in the same burst.

*If asked why not sub-millisecond:* fan-out is serial within an iteration, and
the measurement includes the harness client's own CSV write.

### T2 — 100 clients, 40 s: 11.38 / 29.39 / 36.66 ms, all three at 100%

**The scale result.** 5x the clients for 2.7x the median, with coverage still
100.00%. Sub-linear because the per-update cost is one encode shared across all
clients; only the append is per-client. Still 100% fresh, i.e. a 17x margin
against the 500 ms threshold.

*If asked about 1000 clients:* untested. Fan-out is O(clients) per update and
would grow linearly; 1000 writer tasks is within asyncio's range but scheduling
overhead rises.

### T3 — 100 clients, 10% slow: 14.48 / 2265.89 / 8414.06 ms, 94.65 / 99.34 / 95.18

**These are pooled over two populations, which is the whole explanation.**
P50 14.48 ms is barely above T2's 11.38 — the median client is untouched. P95
and P99 are entirely the slow 10%, who sleep 500 ms per message and are
structurally seconds behind.

Both percentages derive exactly from the mix:

```
Fresh    = (20520 normal x 100%  +  1180 slow x 1.69%) / 21700 = 94.65%   ✓ reported 94.65%
Coverage = 1 - 10% x (1 - 118/228)                             = 95.18%   ✓ reported 95.18%
```

where 118 = how many of the 228 revisions a client reading one per 500 ms can
absorb in 59 s. So **neither number indicates a server defect** — they are what
the population mix arithmetically forces.

Completeness 99.34%: the missing 0.66% is the last few finals still in transit
to slow clients when the fixed 60 s run ends.

The split table is the isolation claim: normal clients at P95 28.87 ms and
100.00% fresh are statistically indistinguishable from T2's 29.39 ms.

**The instrumentation is the best evidence here.** `overload_engaged = 10`
exactly matches the 10 slow readers — zero false positives, no normal client
affected. `provisionals_coalesced = 1020`. And peak queue depth reached 9
against a soft bound of 32, which proves the **RTT trigger** did the work, not
the depth bound — depth never came close.

### T4 — 100 clients, 20% reconnect: 10.58 / 25.78 / 30.95 ms, 100 / 100 / 98.33

Ages match T2, so reconnects do not disturb steady-state latency. Completeness
100.00% with zero duplicates is the recovery path working exactly as designed.

Coverage 98.33% derives from the outage:

```
5 s outage / 0.75 s per segment = 20 revisions missed per disconnected client
Coverage = 1 - 20% x (20/228) = 98.25%     ✓ reported 98.33%
```

Those are **provisional** revisions missed during the gap, and `HISTORY`
carries finals only — so they are unrecoverable by design, not by accident.

Recovery median 4.37 ms / P95 7.97 ms, measured from completed handshake to
`HISTORY` receipt. *Be careful here:* that includes the `CLIENT_HELLO` round
trip, so the honest claim is "history construction is not the bottleneck", not
"history construction takes 4 ms".

### T5 — delay+jitter+loss: 375.82 / 1928.09 / 6750.50 ms, 67.29 / 97.06 / 58.63

P50 375.82 ms against a configured 120 ms delay, because **a caption crosses
the impaired loopback twice**: source to server, then server to client. Two
one-way delays give a 240 ms floor; jitter and retransmission take it to 376 ms.

P99 6.75 s is retransmission timeout plus head-of-line blocking: TCP must
deliver the byte stream in order, so one lost segment stalls everything behind
it. Nothing is lost at the application layer — duplicates, stale and connection
errors were all zero. It arrives *late*.

Fresh 67.29% follows directly: with P50 at 376 ms, the 500 ms threshold is only
1.33x the median, so a third of captions land beyond it with nothing broken.

Completeness 97.06% is end-of-run truncation, as the report states.

> **Coverage 58.63% is the one number the report does not explain in prose.**
> Expect to be asked. The answer: delay and jitter inflate measured RTT, and
> the policy reads RTT above baseline as lag, so it engages on clients that are
> not slow readers — merely distant ones — and coalesces their provisionals.
> The signal conflates *queueing* delay with *path* delay. Completeness still
> held at 97% because finals are never shed, so the policy degraded coverage
> rather than correctness, which is the design behaving as intended under a
> condition we did not tune for.

### Before/after, same T3 parameters

| Row | Why |
|---|---|
| Completeness 95.13 -> 99.34 (+4.21 pp) | The headline: through the 99% gate. Coalescing spends a slow client's scarce budget on finals and current state instead of obsolete provisionals |
| Slow-client P50/P95 14.77/29.18 s -> 5.55/9.36 s (-62%/-68%) | Same mechanism: what a slow client *does* receive is far fresher |
| Overall P99 25120 -> 8414 ms (-66.5%) | The pooled tail is the slow population, so it moves with them |
| Normal-client P95 18.78 -> 28.87 ms (**+10.09 ms**) | **The cost.** Per-client writer tasks plus a ping probe every 0.5 s per client. The report says "most likely" because we did not isolate it with a probing-disabled run |
| Slow-client freshness 1.69% -> 1.69% (unchanged) | Not a failure. A client reading 2 messages/s **cannot** be within 500 ms of source regardless of what we send. We made it less stale, not fresh — freshness is a hard threshold its own read rate forbids |
| Coverage 95.18% -> 95.18% (unchanged) | Same total, different cause: the baseline lost provisionals to backlog, the final design suppresses them deliberately |

### The three numbers an examiner will attack

1. **T5 coverage 58.63%** — unexplained in the report prose. Use the box above.
2. **Normal-client P95 +10.09 ms** — the only metric that got worse. Own it as
   a deliberate trade: 10 ms of normal-client tail for 4.21 points of
   completeness and a two-thirds cut in slow-client lag.
3. **Slow-client freshness unchanged** — explain the read-rate ceiling, then
   name the fix: final-first ordering within a lagging client's queue, plus the
   protocol-level acknowledgements discussed in future work.

## 6. Own these before you are caught by them

Say them first; it reads as rigour rather than being found out.

- **T5 completeness is 97.06 %, below the 99 % bar.** Captions still in flight
  at the end of a fixed-duration experiment under 120 ms delay plus 3 % loss.
  Zero duplicates, zero stale. A longer tail would recover them.
- **Normal-client P95 rose 18.78 → 28.87 ms** with the policy on. The cost of
  per-client writer tasks and ping probes. We accepted ~10 ms to gain 4.21
  percentage points of completeness and a two-thirds cut in slow-client lag.
- **Slow-client freshness is unchanged at 1.69 %.** We fixed completeness and
  staleness, not freshness, for slow readers. The next step is explicit
  final-first ordering within a lagging client's queue; not implemented.
- **T3 coverage is 95.18 %.** That *is* the coalescing working. T2 is 100.00 %,
  which shows the policy is lag-triggered and not always-on.
- **A malformed `CLIENT_HELLO` closes with 1011, not 1008.** `parse_client_hello`
  is called unguarded in `solution_server.py:62`, so a client protocol error is
  reported as a server fault with a traceback. Known; a `try`/`except` away.
- **No browser persistence.** Reload loses the watermark and local history
  together — deliberately together, since keeping one without the other would
  make the client claim finals it cannot display.

## 7. If asked to make a small change

- *"Halve the recovery window"* → `app.py:46`, `history_window_seconds`
- *"Make overload trigger sooner"* → `app.py:64`, `overload_lag_high`
- *"Track more segments"* → `app.py:41`, `state_max_tracked_segments`
- *"Support a second session"* → `caption_state.py` latches one session on first
  update; you would key `_segments`, the history window and the hub by session
- *"Always drop provisionals"* → one line in `_compact`, but say what it costs:
  Normal Update Coverage collapses, which the evaluator checks precisely to
  catch that shortcut

## 8. Last reminders

- Answer from the code, not from memory — open the file and point.
- If you do not know, say so and say who does; do not invent.
- Marks are individual. If a question lands on someone outside their area,
  attempt it anyway — "not mine" scores zero for that member.
