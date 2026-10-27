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

function numericClientId() {
  const key = "liverecall-client-id";
  let value = sessionStorage.getItem(key);
  if (!value) {
    value = String(Math.floor(100000 + Math.random() * 900000));
    sessionStorage.setItem(key, value);
  }
  return Number(value);
}

function appendNaively(msg) {
  const row = document.createElement("div");
  row.className = "naive-line";
  const state = msg.final ? "FINAL" : "PROVISIONAL";
  row.textContent = `[${state}] segment ${msg.segment} rev ${msg.revision}: ${msg.text}`;
  liveEl.appendChild(row);
  liveEl.scrollTop = liveEl.scrollHeight;
}

function appendProperly(msg) {
  const row = document.createElement("div");
  row.className = "proper-line";
  const state = msg.final ? "FINAL" : "PROVISIONAL";

  if (state == "FINAL") {
    var isEdited = false;
    // Check if current message segment is created yet
    for (const child of liveEl.children) {
      const line = `[PROVISIONAL] segment ${msg.segment} rev `;
      var text = child.textContent;
      // If message in same segment exists, replace message
      if (text.includes(line)) {
        child.textContent = `[${state}] segment ${msg.segment} rev ${msg.revision}: ${msg.text}`;
        isEdited = true;
      }
    }

    if (!isEdited) {
      row.textContent = `[${state}] segment ${msg.segment} rev ${msg.revision}: ${msg.text}`;
      liveEl.appendChild(row);
    }
  } else {
    var isCreated = false;
    // Check if current message segment is created yet
    for (const child of liveEl.children) {
      const line = `[PROVISIONAL] segment ${msg.segment} rev `;
      var text = child.textContent;
      // If message in same segment exists, replace message
      if (text.includes(line)) {
        var idx = text.indexOf(line) + length(line);
        var num = text.charAt(idx);
        // If current message revision is newer than displayed message 
        if (Number(num) < Number(msg.revision)) {
          child.textContent = `[${state}] segment ${msg.segment} rev ${msg.revision}: ${msg.text}`;
        }
        isCreated = true;
      }
    }

    // If current message segment not created yet
    if (!isCreated) {
      const new_row = document.createElement("div");
      new_row.className = "proper-line";
      row.textContent = `[${state}] segment ${msg.segment} rev ${msg.revision}: ${msg.text}`;
      liveEl.appendChild(new_row);
    }
  }
  liveEl.scrollTop = liveEl.scrollHeight;
}

function connect() {
  statusEl.textContent = "connecting";
  ws = new WebSocket(WS_URL);

  ws.addEventListener("open", () => {
    statusEl.textContent = "connected";
    ws.send(JSON.stringify({
      type: "CLIENT_HELLO",
      client_id: numericClientId(),
      session: "L1",
      last_segment: 0,       // TODO: resume latest finalized state
      last_revision: 0,
      history_seconds: 30
    }));
  });

  ws.addEventListener("message", (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === "CAPTION_UPDATE") {
      appendProperly(msg);
    } else if (msg.type === "HISTORY") {
      console.log(`HISTORY with ${msg.items?.length ?? 0} item(s)`, msg);
      // TODO: merge history without stale/duplicate final captions.
    }
  });

  ws.addEventListener("close", () => {
    statusEl.textContent = "disconnected";
    // TODO: automatic reconnect after a short delay, using finalized resume state.
  });

  ws.addEventListener("error", () => {
    statusEl.textContent = "connection error";
  });
}

for (const button of document.querySelectorAll("button[data-seconds]")) {
  button.addEventListener("click", () => {
    const seconds = Number(button.dataset.seconds);
    recallEl.textContent = `TODO: show finalized captions from the previous ${seconds} seconds using local state.`;
  });
}

connect();
