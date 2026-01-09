const API_URL = "http://127.0.0.1:8000/api/chat";
//const UPLOAD_URL = "http://localhost:8000/api/upload-image";

/* ================= SEND MESSAGE ================= */
async function sendMessage() {
  const input = document.getElementById("input");  // lấy text 
  const text = input.value.trim();        // kiểm tra xem có phải là rỗng không 
  if (!text) return;

  // hiển thị user trước
  addMessage(text, "user"); // đưa vàod dể hiển thị tin nhắn
  input.value = ""; // xoá input cũ

  try {
    const res = await fetch(API_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        conversation_id: 1, // đoạn này phải xử lý lại để mỗi lần bật app thì cuộc trò truyện là 1-> n // phần này làm sau khi tạo xong phần newchat
        role: "user", // role chắc chắn là user
        message: text
      })
    });

    if (!res.ok) {
      const errText = await res.text();
      throw new Error(`HTTP ${res.status}: ${errText}`); // check code status nếu từ 200->209 coi là có lỗi nhảy về catch
    }

    // backend trả về  content
    const data = await res.json();
    const aiMsg = data.message;// role = "assistant"
    addMessage(aiMsg.content, aiMsg.role); // đưa content cho hiển thị

  } catch (err) {// nếu lỗi thì return 
    console.error(err);
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
/* 
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

 ================= IMAGE UPLOAD ================= Chưa  dùng không động vào 
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
*/
/* ================= SIDEBAR =================  Thái sửa lại đoạn này code cho a */
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
