/*
 * LiveRecall browser client.
 *
 * State, not the DOM, is the source of truth. `segments` holds the newest
 * known revision of every segment; the transcript and the recall panel are
 * both rendered from it. Live CAPTION_UPDATEs and recovered HISTORY items go
 * through the same accept() function, which is what keeps a recovered final
 * from ever being displayed twice (requirement 7).
 *
 * accept() applies the same three rules as the server's caption_state.py, in
 * the same priority order:
 *   1. a final is durable - nothing replaces it, not even a higher revision
 *   2. within a segment, a higher revision replaces a lower one
 *   3. a revision already held is ignored
 */

const WS_URL = "ws://127.0.0.1:8765";
const statusEl = document.getElementById("status");
const liveEl = document.getElementById("live");
const recallEl = document.getElementById("recall");

let ws;
let retryDelay = 1000;
const MAX_DELAY = 30000;
const INITIAL_DELAY = 1000;

// segment -> { revision, final, source_ts, text, row }
const segments = new Map();
// segment -> { ts, text } for finalized captions only. Keyed by segment, so a
// final recovered through HISTORY cannot be stored twice.
const finals = new Map();

// Latest FINALIZED state we hold. This is what CLIENT_HELLO must report - not
// the newest revision we happened to see. See PROTOCOL_EXAMPLES.md section 2.
let lastFinal = { segment: 0, revision: 0 };

// Local retention. Kept above 60 s so the 60 s recall view never loses its
// oldest entries to timing jitter; the server's window is 90 s.
const RETENTION_MS = 90 * 1000;
// Recovery is always requested at the protocol maximum. The recall buttons
// only change what we *display* from local state - a short display window
// must never shrink how much we can recover after an outage.
const RECOVERY_SECONDS = 60;
// Bound the transcript so a long lecture cannot grow the DOM forever.
const MAX_ROWS = 250;

let displayWindowMs = 30 * 1000; // "What did I miss?" defaults to 30 s

function numericClientId() {
  const key = "liverecall-client-id";
  let value = sessionStorage.getItem(key);
  if (!value) {
    value = String(Math.floor(100000 + Math.random() * 900000));
    sessionStorage.setItem(key, value);
  }
  return Number(value);
}

/* ---------------------------------------------------------------- state --- */

function accept(msg) {
  const segment = Number(msg.segment);
  const revision = Number(msg.revision);
  const isFinal = Boolean(msg.final);

  const current = segments.get(segment);
  if (current) {
    // Rule 1 before rule 2: a final outranks a higher revision.
    if (current.final) return false;
    if (revision <= current.revision) return false;
  }

  let row = current ? current.row : null;
  if (!row) {
    row = document.createElement("div");
    liveEl.appendChild(row);
  }

  segments.set(segment, {
    revision, final: isFinal, source_ts: Number(msg.source_ts),
    text: String(msg.text), row,
  });

  row.className = isFinal ? "caption final" : "caption provisional";
  row.dataset.segment = segment;
  row.dataset.revision = revision;
  row.textContent = `${segment}·r${revision}  ${msg.text}`;

  if (isFinal) {
    // source_ts is seconds since the epoch; the recall window is about when a
    // caption was spoken, not when we happened to receive it, so a batch of
    // finals recovered after a reconnect keeps its original spacing.
    finals.set(segment, { ts: Number(msg.source_ts) * 1000, text: String(msg.text) });
    if (segment > lastFinal.segment ||
        (segment === lastFinal.segment && revision > lastFinal.revision)) {
      lastFinal = { segment, revision };
    }
  }

  return true;
}

function prune() {
  const cutoff = Date.now() - RETENTION_MS;
  for (const [segment, item] of finals) {
    if (item.ts < cutoff) finals.delete(segment);
  }
  while (liveEl.children.length > MAX_ROWS) {
    // firstElementChild, not firstChild: whitespace in the markup would
    // otherwise hand us a text node with no dataset.
    const row = liveEl.firstElementChild;
    if (!row) break;
    segments.delete(Number(row.dataset.segment));
    row.remove();
  }
}

/* --------------------------------------------------------------- render --- */

function renderRecall() {
  const cutoff = Date.now() - displayWindowMs;
  const items = [...finals.entries()]
    .filter(([, item]) => item.ts >= cutoff)
    .sort((a, b) => a[0] - b[0]);

  if (items.length === 0) {
    const empty = document.createElement("div");
    empty.className = "recall-empty";
    empty.textContent = `No finalized captions in the last ${displayWindowMs / 1000} s.`;
    recallEl.replaceChildren(empty);
    return;
  }

  recallEl.replaceChildren(...items.map(([segment, item]) => {
    const div = document.createElement("div");
    div.className = "recall-line";
    div.textContent = `${segment}. ${item.text}`;
    return div;
  }));
}

function nearBottom() {
  return liveEl.scrollHeight - liveEl.scrollTop - liveEl.clientHeight < 40;
}

function setStatus(text, cls) {
  statusEl.textContent = text;
  statusEl.className = cls;
}

setInterval(() => {
  prune();
  renderRecall();
}, 1000);

/* ------------------------------------------------------------ transport --- */

function connect() {
  setStatus("connecting", "connecting");
  ws = new WebSocket(WS_URL);

  ws.addEventListener("open", () => {
    setStatus("connected", "connected");
    retryDelay = INITIAL_DELAY; // reset backoff after a successful connect
    ws.send(JSON.stringify({
      type: "CLIENT_HELLO",
      client_id: numericClientId(),
      session: "L1",
      last_segment: lastFinal.segment,
      last_revision: lastFinal.revision,
      history_seconds: RECOVERY_SECONDS,
    }));
  });

  ws.addEventListener("message", (event) => {
    const msg = JSON.parse(event.data);
    const stick = nearBottom();

    if (msg.type === "CAPTION_UPDATE") {
      if (accept(msg)) renderRecall();
    } else if (msg.type === "HISTORY") {
      const items = msg.items || [];
      console.log(`HISTORY with ${items.length} item(s)`, msg);
      let changed = false;
      // Same path as live updates: accept() rejects anything we already hold,
      // so a recovered final is never shown twice.
      for (const item of items) {
        if (accept(item)) changed = true;
      }
      if (changed) renderRecall();
    }

    if (stick) liveEl.scrollTop = liveEl.scrollHeight;
  });

  ws.addEventListener("close", () => {
    setStatus(`disconnected - retrying in ${retryDelay / 1000}s`, "disconnected");
    setTimeout(connect, retryDelay);
    retryDelay = Math.min(retryDelay * 2, MAX_DELAY);
  });

  ws.addEventListener("error", () => {
    setStatus("connection error", "disconnected");
  });
}

/* ------------------------------------------------------------------ ui --- */

for (const button of document.querySelectorAll("button[data-seconds]")) {
  button.addEventListener("click", () => {
    displayWindowMs = Number(button.dataset.seconds) * 1000;
    for (const other of document.querySelectorAll("button[data-seconds]")) {
      other.classList.toggle("active", other === button);
    }
    renderRecall();
  });
}

// Mark the 30 s default as active on load.
const defaultButton = document.querySelector('button[data-seconds="30"]');
if (defaultButton) defaultButton.classList.add("active");

renderRecall();
connect();
