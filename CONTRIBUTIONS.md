# Team Contributions

Team 23 - LiveRecall. See `RESPONSIBILITIES.md` for the detailed division of
work and the per-owner definition of done.

| Member | Main responsibilities | Experiments/report sections | Agreed contribution % |
|---|---|---|---:|
| Ngo Hoang Nhat Minh (Owner A) | Revision state and final durability; bounded recovery history; `HISTORY` / reconnect-resume semantics (`liverecall/caption_state.py`, `liverecall/history.py`) | Revision and recovery semantics; final-completeness and duplicate/stale results | |
| Xinyang (Owner B) | Per-client bounded queues and writer tasks; fan-out; semantic coalescing and overload policy (`liverecall/hub.py`, `liverecall/client_session.py`) | Backpressure and overload policy; slow-reader and constrained-bandwidth experiments | |
| Jordon (Owner C) | Browser client: revision replacement, 15/30/60 s recall from local state, automatic reconnect, `HISTORY` merge (`client/`) | Application architecture and UI; deterministic demo and demo video | |
| Jihan (Owner D) | Source ingest and validation; server observability and metrics (`liverecall/ingest.py`, `liverecall/metrics.py`) | Architecture and protocol overview; public tests T1-T5; before/after comparison; limitations and future work; report assembly | |

Total contribution should be 100%.

## Shared and integration work

- `liverecall/model.py` and `liverecall/app.py` are frozen shared interfaces -
  the record types, the revision ordering rule, and all configured bounds. Agreed
  jointly; changes require team agreement.
- Two ordering invariants span owners: the write path (admit, record, publish) in
  `liverecall/ingest.py`, and the connect path (build `HISTORY` and register with
  the hub with no `await` between them) in `liverecall/client_session.py`. Both
  exist because of Owner A's semantics and are implemented in other owners'
  files.
- Each pull request is reviewed by an owner other than its author.
- All four members take part in the viva dry run, answering on a component they
  did not write.

Git history is supporting evidence, not a substitute for this statement.
