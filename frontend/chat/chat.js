const URL = "http://127.0.0.1:8000" ; 
const API_URL = URL + "/api/chat";
const LIST_API = URL +"/api/conversations";
const DETAIL_API_BASE = URL +"/api/conversations";
const CREATE_API = URL +"/api/creatnew";
const DELETE_API_BASE = URL +"/api/delete_conversations";

let currentConversationId = null;


/* ================= RANDOM WELLCOMEMASSAGE ================= */
const welcomeMessages = [
  {
    title: "Hello !",
    subtitle: "What would you like to do today ?"
  },
  {
    title: "Welcome to ViChat !",
    subtitle: "Where should we start?"
  },
  {
    title: "Ready when you are !",
    subtitle: "Ask me anything."
  },
  {
    title: "Is there anything we can help you with ?",
    subtitle: "We are here to assist you."
  }
]; 

window.addEventListener("DOMContentLoaded", () => {
  const welcome = document.getElementById("welcomeScreen");
  welcome.style.display = "none";
  requestAnimationFrame(() => {
    welcome.style.display = "flex";
    showRandomWelcome();
  });
});

/* ================= HIEU UNG RANDOM WELLCOMEMASSAGE ================= */
let typingTimers = new WeakMap();

function typeText(el, text, speed = 35) {
  // nếu element này đang gõ → dừng nó
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

  // reset
  welcome.classList.remove("show");
  subEl.style.opacity = 0;

  // trigger animation
  requestAnimationFrame(() => {
    welcome.classList.add("show");
    typeText(titleEl, pick.title);
    setTimeout(() => {
      typeText(subEl, pick.subtitle, 20);
      subEl.style.opacity = 1;
    }, 400);
  });
}


/* ================= SEND MESSAGE ================= */

async function sendMessage() {
  const input = document.getElementById("input");
  const text = input.value.trim();
  if (!text) return;
  
   //  hide welcome khi bắt đầu chat
  document.getElementById("welcomeScreen").style.display = "none";

  // 1) UI: hiển thị user trước (giống hệt code cũ)
  addMessage(text, "user");
  input.value = "";
  showTyping();
  try {
    // 2) Nếu là New Chat (chưa có id) -> tạo hội thoại mới trước
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

      const created = await createRes.json(); // { conversation_id, title }
      currentConversationId = created.conversation_id;

      // cập nhật history (không chặn luồng chat)
      loadHistory().catch(console.error);
    }

    // 3) Chat bình thường (giống code cũ, chỉ thay id)
    const res = await fetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        conversation_id: currentConversationId,
        role: "user",
        message: text
      })
    });

    if (!res.ok) {
      const errText = await res.text();
      throw new Error(`HTTP ${res.status}: ${errText}`);
    }

    const data = await res.json();
    const aiMsg = data.message;
    hideTyping();
    // 4) UI: hiển thị bot (giống hệt code cũ)
    addMessage(aiMsg.content, aiMsg.role);

  } catch (err) {
    console.error(err);
    hideTyping();
    addMessage("⚠️ Server not responding", "assistant");
  }
}


/* ================= MESSAGE UI ================= Hàm này dùng để hiển thị tin nhắn  */
function addMessage(text, type) {
  const container = document.querySelector(".chat-container"); // lấy container

  const div = document.createElement("div");
  div.className = type;
  div.innerText = text;       // style cho từng role 

  container.appendChild(div);  //Gắn message mới vào cuối danh sách
  container.parentElement.scrollTop = container.parentElement.scrollHeight; // tự động kéo màn hình xuống tin nhắn mới nhất
}

/* ================= SIDEBAR =================  Thái sửa lại đoạn này code cho a  đây là phần lịch sử đó */
const menuBtn = document.getElementById("menuBtn");
const app = document.querySelector(".app");

menuBtn.addEventListener("click", () => {
  app.classList.toggle("sidebar-open");
});

/* ================= EVENTS Khi ấn nút gửi  =================  */
document.getElementById("sendBtn").addEventListener("click", sendMessage); // Nếu ấn vào nút sendBTn thì đưa tin nhắn vào hàm sendMessgae
document.getElementById("input").addEventListener("keydown", (e) => {     //  Tương tự nhưng là ấn nút enter
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
  container.parentElement.scrollTop = container.parentElement.scrollHeight;
}
function hideTyping() {
  const el = document.getElementById("typing-indicator");
  if (el) el.remove();
}

/* ================= NEW CHAT ================= */
const newChatBtn = document.getElementById("newChatBtn");

newChatBtn.addEventListener("click", () => {
  // reset trạng thái
  currentConversationId = null;

  // xoá UI chat
  const container = document.querySelector(".chat-container");
  container.innerHTML = "";

  // bật welcome screen
  const welcome = document.getElementById("welcomeScreen");
  welcome.style.display = "flex";

  // random lại câu chào
  showRandomWelcome();

  setPageTitle(""); 
  // focus input
  const input = document.getElementById("input");
  input.value = "";
  input.focus();

  // (tuỳ chọn) bỏ active history
  document
    .querySelectorAll(".history li.active")
    .forEach(li => li.classList.remove("active"));
});



/* ================= HISTORY LIST ================= */
const historyUl = document.querySelector(".history");
/* ================= CONFIRM DELETE MODAL (UI) ================= */
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
  // fallback nếu HTML chưa có modal
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

// Buttons
if (confirmOkBtn) confirmOkBtn.addEventListener("click", () => closeConfirmModal(true));
if (confirmCancelBtn) confirmCancelBtn.addEventListener("click", () => closeConfirmModal(false));

// Click outside to close
if (confirmOverlay) {
  confirmOverlay.addEventListener("click", (e) => {
    if (e.target === confirmOverlay) closeConfirmModal(false);
  });
}

// ESC to close
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

    // ✅ 1 listener duy nhất: click ra ngoài thì đóng mọi menu đang mở
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

      // title
      const titleSpan = document.createElement("span");
      titleSpan.textContent = c.title || `Conversation ${c.conversation_id}`;
      titleSpan.className = "history-title-text";

      // click load conversation
      titleSpan.addEventListener("click", () => {
        loadConversationDetail(c.conversation_id);

        setPageTitle(c.title || `Conversation ${c.conversation_id}`);

        document
        .querySelectorAll(".history li.active")
        .forEach(x => x.classList.remove("active"));

        li.classList.add("active");
      });


      /* ================= UI DELETE: 3 dots + menu ================= */
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

      // open / close menu (không cho click lan ra ngoài)
      moreBtn.addEventListener("click", (e) => {
        e.stopPropagation();

        // đóng menu khác trước
        document
          .querySelectorAll(".history-actions.open")
          .forEach(el => {
            if (el !== actions) el.classList.remove("open");
          });

        actions.classList.toggle("open");
      });

      // click delete
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

          // ✅ xoá khỏi UI ngay
          li.remove();

          // nếu đang mở đúng chat bị xoá
          if (String(currentConversationId) === String(c.conversation_id)) {
            currentConversationId = null;
            document.querySelector(".chat-container").innerHTML = "";
          }

        } catch (err) {
          console.error(err);
          alert("Delete failed");
        }
      });

      /* ================= append ================= */
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





/* ================= LOAD CONVERSATION DETAIL ================= */
async function loadConversationDetail(conversationId) {
  try {
     //  hide welcome khi mở chat cũ
    document.getElementById("welcomeScreen").style.display = "none";

    const res = await fetch(`${DETAIL_API_BASE}/${conversationId}`);
    if (!res.ok) {
      const errText = await res.text();
      throw new Error(`HTTP ${res.status}: ${errText}`);
    }

    const data = await res.json();
    const messages = data.messages || [];

    // set trạng thái hiện tại
    currentConversationId = data.conversation_id;

    // clear UI chat
    const container = document.querySelector(".chat-container");
    container.innerHTML = "";

    // render messages
    messages.forEach(m => {
      addMessage(m.content, m.role);
    });

  } catch (err) {
    console.error("Load conversation detail failed:", err);
  }
}




async function deleteConversation(conversationId) {
  try {
    const res = await fetch(`${DELETE_API_BASE}/${conversationId}/`, {
      method: "DELETE"
    });

    if (!res.ok) {
      const errText = await res.text();
      throw new Error(`HTTP ${res.status}: ${errText}`);
    }

    const data = await res.json(); // { success: true }
    if (!data.success) throw new Error("Delete failed");

    // Nếu đang mở đúng chat bị xoá → reset UI
    if (String(currentConversationId) === String(conversationId)) {
      currentConversationId = null;
      document.querySelector(".chat-container").innerHTML = "";
      document.getElementById("input").value = "";
      setPageTitle("");
    }

    // Reload history
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
 