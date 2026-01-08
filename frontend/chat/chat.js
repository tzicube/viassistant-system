/* ================= CONFIG ================= */
// true  = chạy mock (không cần backend)
// false = chạy backend + websocket
const USE_MOCK = true;

const API_URL = "http://localhost:8000/api/chat";
const WS_URL  = "ws://localhost:8000/ws/chat";
const UPLOAD_URL = "http://localhost:8000/api/upload-image";
const SESSION_ID = "demo-user";

/* ================= MOCK API ================= */
function mockChatAPI(message) {
  return new Promise((resolve) => {
    setTimeout(() => {
      resolve({
        reply: "🤖 (Mock AI) You said: " + message
      });
    }, 600);
  });
}

/* ================= WEBSOCKET ================= */
let socket = null;

function connectWS() {
  socket = new WebSocket(WS_URL);

  socket.onopen = () => {
    console.log("✅ WebSocket connected");
  };

  socket.onmessage = (event) => {
    addMessage(event.data, "bot");
  };

  socket.onerror = () => {
    addMessage("⚠️ WebSocket error", "bot");
  };

  socket.onclose = () => {
    console.log("❌ WebSocket closed");
  };
}

if (!USE_MOCK) {
  connectWS();
}

/* ================= WS AUTO CALL (1s) ================= */
let wsInterval = null;

function startWSAutoCall() {
  if (wsInterval) return; // tránh gọi trùng

  wsInterval = setInterval(() => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({
        type: "ping",
        session_id: SESSION_ID,
        time: Date.now()
      }));
      console.log("📡 WS ping sent");
    }
  }, 1000); // ⏱️ 1 giây
}

function stopWSAutoCall() {
  clearInterval(wsInterval);
  wsInterval = null;
}

/* ================= SEND MESSAGE ================= */
async function sendMessage() {
  const input = document.getElementById("input");
  const text = input.value.trim();
  if (!text) return;

  addMessage(text, "user");
  input.value = "";

  // 🧠 MOCK MODE
  if (USE_MOCK) {
    const data = await mockChatAPI(text);
    addMessage(data.reply, "bot");
    return;
  }

  // 🌐 WEBSOCKET MODE
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(text);
    return;
  }

  // 🌐 FALLBACK HTTP API
  try {
    const res = await fetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        session_id: SESSION_ID
      })
    });

    if (!res.ok) throw new Error("Server error");

    const data = await res.json();
    addMessage(data.reply, "bot");

  } catch (err) {
    addMessage("⚠️ Server not responding", "bot");
  }
}

/* ================= MESSAGE UI ================= */
function addMessage(text, type) {
  const container = document.querySelector(".chat-container");

  const div = document.createElement("div");
  div.className = type;
  div.innerText = text;

  container.appendChild(div);
  container.parentElement.scrollTop = container.parentElement.scrollHeight;
}

function addImageMessage(src, type) {
  const container = document.querySelector(".chat-container");

  const div = document.createElement("div");
  div.className = type;

  const img = document.createElement("img");
  img.src = src;
  img.className = "chat-image";

  div.appendChild(img);
  container.appendChild(div);

  container.parentElement.scrollTop = container.parentElement.scrollHeight;
}

/* ================= IMAGE UPLOAD ================= */
document.getElementById("uploadBtn").onclick = () => {
  document.getElementById("imageInput").click();
};

document.getElementById("imageInput").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;

  // Preview user image
  addImageMessage(URL.createObjectURL(file), "user");

  const formData = new FormData();
  formData.append("image", file);
  formData.append("session_id", SESSION_ID);

  try {
    const res = await fetch(UPLOAD_URL, {
      method: "POST",
      body: formData
    });

    const data = await res.json();

    if (data.reply) addMessage(data.reply, "bot");
    if (data.image_url) addImageMessage(data.image_url, "bot");

  } catch (err) {
    addMessage("⚠️ Image upload failed", "bot");
  }
});

/* ================= SIDEBAR ================= */
const menuBtn = document.getElementById("menuBtn");
const app = document.querySelector(".app");

menuBtn.addEventListener("click", () => {
  app.classList.toggle("sidebar-open");
});

/* ================= EVENTS ================= */
document.getElementById("sendBtn").addEventListener("click", sendMessage);

document.getElementById("input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendMessage();
});
