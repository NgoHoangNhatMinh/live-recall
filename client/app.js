/*
 * Working but deliberately naive LiveRecall browser starter.
 *
 * Provided mechanical behavior:
 *   - opens a WebSocket
 *   - sends CLIENT_HELLO
 *   - visibly appends every received CAPTION_UPDATE
 *   - displays whether an update is provisional/final
 *
 * Graded TODOs:
 *   - replace revisions rather than appending duplicates
 *   - maintain >=60 s of finalized local state
 *   - implement 30 s default recall + 15/30/60 s views
 *   - automatic reconnect + correct resume state
 *   - HISTORY merge/deduplication
 *   - usable final UI
 */

const WS_URL = "ws://127.0.0.1:8765";
const statusEl = document.getElementById("status");
const liveEl = document.getElementById("live");
const recallEl = document.getElementById("recall");

let ws;
let retryDelay = 1000;
const MAX_DELAY = 30000;

const recallHistory = [];
const MAX_HISTORY_DURATION = 70 * 1000;
var history_duration = 30 * 1000;

var lastCaption = {
  segment: 0,
  revision: 0,
}

function numericClientId() {
  const key = "liverecall-client-id";
  let value = sessionStorage.getItem(key);
  if (!value) {
    value = String(Math.floor(100000 + Math.random() * 900000));
    sessionStorage.setItem(key, value);
  }
  return Number(value);
}

function appendProperly(msg) {
  const row = document.createElement("div");
  row.className = "proper-line";

  if (liveEl.children.length <= 0) {
    row.dataset.segment = msg.segment;
    row.dataset.revision = msg.revision;
    row.textContent = String(msg.text);
    row.dataset.source_ts = msg.source_ts;
    liveEl.appendChild(row);
  }

  // Check if current message segment is created yet
  for (const child of liveEl.children) {
    const old_segment = child.dataset.segment;
    const old_revision = child.dataset.revision;
    // If message in same segment exists, replace message
    if ((msg.segment == old_segment && msg.revision > old_revision) || msg.segment > old_segment) {
      child.dataset.segment = msg.segment;
      child.dataset.revision = msg.revision;
      child.textContent = String(msg.text);
      child.dataset.source_ts = msg.source_ts;
    }
  }

  if (msg.final) {
    record(msg.text);
  }

  liveEl.scrollTop = liveEl.scrollHeight;
}

function record(value) {
  recallHistory.push({
    timestamp: Date.now(),
    text: value
  });

  removeExpired();
}

function removeExpired() {
  const cutoff = Date.now() - MAX_HISTORY_DURATION;

  while (recallHistory.length > 0 && recallHistory[0].timestamp < cutoff) {
    recallHistory.shift();
  }
}

function renderHistory() {
  const duration = Number(history_duration);
  const cutoff = Date.now() - duration;

  const filtered = recallHistory.filter(
      item => item.timestamp >= cutoff
  );

  const divs = filtered.map(item => {
      const div = document.createElement("div");
      div.textContent = item.text;
      return div;
  });

  recallEl.replaceChildren(...divs);
}

setInterval(() => {
  removeExpired();
  renderHistory();
}, 1000);

function connect() {
  statusEl.textContent = "connecting";
  ws = new WebSocket(WS_URL);

  ws.addEventListener("open", () => {
    statusEl.textContent = "connected";
    ws.send(JSON.stringify({
      type: "CLIENT_HELLO",
      client_id: numericClientId(),
      session: "L1",
      last_segment: lastCaption.segment,
      last_revision: lastCaption.revision,
      history_seconds: history_duration / 1000
    }));
  });

  ws.addEventListener("message", (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === "CAPTION_UPDATE") {
      lastCaption.segment = msg.segment;
      lastCaption.revision = msg.revision;
      appendProperly(msg);
    } else if (msg.type === "HISTORY") {
      console.log(`HISTORY with ${msg.items?.length ?? 0} item(s)`, msg);
      for (const item of msg.items) {
        lastCaption.segment = item.segment;
        lastCaption.revision = item.revision;
        recallHistory.push({
          timestamp: Date.now(),
          text: String(item.text)
        });
      }
      renderHistory();
    }
  });

  ws.addEventListener("close", () => {
    statusEl.textContent = "disconnected";
    setTimeout(connect, retryDelay);
    retryDelay = Math.min(retryDelay * 2, MAX_DELAY);
  });

  ws.addEventListener("error", () => {
    statusEl.textContent = "connection error";
  });
}

for (const button of document.querySelectorAll("button[data-seconds]")) {
  button.addEventListener("click", () => {
    const seconds = Number(button.dataset.seconds) * 1000;
    history_duration = seconds;
    renderHistory();
  });
}

connect();
