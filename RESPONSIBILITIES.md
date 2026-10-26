# Team 23 - LiveRecall: Division of Work

Working document for the team. `CONTRIBUTIONS.md` is the graded submission
artifact; keep it in sync with this file as roles settle.

Deadline **4 Nov 2026**. Demo and viva **6 Nov 2026**, 15-minute slot, all four
members attend.

---

## 1. Roles at a glance

| Role | Name | Mandate |
|---|---|---|
| **A** | _(assign)_ | Make the server's notion of "what is true" correct and bounded |
| **B** | _(assign)_ | Keep every client as fresh as its own capacity allows, without one client hurting another |
| **C** | _(assign)_ | A thing that behaves like a usable classroom tool |
| **D** | _(assign)_ | Nothing untrusted gets in unvalidated; nothing gets claimed without evidence |

Section 7 has the detail. Where the marks sit:

| Assignment component | Marks | Owner |
|---|---|---:|
| A. Usable application and deterministic demo | 15 | C |
| B. Protocol correctness and robustness | 15 | A, with B |
| C. Public experiments and analysis | 10 | D |
| D. Hidden performance evaluation | 30 | see below |
| E. Code / repo / report / reproducibility | 10 | D |
| F. Individual technical viva | 20 | everyone |

| Hidden-performance component | Marks | Owner |
|---|---|---:|
| Correctness and invariants | 8 | A |
| Normal update coverage and normal freshness | 4 | B |
| Delay/loss tail freshness | 2 | D |
| Challenge 1: slow-reader semantic backpressure | 6 | B |
| Challenge 2: constrained-bandwidth semantic delivery | 6 | B |
| Reconnect and catch-up recovery | 4 | A (incremental) + B (convergence) |

Two notes on why the split is drawn here.

**A is the critical path.** Final Caption Completeness below 99% caps the whole
30-mark hidden-performance section at 15, and below 95% caps it at 5. No amount
of work by B rescues a broken A. A should also land the `HISTORY` path early,
because C cannot test recovery or late join until it exists.

**D is not a documentation role.** The viva is individually assessed at 20
marks, so every member needs code they can defend. D owns the inbound
validation boundary and the metrics layer, which is exactly the code that
produces the report's claims and answers "show me that your policy engaged".

---

## 2. File ownership

One owner per file. Nobody edits another owner's file without asking; that is
the whole reason the server was split up.

```
solution_server.py            wiring only, ~110 lines, keep it that way
liverecall/model.py           FROZEN  records + the revision ordering rule
liverecall/app.py             FROZEN  config bounds + dependency container
liverecall/caption_state.py   A       per-segment revision state, final durability
liverecall/history.py         A       bounded finals window, HISTORY/resume
liverecall/hub.py             B       client registry, fan-out
liverecall/client_session.py  B       bounded queue, writer task, overload policy
liverecall/ingest.py          D       parsing/validation, source handler
liverecall/metrics.py         D       counters and observability
client/                       C       browser client
tests/                        shared  add alongside your own module
```

Changing anything marked **FROZEN** needs team agreement, because more than one
owner codes against it.

---

## 3. Day-one decisions (already made - do not relitigate silently)

These are written into the code so they cannot drift. Each one is a likely viva
question, so everybody should be able to explain all five.

**1. Resume semantics: `last_segment` is a watermark.**
`HISTORY` returns only finals strictly newer than `(last_segment, last_revision)`.
Implemented once, in `model.after_watermark()`.
*Consequence:* a client holding segment 12 but missing segment 10 can never
recover 10, because its watermark hides the gap. **The overload policy must
therefore never drop a final** - that is what makes the watermark safe.

**2. Protocol: mandatory interface only, no extensions.**
Zero evaluator-compatibility risk, and it unblocks C immediately because the
wire format is fully specified in the assignment.

**3. Bounds, all in `Config` in `liverecall/app.py`.**

| Bound | Value | Why |
|---|---|---|
| `history_window_seconds` | 90 | Exceeds the 60 s recall requirement with slack |
| `history_max_items` | 1500 | Clock-independent cap; a bursty hidden source could put far more than 120 segments in 90 s |
| `state_max_tracked_segments` | 512 | Live per-segment state would otherwise grow for the whole lecture |
| `queue_soft_limit` | 32 | Where the overload policy engages |
| `queue_hard_limit` | 128 | Where a client is dropped to reconnect and resume cleanly |

Tune the numbers, but tune them *there* - don't scatter new ones.

**4. Write-path ordering: admit → record → publish.**
In `ingest.handle_source`. Recording a final into history *before* publishing it
means a client reconnecting in that same instant finds it instead of missing it.

**5. Connect-path ordering: build HISTORY and register with the hub with no
`await` between them.**
In `client_session.serve_client`, with the reasoning in a comment there.
Register first and a live update can overtake HISTORY, producing a duplicate
final. Await in between and an update published in the gap is lost forever.
Both calls are synchronous, so the event loop cannot interleave.

---

## 4. Current state of the skeleton

The module split is in place and measured. `submission_check.py` passes.

| Test (reduced scale) | Completeness | Coverage | Normal P95 | Slow P95 |
|---|---|---|---|---|
| 20 clients / 20 s | 100.00% | 100.00% | 4.37 ms | — |
| 40 clients / 30 s, 20% reconnect | 100.00% | 96.30% | 4.59 ms | — |
| 40 clients / 30 s, 10% slow 500 ms | **95.28%** | 95.37% | 4.85 ms | 13644 ms |

Read that bottom row carefully, because it defines B's job.

*Slow-client isolation already works.* Normal clients stayed at P95 = 4.85 ms
and 100% freshness while slow clients were 13 seconds behind. The per-client
queue plus one writer task per client bought that, and it is a large
improvement on the baseline's shared `asyncio.gather`.

*Completeness is below the 99% gate, and the arithmetic says it is fixable.* A
client sleeping 500 ms per message can absorb only ~60 messages in a 30-second
run. The source produced 36 finals and 72 provisionals. The skeleton spent that
scarce budget in arrival order, so slow clients got 76 of 144 expected finals.
Spend the same 60-message budget on finals and newest-state first and all 36
finals fit comfortably. **The overload policy is not a latency optimisation -
it is what gets completeness through the gate.**

*And the policy currently never fires.* `peak_queue_depth` stayed at 1 across
that whole run. `await ws.send()` returns once the frame reaches the asyncio
transport, which buffers 32 KB by default, so a slow client's backlog lives in
the transport and kernel buffers where the application deque cannot see it.
Queue depth is not yet a usable lag signal. Three verified ways out are written
up in the header of `liverecall/client_session.py`; B should start there.

---

## 5. Blockers, in order

Nothing in section 6 starts until these are done.

1. **Ubuntu VM for D, ideally for everyone.** The assignment says outright that
   WSL is not the reference grading environment and to use a full Ubuntu VM if
   `tc/netem` differs. T5 and the before/after comparison are measured under
   netem on `lo`. `multipass launch --name liverecall --cpus 2 --memory 4G --disk 15G`,
   then confirm `tc -V`.
2. **Baseline numbers captured** from commit `4c7e5c9` (the naive broadcaster),
   for the mandatory before/after comparison. Same parameters as the final run.
3. ~~Repo layout and frozen interfaces~~ — done, section 2.
4. ~~The five semantic decisions~~ — done, section 3.
5. **Names into this file and `CONTRIBUTIONS.md`.** `README.md` currently lists
   one of four members with "responsibility" as a placeholder. Named
   responsibilities are graded evidence and feed the individual viva.
6. **Git workflow agreed**: branch per member, small PRs, each PR reviewed by a
   different owner. Git history is explicit supporting evidence for the
   contribution statement.

---

## 6. Schedule

### Week 1 - end to end and correct

- **A** — harden `caption_state` and `history`; unit tests for the three
  invariants (final durability, higher revision wins, duplicate rejection) and
  for `items_since` at the watermark boundary.
- **B** — pick the lag signal (see `client_session.py` header) and prove it
  moves under load before writing any policy. A trigger you cannot observe
  cannot be tuned.
- **C** — revision replacement keyed by segment, provisional vs final styling,
  reconnect with backoff, connection status. A 20-line fake server returning
  canned `HISTORY` items unblocks you before A lands.
- **D** — finish validation edge cases, get T1/T2 running on the VM, wire
  `monitor_server.py` into the T3 procedure.

### Week 2 - the graded mechanisms

- **A** — reconnect/dedup edge cases: simultaneous reconnect burst, a client
  resuming with a watermark older than the window, late join mid-segment.
- **B** — the real policy: per-segment coalescing, finals never shed, lag
  trigger with hysteresis, newest-first flush on recovery. Target the 95.28% →
  ≥99% completeness jump and report `overload_engaged`/`overload_cleared` so
  the report can show it switching on and off rather than running always-on.
- **C** — 60 s local finalized history, 15/30/60 s recall with 30 s default
  served from local state, `HISTORY` merge with no duplicate finals.
- **D** — T3/T4 at full scale with memory observation; start the before/after
  table.

### Week 3 - evidence

- Tuning driven by D's measurements, not by intuition.
- T5 under `delay_loss.sh`, plus `bandwidth_2mbit.sh` for the
  constrained-bandwidth challenge.
- All of T1–T5 at `--runs 3`, medians reported.
- `report.pdf` (4–5 pages), 5–7 minute demo video, `submission_check.py --final`.
- **Viva dry run: each member answers the assignment's example questions about
  someone else's component.** If only B can explain the overload policy, three
  people lose marks on a 20-mark individually-assessed component.

---

## 7. Owner responsibilities in detail

### Owner A - revision state and recovery

**Mandate:** make the server's notion of "what is true" correct and bounded.

**Files:** `liverecall/caption_state.py`, `liverecall/history.py`

#### The work

**Three invariants in `CaptionState.apply()`.** Final durability (once a segment
is final, nothing replaces it), higher-revision-wins within a segment,
duplicate rejection. `apply()` returns `None` for anything that does not advance
state, so stale and duplicate revisions never reach history or any client queue.
This single return value is what keeps the `duplicates` and `stale` columns at
zero across every public test.

**Bounded live state.** Per-segment state would otherwise grow for the whole
lecture. Eviction in `_prune()` only removes finalised segments below the lowest
active one, and `_pruned_through` keeps rejecting them afterwards so eviction
cannot resurrect stale revisions. There is a known hole marked `TODO(A)`: a
source that leaves a low segment active forever blocks eviction entirely. The
public and instructor sources complete a segment before starting the next, so it
cannot bite - but be able to say that out loud, because "what stops this
growing?" is the obvious viva follow-up.

**The history window, bounded twice.** By time (90 s) and by count (1500). The
count bound is the one that earns marks: a bursty hidden source could put far
more than 120 segments inside a 90-second window, and "bounded in wall-clock
terms" would then still mean "grows with the source rate".

**`items_since()` - two filters, both required.** Strictly newer than the
client's watermark (4.2: HISTORY must not include finals the client already
reported), and no older than `history_seconds` (requirement 5: recover recent
context, do not replay the lecture). Ordered oldest to newest. Finals only - the
load client flags a non-final HISTORY item as `invalid_history_nonfinal`.

**`build_history_message()` splices cached wire forms** rather than re-encoding.
Under a simultaneous-reconnect burst that is one JSON encode per client instead
of one per item per client.

#### Edge cases A owns

- A client reconnecting with a watermark older than the window. Offline 70 s
  against a 90 s window is fine; offline 120 s leaves an unrecoverable gap. The
  public harness disconnects for 5 s, but the hidden evaluator varies disconnect
  duration. A decides the policy and documents it.
- Late join (`last_segment=0`) gets the whole window, capped at the clamped
  `history_seconds`.
- Simultaneous reconnect burst: 20 clients each building a HISTORY in the same
  event-loop tick. Shows up as `recovery_p95`. Measure it.

#### Definition of done

`final_completeness_pct` >= 99% (aim 100) on T1-T4, `duplicates` = 0, `stale` =
0, `invalid_history_nonfinal` = 0. Server memory flat over a 10-minute run. Can
state the three invariants without looking.

Metrics owned: `updates_accepted`, `updates_rejected_stale`,
`updates_rejected_duplicate`, `history_items`, `history_items_sent`,
`state_tracked_segments`. Harness signals: `final_completeness_pct`,
`duplicates`, `stale`, `recovery_p50/p95`.

#### Tests to write

Unit tests, no sockets needed - both classes are pure. Final-then-higher-revision
rejected; equal revision is duplicate; lower is stale; eviction does not
resurrect. For history: exact match at the watermark is *excluded*, the
`history_seconds` cutoff boundary, the count bound, and ordering.
`HistoryWindow` takes an injectable `clock` precisely so these run without
sleeping.

#### Viva questions A must answer

"Why can an older revision never overwrite a newer one?" / "What exactly happens
when a client reconnects after 10 seconds offline?" / "What stops your history
growing?"

---

### Owner B - fan-out and overload policy

**Mandate:** keep every client as fresh as its own capacity allows, without
letting any client hurt another or hold unbounded state.

**Files:** `liverecall/hub.py`, `liverecall/client_session.py`

#### The work, in order

**1. Find a lag signal that moves.** This comes first and it is not optional.
Measured on the skeleton: `peak_queue_depth` stayed at 1 while slow clients ran
13 s behind, because `await ws.send()` returns once the frame reaches the asyncio
transport, which buffers 32 KB before applying backpressure. The backlog lives
in transport and kernel buffers. Three verified options are in the module
header. Prove the signal tracks real lag *before* writing any policy - a trigger
you cannot observe cannot be tuned.

**2. Coalescing structure.** Pending provisionals in a dict keyed by segment, so
a newer revision of an active segment *replaces* the queued older one in place
rather than queueing behind it. That bounds provisional backlog by the number of
active segments instead of by the revision rate, which is the real win. Finals
go in a separate FIFO that is never shed.

**3. Hysteresis, and reporting it.** Engage above the soft limit, clear below a
lower mark, and emit `overload_engaged` / `overload_cleared`. This is what
protects the 4-mark coverage component: the evaluator checks Normal Update
Coverage specifically to catch a policy that sheds unconditionally. The report
needs to show the policy toggling, not just running.

**4. Rapid convergence.** On clearing, prefer newest-first or skip-if-superseded
on dequeue, so a recovering client lands on current state instead of draining
the stall it just left.

#### Why this is a correctness job, not an optimisation

On the measured T3 run, completeness was 95.28% - under the gate. The arithmetic:
a client sleeping 500 ms per message absorbs ~60 messages in 30 s, the source
emitted 36 finals and 72 provisionals, and the skeleton spent that budget in
arrival order, delivering 76 of 144 expected finals. Spend the same 60 messages
on finals and newest-state first and all 36 fit with room over. The overload
policy is what gets completeness through the gate.

#### The hard constraint from A

**Never drop a final.** Because `last_segment` is a watermark, a dropped final
for segment 10 followed by a delivered segment 11 moves the client's watermark to
11, and HISTORY will only ever send items above it. Segment 10 is permanently
lost and completeness permanently reduced. Shedding is provisional-only, always.

#### Also B's

- The `serve_client` ordering invariant lives in B's file (decision 5 above). B
  owns not breaking it.
- The `queue_hard_limit` question: is disconnect-and-resume better than holding
  the backlog? It is bounded and recoverable but costs a round trip and a HISTORY
  build. Measure both; do not inherit the current guess.
- Whether Challenge 2 (constrained bandwidth, `bandwidth_2mbit.sh`) needs a
  different mechanism from Challenge 1, or whether one lag-triggered policy
  serves both. Cheaper to test than to argue.

#### Definition of done

Completeness >= 99% on T3 and under `bandwidth_2mbit.sh`. Normal-client P95
unaffected by slow readers. Normal Update Coverage back at ~100% when nothing is
overloaded. Metrics show the policy engaging *and clearing*.

Metrics owned: `frames_sent`, `provisionals_coalesced`, `provisionals_dropped`,
`overload_engaged`/`overload_cleared`, `peak_queue_depth`,
`clients_disconnected_overflow`, `clients_connected`. Harness signals:
`normal_clients.p95`, `slow_clients.fresh_pct`, `normal_update_coverage_pct`.

#### Tests to write

B needs a fake websocket whose `send()` awaits a controllable event - that is how
you drive the policy deterministically without real sockets or real time. This is
the least obvious and most valuable piece of test infrastructure in the project.

#### Viva questions B must answer

"What happens when a client consumes messages more slowly than they are
generated?" / "Which provisional revisions can safely be dropped, and why?" /
"Where is per-client buffering implemented, and how is it bounded?" / "How would
your behaviour change if bandwidth were cut in half?" / "Show the code
implementing your overload policy."

---

### Owner C - browser client

**Mandate:** a thing that behaves like a usable classroom tool, not a
technically connected WebSocket demo. That wording is from the grading rubric's
top-mark column.

**Files:** `client/`

#### Requirement by requirement

| Req | What C builds |
|---|---|
| 1 | Continuous caption display; provisional and final visually distinguishable |
| 2 | Newer revision replaces older in place - no duplicate lines |
| 3 | >=60 s rolling local finals history; "What did I miss?" defaults to 30 s, offers 15/30/60 s, **served from local state** - a server request only for what was genuinely missed |
| 4 | Automatic reconnect with backoff, connection state visible to the user |
| 5 | Incremental recovery - send the real watermark in `CLIENT_HELLO`, not `0` |
| 6 | Late join: recent context, then continue live |
| 7 | No duplicate finals after reconnect - HISTORY merge dedupes against local state |

#### The data model is the whole job

A `Map<segment, {revision, final, source_ts, text}>` plus a derived finals list
for recall plus a watermark. Using rendered `textContent` as the model cannot
reach requirements 3 and 5-7 - you cannot build a 60-second recall window or a
dedupe check on string-scanning the DOM.

#### Subtleties C must get right

**The watermark is finalized state, not latest-seen.** `PROTOCOL_EXAMPLES.md` is
explicit: `last_segment`/`last_revision` describe the latest *finalized* state
the client holds, not the newest provisional it happened to see. Sending a
provisional revision here would ask the server to skip a final the client does
not have.

**Persistence consistency.** If the watermark survives a page reload
(sessionStorage) but local history does not, recall silently breaks - the client
claims to hold finals it can no longer display. Persist both or neither.

**Local pruning floor.** Pruning local history at exactly 60 s makes the 60 s
recall view lose its oldest entries to timing jitter. Keep ~90 s, matching the
server window.

**Defensive merge.** The server guarantees HISTORY arrives before live updates,
but merge defensively anyway - do not depend on an invariant implemented in
someone else's file.

**Autoscroll versus reading.** Autoscrolling on every update fights a user who
scrolled up to read the recall panel. Small thing; it is exactly the difference
the 15-mark rubric is describing.

#### Also C's

The section-6 demonstration checklist and the content of the 5-7 minute demo
video - distinguishable provisional/final, in-place replacement, 30 s default
recall with 15/30/60 options, disconnect to auto-reconnect to recovery with no
duplicate finals, late join.

#### Definition of done

Every bullet of assignment section 6 demonstrable in two browser tabs.

#### Viva questions C must answer

"Why is `last_segment` the finalized state rather than the latest revision you
saw?" / "What happens on your client when the connection drops for 10 seconds?"
/ "Where does the 30-second recall data come from, and when do you have to ask
the server?"

---

### Owner D - input boundary, observability, experiments, report

**Mandate:** nothing untrusted gets in unvalidated, and nothing gets claimed
without evidence.

**Files:** `liverecall/ingest.py`, `liverecall/metrics.py`, the experiment
procedure, `report.pdf`, `README.md`

#### The server-side half

**The validation boundary.** All untrusted input enters here, and everything
downstream trusts the result and never re-checks a field. Unknown JSON fields
ignored, unknown message types ignored, malformed JSON counted rather than fatal.
Section 4.1 says the instructor source may add fields such as a test-phase label
- crashing on one is a zero for hidden performance. `history_seconds` is clamped
to 60 once, here, so no caller repeats it.

**The write-path ordering** in `handle_source`: admit, record, publish.
Recording a final into history *before* publishing means a client reconnecting in
that same instant finds it rather than missing it. D owns the file, so D owns
explaining it.

**Metrics as the evidence base.** The load-client CSV shows what clients
received; it cannot show *why*. These counters are how the report substantiates
any claim about backpressure, and they are the answer to "show me that your
policy actually engaged". Keep them cheap - they run on the fan-out path.

#### The experiments half

- Ubuntu VM with working `tc/netem`, and the T1-T5 procedure at `--runs 3` with
  medians.
- `monitor_server.py` during T3, which is how the bounded-memory claim gets
  evidence instead of assertion.
- **The mandatory before/after comparison**: baseline at commit `4c7e5c9` versus
  final, identical parameters, quantified, with the trade-off explained. The
  rubric wants engineering evidence, not only final numbers.
- `bandwidth_2mbit.sh` runs as the evidence for Challenge 2.
- **The T5 explanation**, which is a 2-mark hidden component *and* a listed viva
  question: why P95/P99 rise under packet loss even though WebSocket/TCP is
  reliable. Answer: retransmission and head-of-line blocking - application
  messages are not lost, they are late.
- `report.pdf`, 4-5 pages: architecture and protocol; revision/recovery
  semantics; backpressure policy; public experiments; before/after; P50/P95/P99
  plus freshness plus completeness; failures and trade-offs; limitations; future
  work.
- Repository hygiene: `README.md` reproducibility, `requirements.txt` accuracy,
  `submission_check.py --final`, `AI_USAGE.md`, `CONTRIBUTIONS.md`, and the
  gitignored-harness decision in section 9.

#### Definition of done

`python run_demo.py ...` reproduces every number in the report from a clean clone
on the VM. One before/after comparison quantified with the trade-off explained.
Every report claim traceable to a CSV row or a metrics line.

#### Viva questions D must answer

"Why did P95/P99 increase under packet loss even though WebSocket/TCP is
reliable?" / "Explain one experimental result that surprised your team." / "Show
me where unknown fields from the source are handled."

---

## 8. Handoffs and shared obligations

**Frozen, needs team agreement to change:** `liverecall/model.py` and
`liverecall/app.py`. Three owners code against them.

**A to B, the load-bearing contract:** B never sheds a final, because A's
watermark cannot repair the resulting hole. If only one cross-module rule
survives into the viva, make it this one.

**A to C:** the HISTORY shape and the watermark semantics.

**D to B:** the lag metrics B tunes against. B cannot tune what D does not
expose.

**Two ordering invariants, three owners.** The write path lives in D's file, the
connect path in B's file, and both exist because of A's semantics. All three need
to be able to explain both.

**Everyone:** the viva is individually assessed at 20 marks and questions go to
any member. The week-3 dry run where each person answers on someone else's
component is the thing that converts four specialists into four people who can
each defend the system.

---

## 9. Known open questions

- Is dropping a client at `queue_hard_limit` better than holding its backlog?
  Reconnect-and-resume is bounded and recoverable, but it costs a round trip and
  a `HISTORY` build. **B measures both** before trusting the current choice.
- Should the constrained-bandwidth policy differ from the slow-reader policy, or
  is one lag-triggered mechanism enough for both hidden challenges? Cheaper to
  find out with `bandwidth_2mbit.sh` than to argue about.
- The harness files are currently gitignored, so a fresh clone cannot run
  `run_demo.py`. Defensible since the instructor supplies them, but section E is
  graded on reproducing without guesswork — **D decides and says so in
  `README.md` either way.**
