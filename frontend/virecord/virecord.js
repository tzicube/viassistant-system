/* ======================
 * UTILS
 * ====================== */
const $ = (id) => document.getElementById(id);
const escapeHtml = (s) =>
  String(s).replace(/[&<>"']/g, (m) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[m]));

// DEBUG: bắt lỗi runtime để khỏi WS tự rớt mà mình không biết
window.addEventListener("error", (e) => {
  console.error("[UI ERROR]", e?.message || e, e?.error);
});
window.addEventListener("unhandledrejection", (e) => {
  console.error("[UI PROMISE REJECT]", e?.reason || e);
});

/* ======================
 * CONFIG & STATE
 * ====================== */
const LANGS = {
  vi: { label: "Vietnamese", flag: "🇻🇳" },
  zh: { label: "Chinese", flag: "🇹🇼" },
  en: { label: "English", flag: "🇺🇸" },
};

let sourceLang = "zh";
let targetLang = "vi";

let topics = [];
let activeTitleId = null;
let activeTitleName = null;

// history + live (Cách A)
let srcHistory = "";
let tgtHistory = "";
let srcLive = ""; // live draft (replace)
let tgtLive = ""; // live translation (stream for current committed segment)

// WS / Recording
let ws = null;
let isRecording = false;
let pendingStop = false;
let stopTimer = null;
let reconnectTimer = null;
let allowReconnect = true;

// audio
let audioCtx = null;
let micStream = null;
let processor = null;
let pcmQueue = [];
let sendTimer = null;

/* ======================
 * UI
 * ====================== */
function updateLangUI() {
  $("srcLabel").textContent = LANGS[sourceLang].label;
  $("srcFlag").textContent = LANGS[sourceLang].flag;
  $("srcTitle").textContent = LANGS[sourceLang].label;

  $("tgtLabel").textContent = LANGS[targetLang].label;
  $("tgtFlag").textContent = LANGS[targetLang].flag;
  $("tgtTitle").textContent = LANGS[targetLang].label;

  updateLiveBadges();
}

function setStatus(text) {
  $("statusBadge").textContent = text;
  updateLiveBadges();
}

function updateLiveBadges() {
  const srcTitleEl = $("srcTitle");
  const tgtTitleEl = $("tgtTitle");

  srcTitleEl.textContent = LANGS[sourceLang].label;
  tgtTitleEl.textContent = LANGS[targetLang].label;

  const needLive = isRecording || pendingStop;

  if (needLive) {
    const badge = document.createElement("span");
    badge.textContent = "LIVE";
    badge.style.marginLeft = "10px";
    badge.style.fontSize = "11px";
    badge.style.padding = "2px 8px";
    badge.style.borderRadius = "999px";
    badge.style.background = "#111827";
    badge.style.color = "#fff";
    badge.style.verticalAlign = "middle";
    srcTitleEl.appendChild(badge);

    const badge2 = badge.cloneNode(true);
    tgtTitleEl.appendChild(badge2);
  }
}

function renderSource() {
  const text = (srcHistory ? srcHistory + "\n" : "") + (srcLive || "");
  $("srcText").textContent = text.trim() ? text : "—";
}

function renderTarget() {
  const text = (tgtHistory ? tgtHistory + "\n" : "") + (tgtLive || "");
  $("tgtText").textContent = text.trim() ? text : "—";
}

function appendHistoryLine(cur, line) {
  const s = (line || "").toString().trim();
  if (!s) return cur || "";
  return (cur ? cur + "\n" : "") + s;
}

/* ======================
 * SIDEBAR
 * ====================== */
const sidebar = $("sidebar");
const overlay = $("overlay");
const toggleMenu = () => {
  sidebar.classList.toggle("show");
  overlay.classList.toggle("show");
};
$("btnMenu").addEventListener("click", toggleMenu);
overlay.addEventListener("click", toggleMenu);

/* ======================
 * API & WS URL
 * ====================== */
const apiBase = () => ($("baseUrl").value || "").trim().replace(/\/+$/, "");
const wsUrl = () => {
  const base = apiBase();
  if (base.startsWith("https://")) return "wss://" + base.slice(8) + "/ws/virecord/";
  if (base.startsWith("http://")) return "ws://" + base.slice(7) + "/ws/virecord/";
  return "ws://127.0.0.1:8000/ws/virecord/";
};

const endpoints = {
  newTopic: () => apiBase() + "/api/new_topic",
  history: () => apiBase() + "/api/record_history",
  detail: (id) => apiBase() + "/api/record_detail?title_id=" + encodeURIComponent(id),
};

/* ======================
 * TOPICS UI
 * ====================== */
function renderTopics() {
  const list = $("topicList");
  list.innerHTML = "";
  if (!topics.length) {
    list.innerHTML = `<div style="padding:10px; color:#9ca3af;">No history yet.</div>`;
    return;
  }

  topics.forEach((t) => {
    const el = document.createElement("div");
    el.className = `topic-item ${String(t.title_id) === String(activeTitleId) ? "active" : ""}`;
    el.innerHTML =
      `<span>${escapeHtml(t.title_name)}</span> ` +
      `<span style="font-size:10px; opacity:0.5;">#${t.title_id}</span>`;

    el.onclick = async () => {
      activeTitleId = t.title_id;
      activeTitleName = t.title_name;
      $("topicBadge").textContent = "Topic: " + activeTitleName;

      renderTopics();
      sidebar.classList.remove("show");
      overlay.classList.remove("show");

      await loadDetail(activeTitleId);
    };
    list.appendChild(el);
  });
}

async function loadHistory() {
  try {
    setStatus("Loading...");
    const r = await fetch(endpoints.history());
    const data = await r.json();
    topics = data.titles || [];

    if (!activeTitleId && topics.length) {
      activeTitleId = topics[0].title_id;
      activeTitleName = topics[0].title_name;
      $("topicBadge").textContent = "Topic: " + activeTitleName;
    }

    renderTopics();
    if (activeTitleId) await loadDetail(activeTitleId);

    setStatus("Idle");
  } catch (e) {
    setStatus("Err: history");
    tgtLive = "[UI] Load history failed: " + (e?.message || e);
    renderTarget();
  }
}

async function loadDetail(id) {
  setStatus("Loading detail...");
  try {
    const r = await fetch(endpoints.detail(id));
    const data = await r.json();

    srcHistory = (data.original_text || "").trim();
    tgtHistory = (data.translated_text || "").trim();

    // khi click history thì reset live (nếu không đang ghi)
    if (!isRecording && !pendingStop) {
      srcLive = "";
      tgtLive = "";
    }

    renderSource();
    renderTarget();
    setStatus("Idle");
  } catch (e) {
    setStatus("Err: detail");
    tgtLive = "[UI] Load detail failed: " + (e?.message || e);
    renderTarget();
  }
}

$("btnReload").onclick = loadHistory;

$("btnNewTopic").onclick = async () => {
  const name = prompt("New topic name:", "Meeting " + new Date().toLocaleTimeString());
  if (!name) return;

  try {
    const r = await fetch(endpoints.newTopic(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title_name: name }),
    });
    const data = await r.json();

    activeTitleId = data.title_id;
    activeTitleName = data.title_name;
    $("topicBadge").textContent = "Topic: " + activeTitleName;

    await loadHistory();
  } catch (e) {
    alert("Err: " + (e?.message || e));
  }
};

/* ======================
 * LANG CONTROLS
 * ====================== */
$("btnSwap").addEventListener("click", () => {
  [sourceLang, targetLang] = [targetLang, sourceLang];
  updateLangUI();
});

$("srcBlock").addEventListener("click", () => {
  const keys = Object.keys(LANGS);
  sourceLang = keys[(keys.indexOf(sourceLang) + 1) % keys.length];
  updateLangUI();
});

$("tgtBlock").addEventListener("click", () => {
  const keys = Object.keys(LANGS);
  targetLang = keys[(keys.indexOf(targetLang) + 1) % keys.length];
  updateLangUI();
});

/* ======================
 * WS Helpers
 * ====================== */
function wsSend(obj) {
  if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj));
}

function cleanupAudio() {
  if (sendTimer) clearInterval(sendTimer);
  sendTimer = null;
  pcmQueue = [];

  if (processor) {
    try { processor.disconnect(); } catch {}
    processor = null;
  }
  if (audioCtx) {
    try { audioCtx.close(); } catch {}
    audioCtx = null;
  }
  if (micStream) {
    try { micStream.getTracks().forEach((t) => t.stop()); } catch {}
    micStream = null;
  }
}

function closeWs() {
  if (ws) {
    try { ws.onopen = ws.onmessage = ws.onerror = ws.onclose = null; } catch {}
    try { ws.close(); } catch {}
  }
  ws = null;
}

function finalizeStopCloseWs() {
  pendingStop = false;
  if (stopTimer) clearTimeout(stopTimer);
  stopTimer = null;

  cleanupAudio();
  closeWs();

  setStatus("Idle");
}

function scheduleReconnect() {
  if (!allowReconnect) return;
  if (!isRecording) return;          // chỉ reconnect khi đang record
  if (pendingStop) return;           // stop thì không reconnect
  if (reconnectTimer) return;

  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    console.warn("[WS] reconnect...");
    startRecording(true);
  }, 600);
}

/* ======================
 * RECORDING
 * ====================== */
async function startRecording(isReconnect = false) {
  if ((isRecording || pendingStop) && !isReconnect) return;

  // CHẶN open 2 lần
  if (ws && (ws.readyState === 0 || ws.readyState === 1)) {
    console.warn("[UI] WS already open, ignore start");
    return;
  }

  if (!activeTitleId) {
    alert("Chưa có topic. Bấm New Topic hoặc chọn topic trong History.");
    return;
  }

  isRecording = true;
  $("btnRecord").classList.add("recording");
  setStatus("Connecting...");

  if (!isReconnect) {
    // reset live only (history giữ nguyên)
    srcLive = "";
    tgtLive = "";
    renderSource();
    renderTarget();
  }

  ws = new WebSocket(wsUrl());

  ws.onopen = async () => {
    setStatus("Recording...");

    wsSend({
      type: "init",
      title_id: activeTitleId,
      title_name: activeTitleName,
      stt_language: sourceLang,
      translate_source: sourceLang,
      translate_target: targetLang,
    });

    await initAudio();
  };

  ws.onmessage = (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }

    // =========================================================
    // CÁCH A (Backend mới):
    //  - stt.delta: {text: draft, delta: legacy_delta}
    //  - stt.commit: {text: committed_segment}
    //  - translation.delta: stream for CURRENT committed segment
    //  - translation.commit: {text: committed_translation}
    // =========================================================

    // -------------------------
    // STT DELTA (LIVE DRAFT)
    // -> replace srcLive bằng msg.text
    // -------------------------
    if (msg.type === "stt.delta") {
      const draft = (msg.text ?? "").toString();
      srcLive = draft;     // REPLACE (quan trọng)
      renderSource();
      return;
    }

    // -------------------------
    // STT COMMIT (APPEND HISTORY)
    // -> append vào srcHistory, clear srcLive
    // -------------------------
    if (msg.type === "stt.commit") {
      const seg = (msg.text || "").toString().trim();
      if (seg) {
        srcHistory = appendHistoryLine(srcHistory, seg);
        srcLive = ""; // committed rồi thì live reset
        renderSource();
      }
      return;
    }

    // -------------------------
    // TRANSLATION DELTA
    // -> streaming vào tgtLive (append)
    // -------------------------
    if (msg.type === "translation.delta") {
      const d = (msg.delta || msg.text_delta || "").toString();
      if (d) {
        tgtLive += d;
        renderTarget();
      }
      return;
    }

    // -------------------------
    // TRANSLATION COMMIT
    // -> append vào tgtHistory, clear tgtLive
    // -------------------------
    if (msg.type === "translation.commit") {
      const seg = (msg.text || "").toString().trim();
      if (seg) {
        tgtHistory = appendHistoryLine(tgtHistory, seg);
        tgtLive = "";
        renderTarget();
      }
      return;
    }

    // -------------------------
    // SUMMARY
    // -------------------------
    if (msg.type === "summary.update") {
      console.log("🧠 summary:", msg.summary);
      return;
    }

    // -------------------------
    // FINAL RESULT
    // (backend sẽ overwrite whole history files)
    // -------------------------
    if (msg.type === "final.result") {
      const fullSrc = (msg.source || "").toString().trim();
      const fullTgt = (msg.target || "").toString().trim();

      if (fullSrc) srcHistory = fullSrc;
      if (fullTgt) tgtHistory = fullTgt;

      srcLive = "";
      tgtLive = "";

      renderSource();
      renderTarget();

      if (pendingStop) finalizeStopCloseWs();
      else setStatus("Idle");
      return;
    }

    // -------------------------
    // ERROR
    // -------------------------
    if (msg.type === "error") {
      const err = (msg.error || msg.message || "unknown").toString();
      setStatus("Err: " + err);
      tgtLive = "[SERVER ERROR] " + err;
      renderTarget();

      if (pendingStop) finalizeStopCloseWs();
      return;
    }

    console.log("[WS] unknown msg", msg);
  };

  ws.onerror = () => {
    console.warn("[WS ERROR]");
    setStatus("WS Error");
    cleanupAudio();
    closeWs();
    scheduleReconnect();
  };

  ws.onclose = (ev) => {
    console.warn("[WS CLOSE]", {
      code: ev.code,
      reason: ev.reason,
      wasClean: ev.wasClean,
      isRecording,
      pendingStop,
    });

    // nếu đang record mà ws rớt => reconnect
    if (isRecording && !pendingStop) {
      cleanupAudio();
      closeWs();
      setStatus("Disconnected");
      scheduleReconnect();
    }
  };
}

function stopRecording() {
  if (!isRecording) return;

  isRecording = false;
  pendingStop = true;
  allowReconnect = false;

  $("btnRecord").classList.remove("recording");
  setStatus("Committing...");

  // stop mic but keep WS open for final.result
  cleanupAudio();

  wsSend({ type: "stop" });

  if (stopTimer) clearTimeout(stopTimer);
  stopTimer = setTimeout(() => {
    if (pendingStop) setStatus("Waiting translation...");
  }, 30000);
}

$("btnRecord").onclick = () => {
  if (!isRecording) allowReconnect = true;
  isRecording ? stopRecording() : startRecording(false);
};

/* ======================
 * AUDIO → PCM16(base64) → WS
 * ====================== */
async function initAudio() {
  micStream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true },
  });

  audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  const src = audioCtx.createMediaStreamSource(micStream);

  processor = audioCtx.createScriptProcessor(4096, 1, 1);
  processor.onaudioprocess = (e) => {
    if (!isRecording) return;

    const input = e.inputBuffer.getChannelData(0);

    // resample -> 16k PCM16
    const targetRate = 16000;
    const ratio = audioCtx.sampleRate / targetRate;
    const newLen = Math.round(input.length / ratio);
    const pcm16 = new Int16Array(newLen);

    for (let i = 0; i < newLen; i++) {
      const s = Math.max(-1, Math.min(1, input[Math.round(i * ratio)]));
      pcm16[i] = s < 0 ? (s * 0x8000) : (s * 0x7fff);
    }

    pcmQueue.push(new Uint8Array(pcm16.buffer));
  };

  src.connect(processor);
  processor.connect(audioCtx.destination);

  // send each 250ms
  if (sendTimer) clearInterval(sendTimer);
  sendTimer = setInterval(() => {
    if (!isRecording) return;
    if (!pcmQueue.length) return;
    if (!ws || ws.readyState !== 1) return;

    const len = pcmQueue.reduce((a, b) => a + b.length, 0);
    const all = new Uint8Array(len);
    let off = 0;
    pcmQueue.forEach((chunk) => {
      all.set(chunk, off);
      off += chunk.length;
    });
    pcmQueue = [];

    // Uint8Array -> base64
    let bin = "";
    for (let i = 0; i < all.length; i++) bin += String.fromCharCode(all[i]);
    const b64 = btoa(bin);

    wsSend({ type: "audio.chunk", pcm16_b64: b64 });
  }, 500);
}

/* ======================
 * INIT
 * ====================== */
updateLangUI();
loadHistory();
renderSource();
renderTarget();
setStatus("Idle");
