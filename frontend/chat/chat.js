const URL = "http://127.0.0.1:8000";
const API_URL = URL + "/api/chat";                 // (không dùng nữa cho chat, giữ lại nếu anh cần fallback)
const LIST_API = URL + "/api/conversations";
const DETAIL_API_BASE = URL + "/api/conversations";
const CREATE_API = URL + "/api/creatnew";
const DELETE_API_BASE = URL + "/api/delete_conversations";

// ================= WS CONFIG =================
const WS_URL = (() => {
  // Tự chuyển http -> ws
  if (URL.startsWith("https://")) return "wss://" + URL.slice(8) + "/ws/vichat/";
  if (URL.startsWith("http://"))  return "ws://"  + URL.slice(7) + "/ws/vichat/";
  return "ws://127.0.0.1:8000/ws/vichat/";
})();

let ws = null;
let wsReadyPromise = null;

let currentConversationId = null;

// stream state
let currentAssistantEl = null;
let pendingUserTextForCreate = null;

// ================= RANDOM WELLCOMEMASSAGE =================
const welcomeMessages = [
  { title: "Hello !", subtitle: "What would you like to do today ?" },
  { title: "Welcome to ViChat !", subtitle: "Where should we start?" },
  { title: "Ready when you are !", subtitle: "Ask me anything." },
  { title: "Is there anything we can help you with ?", subtitle: "We are here to assist you." }
];

window.addEventListener("DOMContentLoaded", () => {
  const welcome = document.getElementById("welcomeScreen");
  welcome.style.display = "none";
  requestAnimationFrame(() => {
    welcome.style.display = "flex";
    showRandomWelcome();
  });
});

// ================= HIEU UNG RANDOM WELLCOMEMASSAGE =================
let typingTimers = new WeakMap();

function typeText(el, text, speed = 35) {
  if (typingTimers.has(el)) {
    clearInterval(typingTimers.get(el));
  }

  el.innerHTML = "";
  let i = 0;

  const timer = setInterval(() => {
    let char = text[i];
    if (char === " ") char = "&nbsp;";
    el.innerHTML += char;
    i++;

    if (i >= text.length) {
      clearInterval(timer);
      typingTimers.delete(el);
    }
  }, speed);

  typingTimers.set(el, timer);
}

function showRandomWelcome() {
  const pick = welcomeMessages[Math.floor(Math.random() * welcomeMessages.length)];

  const welcome = document.getElementById("welcomeScreen");
  const titleEl = document.getElementById("welcomeTitle");
  const subEl = document.getElementById("welcomeSubtitle");

  welcome.classList.remove("show");
  subEl.style.opacity = 0;

  requestAnimationFrame(() => {
    welcome.classList.add("show");
    typeText(titleEl, pick.title);
    setTimeout(() => {
      typeText(subEl, pick.subtitle, 20);
      subEl.style.opacity = 1;
    }, 400);
  });
}

// ================= WS HELPERS =================
function ensureWS() {
  if (ws && ws.readyState === WebSocket.OPEN) return Promise.resolve(true);

  // nếu đang CONNECTING thì trả promise cũ
  if (ws && ws.readyState === WebSocket.CONNECTING && wsReadyPromise) return wsReadyPromise;

  wsReadyPromise = new Promise((resolve, reject) => {
    ws = new WebSocket(WS_URL);

    ws.onopen = () => resolve(true);

    ws.onerror = (e) => {
      console.error("WS error", e);
      reject(e);
    };

    ws.onclose = (e) => {
      console.warn("WS closed", e.code, e.reason);
      // reset để lần sau ensureWS() sẽ connect lại
      ws = null;
      wsReadyPromise = null;
    };

    ws.onmessage = (ev) => {
      let msg = null;
      try {
        msg = JSON.parse(ev.data);
      } catch (e) {
        console.error("WS message parse error:", e);
        return;
      }

      // ===== Protocol =====
      if (msg.type === "ws.connected") {
        return;
      }

      if (msg.type === "chat.start") {
        // tạo bubble assistant rỗng để fill token
        hideTyping();
        currentAssistantEl = addMessageReturnEl("", "assistant");
        return;
      }

      if (msg.type === "chat.delta") {
        if (!currentAssistantEl) {
          currentAssistantEl = addMessageReturnEl("", "assistant");
        }
        // append “từng chữ/từng chunk”
        currentAssistantEl.textContent += (msg.text_delta || "");
        scrollToBottom();
        return;
      }

      if (msg.type === "chat.done") {
        hideTyping();
        currentAssistantEl = null;
        return;
      }

      if (msg.type === "chat.error") {
        console.error("WS chat error:", msg.error);
        hideTyping();
        currentAssistantEl = null;
        addMessage("⚠️ " + (msg.error || "Server error"), "assistant");
        return;
      }
    };
  });

  return wsReadyPromise;
}

function wsSend(obj) {
  return ensureWS().then(() => {
    ws.send(JSON.stringify(obj));
  });
}

// ================= SEND MESSAGE =================
async function sendMessage() {
  const input = document.getElementById("input");
  const text = input.value.trim();
  if (!text) return;

  // hide welcome khi bắt đầu chat
  document.getElementById("welcomeScreen").style.display = "none";

  // 1) UI: show user trước
  addMessage(text, "user");
  input.value = "";
  showTyping();

  try {
    // 2) Nếu New Chat -> tạo conversation bằng HTTP (giữ nguyên logic backend)
    if (currentConversationId === null) {
      const createRes = await fetch(CREATE_API, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text })
      });

      if (!createRes.ok) {
        const errText = await createRes.text();
        throw new Error(`HTTP ${createRes.status}: ${errText}`);
      }

      const created = await createRes.json(); // { conversation_id, title, message: {..assistant..} }
      currentConversationId = created.conversation_id;

      // cập nhật title luôn (nếu backend trả)
      setPageTitle(created.title || "");

      // cập nhật history (không chặn luồng)
      loadHistory().catch(console.error);

      // IMPORTANT:
      // Backend create_conversation của anh đã tạo assistant message rồi.
      // Nếu anh muốn UI hiện assistant của create luôn (không cần WS):
      if (created.message && created.message.content) {
        hideTyping();
        addMessage(created.message.content, "assistant");
      } else {
        hideTyping();
      }
      return; // đã xử lý xong ở create_conversation
    }

    // 3) Chat bình thường -> dùng WS stream
    await wsSend({
      type: "chat.send",
      conversation_id: currentConversationId,
      message: text
    });

    // NOTE: phần render assistant sẽ được WS onmessage xử lý (chat.start/delta/done)

  } catch (err) {
    console.error(err);
    hideTyping();
    addMessage("⚠️ Server not responding", "assistant");
  }
}

// ================= MESSAGE UI =================
function addMessage(text, type) {
  const container = document.querySelector(".chat-container");
  const div = document.createElement("div");
  div.className = type;
  div.innerText = text;
  container.appendChild(div);
  scrollToBottom();
}

// trả về element để append dần token
function addMessageReturnEl(text, type) {
  const container = document.querySelector(".chat-container");
  const div = document.createElement("div");
  div.className = type;
  div.innerText = text || "";
  container.appendChild(div);
  scrollToBottom();
  return div;
}

function scrollToBottom() {
  const container = document.querySelector(".chat-container");
  if (!container) return;
  container.parentElement.scrollTop = container.parentElement.scrollHeight;
}

// ================= SIDEBAR =================
const menuBtn = document.getElementById("menuBtn");
const app = document.querySelector(".app");

menuBtn.addEventListener("click", () => {
  app.classList.toggle("sidebar-open");
});

// ================= EVENTS =================
document.getElementById("sendBtn").addEventListener("click", sendMessage);
document.getElementById("input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendMessage();
});

function showTyping() {
  const container = document.querySelector(".chat-container");

  const div = document.createElement("div");
  div.className = "bot typing typing-robot";
  div.id = "typing-indicator";
  div.innerHTML = `
    <span class="robot" aria-hidden="true">💬</span>
    <span class="sr-only">Thinking…</span>
  `;

  container.appendChild(div);
  scrollToBottom();
}

function hideTyping() {
  const el = document.getElementById("typing-indicator");
  if (el) el.remove();
}

// ================= NEW CHAT =================
const newChatBtn = document.getElementById("newChatBtn");

newChatBtn.addEventListener("click", () => {
  currentConversationId = null;
  currentAssistantEl = null;

  const container = document.querySelector(".chat-container");
  container.innerHTML = "";

  const welcome = document.getElementById("welcomeScreen");
  welcome.style.display = "flex";

  showRandomWelcome();

  setPageTitle("");

  const input = document.getElementById("input");
  input.value = "";
  input.focus();

  document
    .querySelectorAll(".history li.active")
    .forEach(li => li.classList.remove("active"));
});

// ================= HISTORY LIST =================
const historyUl = document.querySelector(".history");

// ================= CONFIRM DELETE MODAL (UI) =================
const confirmOverlay = document.getElementById("confirmOverlay");
const confirmOkBtn = document.getElementById("confirmOk");
const confirmCancelBtn = document.getElementById("confirmCancel");
const confirmTitleEl = document.getElementById("confirmTitle");
const confirmDescEl = document.getElementById("confirmDesc");

let _confirmResolver = null;

function openConfirmModal({
  title = "Delete conversation?",
  desc = "This action cannot be undone."
} = {}) {
  if (!confirmOverlay) return Promise.resolve(window.confirm(title));

  if (confirmTitleEl) confirmTitleEl.textContent = title;
  if (confirmDescEl) confirmDescEl.textContent = desc;

  confirmOverlay.classList.add("show");
  confirmOverlay.setAttribute("aria-hidden", "false");

  return new Promise((resolve) => {
    _confirmResolver = resolve;
  });
}

function closeConfirmModal(result) {
  if (!confirmOverlay) return;

  confirmOverlay.classList.remove("show");
  confirmOverlay.setAttribute("aria-hidden", "true");

  if (typeof _confirmResolver === "function") {
    const r = _confirmResolver;
    _confirmResolver = null;
    r(!!result);
  }
}

if (confirmOkBtn) confirmOkBtn.addEventListener("click", () => closeConfirmModal(true));
if (confirmCancelBtn) confirmCancelBtn.addEventListener("click", () => closeConfirmModal(false));

if (confirmOverlay) {
  confirmOverlay.addEventListener("click", (e) => {
    if (e.target === confirmOverlay) closeConfirmModal(false);
  });
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && confirmOverlay && confirmOverlay.classList.contains("show")) {
    closeConfirmModal(false);
  }
});

async function loadHistory() {
  try {
    const res = await fetch(LIST_API);
    if (!res.ok) throw new Error("Cannot load history");

    const data = await res.json();
    const conversations = data.conversations || [];

    historyUl.innerHTML = "";

    if (!window.__historyOutsideClickBound) {
      document.addEventListener("click", () => {
        document
          .querySelectorAll(".history-actions.open")
          .forEach(el => el.classList.remove("open"));
      });
      window.__historyOutsideClickBound = true;
    }

    conversations.forEach((c) => {
      const li = document.createElement("li");
      li.dataset.conversationId = c.conversation_id;

      const titleSpan = document.createElement("span");
      titleSpan.textContent = c.title || `Conversation ${c.conversation_id}`;
      titleSpan.className = "history-title-text";

      titleSpan.addEventListener("click", () => {
        loadConversationDetail(c.conversation_id);
        setPageTitle(c.title || `Conversation ${c.conversation_id}`);

        document
          .querySelectorAll(".history li.active")
          .forEach(x => x.classList.remove("active"));

        li.classList.add("active");
      });

      const actions = document.createElement("div");
      actions.className = "history-actions";

      const moreBtn = document.createElement("button");
      moreBtn.type = "button";
      moreBtn.className = "history-more-btn";
      moreBtn.textContent = "⋯";

      const menu = document.createElement("div");
      menu.className = "history-menu";

      const delItem = document.createElement("button");
      delItem.type = "button";
      delItem.className = "history-menu-item danger";
      delItem.textContent = "Delete";

      menu.appendChild(delItem);
      actions.appendChild(moreBtn);
      actions.appendChild(menu);

      moreBtn.addEventListener("click", (e) => {
        e.stopPropagation();

        document
          .querySelectorAll(".history-actions.open")
          .forEach(el => {
            if (el !== actions) el.classList.remove("open");
          });

        actions.classList.toggle("open");
      });

      delItem.addEventListener("click", async (e) => {
        e.stopPropagation();
        actions.classList.remove("open");

        const ok = await openConfirmModal({
          title: "Delete this conversation?",
          desc: "This action cannot be undone.",
        });
        if (!ok) return;

        try {
          const delRes = await fetch(
            `${DELETE_API_BASE}/${c.conversation_id}/`,
            { method: "DELETE" }
          );

          if (!delRes.ok) {
            console.error("Delete HTTP error", delRes.status);
            alert("Delete failed");
            return;
          }

          const result = await delRes.json();
          if (!result.success) {
            alert("Delete failed");
            return;
          }

          li.remove();

          if (String(currentConversationId) === String(c.conversation_id)) {
            currentConversationId = null;
            currentAssistantEl = null;
            document.querySelector(".chat-container").innerHTML = "";
          }

        } catch (err) {
          console.error(err);
          alert("Delete failed");
        }
      });

      li.appendChild(titleSpan);
      li.appendChild(actions);
      historyUl.appendChild(li);
    });

  } catch (err) {
    console.error(err);
    historyUl.innerHTML = `<li>Cannot load history</li>`;
  }
}

// gọi ngay khi load trang
loadHistory();

// ================= LOAD CONVERSATION DETAIL =================
async function loadConversationDetail(conversationId) {
  try {
    document.getElementById("welcomeScreen").style.display = "none";

    const res = await fetch(`${DETAIL_API_BASE}/${conversationId}`);
    if (!res.ok) {
      const errText = await res.text();
      throw new Error(`HTTP ${res.status}: ${errText}`);
    }

    const data = await res.json();
    const messages = data.messages || [];

    currentConversationId = data.conversation_id;
    currentAssistantEl = null;

    const container = document.querySelector(".chat-container");
    container.innerHTML = "";

    messages.forEach(m => {
      addMessage(m.content, m.role);
    });

  } catch (err) {
    console.error("Load conversation detail failed:", err);
  }
}

// ================= DELETE (unused helper) =================
async function deleteConversation(conversationId) {
  try {
    const res = await fetch(`${DELETE_API_BASE}/${conversationId}/`, { method: "DELETE" });

    if (!res.ok) {
      const errText = await res.text();
      throw new Error(`HTTP ${res.status}: ${errText}`);
    }

    const data = await res.json();
    if (!data.success) throw new Error("Delete failed");

    if (String(currentConversationId) === String(conversationId)) {
      currentConversationId = null;
      currentAssistantEl = null;
      document.querySelector(".chat-container").innerHTML = "";
      document.getElementById("input").value = "";
      setPageTitle("");
    }

    await loadHistory();

  } catch (err) {
    console.error("Delete conversation failed:", err);
    alert("Delete failed");
  }
}

function setPageTitle(chatTitle = "") {
  if (chatTitle && chatTitle.trim()) {
    document.title = `ViChat - ${chatTitle}`;
  } else {
    document.title = "ViChat";
  }
}

// ================= OPTIONAL: connect WS early =================
// Nếu muốn WS luôn sẵn (mở trang là connect), bật dòng dưới:
ensureWS().catch(() => {});
