"""LiveRecall server package.

Module ownership (see RESPONSIBILITIES.md):

    model.py          FROZEN - shared record types and the revision ordering rule
    app.py            FROZEN - configuration and the dependency container
    caption_state.py  Owner A - per-segment revision state, final durability
    history.py        Owner A - bounded finals window, HISTORY/resume
    hub.py            Owner B - client registry and fan-out
    client_session.py Owner B - bounded per-client queue, writer task, overload policy
    ingest.py         Owner D - inbound parsing/validation, source handler
    metrics.py        Owner D - counters and observability

Changing anything marked FROZEN requires team agreement, because more than one
owner codes against it.
"""
