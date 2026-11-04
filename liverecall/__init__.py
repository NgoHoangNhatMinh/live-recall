"""LiveRecall server package.

Module ownership (see RESPONSIBILITIES.md):

    model.py          FROZEN - shared record types and the revision ordering rule
    app.py            FROZEN - configuration and the dependency container
    caption_state.py  Ngo Hoang Nhat Minh - per-segment revision state, final durability
    history.py        Ngo Hoang Nhat Minh - bounded finals window, HISTORY/resume
    hub.py            Xinyang - client registry and fan-out
    client_session.py Xinyang - bounded per-client queue, writer task, overload policy
    ingest.py         Jihan - inbound parsing/validation, source handler
    metrics.py        Jihan - counters and observability

Changing anything marked FROZEN requires team agreement, because more than one
owner codes against it.
"""
