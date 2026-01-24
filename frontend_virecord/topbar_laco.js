/* =========================================================
  app.js (UI only) - FILE CHỈ LO GIAO DIỆN
  ---------------------------------------------------------
  Mục tiêu file này:
  1) Mở/đóng Drawer (top bar menu bên trái)
  2) Chọn ngôn ngữ nguồn/đích trong Drawer
  3) Khi chọn ngôn ngữ -> đổi icon + label + đổi nền cờ (background split)
  4) Lưu trạng thái ngôn ngữ vào:
     - #srcLang.value, #dstLang.value (hidden input)
     - #app.dataset.src, #app.dataset.dst (data attributes)

  IMPORTANT:
  - File này KHÔNG gọi API, KHÔNG dịch thuật.
  - Việc lấy dữ liệu / đổ dữ liệu dịch sẽ do file khác (name.js) xử lý.
  - Để tránh xung đột biến/hàm với name.js, ta bọc toàn bộ file trong IIFE.
========================================================= */
(() => {
  "use strict";

  /* =========================
    1) CONFIG NGÔN NGỮ
    -------------------------
    Map code -> thông tin UI
    - code: "vi" | "zh" | "en"
    - label: hiển thị trên nút chọn ngôn ngữ
    - flag: đường dẫn ảnh (đúng thư mục photo/)
    - tint: màu phủ nhẹ lên nền cho đẹp

    NOTE cho backend/name.js:
    - Backend chỉ cần quan tâm code (vi/zh/en).
  ========================= */
  const LANG = {
    vi: { label: "Vietnamese", flag: "photo/VN.png", tint: "#fdecec" },
    zh: { label: "Chinese", flag: "photo/tw.png", tint: "#eef2ff" },
    en: { label: "English", flag: "photo/en.png", tint: "#eef7ff" },
  };

  /* =========================
    2) DOM ELEMENTS (CÁC ĐIỂM MÓC)
    -----------------------------
    - app: root element, có data-src/data-dst để lưu state
    - drawerWrap: lớp phủ + drawer (thêm class is-open để mở)
    - btnDrawer / btnDrawerClose: nút mở/đóng drawer

    - srcLangBtn / dstLangBtn: nút dropdown chọn ngôn ngữ
    - srcLangMenu / dstLangMenu: menu danh sách ngôn ngữ
    - srcLangFlag / dstLangFlag: icon cờ trên nút
    - srcLangLabel / dstLangLabel: text label trên nút

    - srcHidden / dstHidden: hidden input lưu code ngôn ngữ
      => Đây là chỗ name.js/back-end NÊN đọc để biết ngôn ngữ hiện tại
    - btnSwap: nút swap 2 ngôn ngữ
  ========================= */
  const app = document.getElementById("app");
  const drawerWrap = document.getElementById("drawerWrap");
  const btnDrawer = document.getElementById("btnDrawer");
  const btnDrawerClose = document.getElementById("btnDrawerClose");

  const srcLangBtn = document.getElementById("srcLangBtn");
  const dstLangBtn = document.getElementById("dstLangBtn");
  const srcLangMenu = document.getElementById("srcLangMenu");
  const dstLangMenu = document.getElementById("dstLangMenu");

  const srcLangFlag = document.getElementById("srcLangFlag");
  const dstLangFlag = document.getElementById("dstLangFlag");
  const srcLangLabel = document.getElementById("srcLangLabel");
  const dstLangLabel = document.getElementById("dstLangLabel");

  const srcHidden = document.getElementById("srcLang");
  const dstHidden = document.getElementById("dstLang");

  const btnSwap = document.getElementById("btnSwapLang");

  /* =========================
    3) DRAWER OPEN/CLOSE
    -------------------------
    - Mở: thêm class "is-open" vào #drawerWrap
    - Đóng: xóa class "is-open"
    - aria-hidden: cập nhật để hỗ trợ accessibility
  ========================= */
  function openDrawer() {
    drawerWrap.classList.add("is-open");
    drawerWrap.setAttribute("aria-hidden", "false");
  }

  function closeDrawer() {
    drawerWrap.classList.remove("is-open");
    drawerWrap.setAttribute("aria-hidden", "true");
  }

  /* =========================
    4) DROPDOWN MENU (NGÔN NGỮ) OPEN/CLOSE
    -------------------------
    closeMenus(): đóng cả 2 menu (src + dst)
    toggleMenu(which): bật/tắt menu theo which = "src" hoặc "dst"
  ========================= */
  function closeMenus() {
    // đóng menu bằng cách remove class "open" ở .lang-select chứa nút
    srcLangBtn.closest(".lang-select").classList.remove("open");
    dstLangBtn.closest(".lang-select").classList.remove("open");

    // cập nhật aria-expanded
    srcLangBtn.setAttribute("aria-expanded", "false");
    dstLangBtn.setAttribute("aria-expanded", "false");
  }

  function toggleMenu(which) {
    // xác định menu nào cần thao tác
    const wrap =
      which === "src"
        ? srcLangBtn.closest(".lang-select")
        : dstLangBtn.closest(".lang-select");

    const btn = which === "src" ? srcLangBtn : dstLangBtn;

    // nếu đang đóng -> mở, nếu đang mở -> đóng
    const willOpen = !wrap.classList.contains("open");

    // luôn đóng hết trước để tránh mở 2 menu cùng lúc
    closeMenus();

    if (willOpen) {
      wrap.classList.add("open");
      btn.setAttribute("aria-expanded", "true");
    }
  }

  /* =========================
    5) APPLY BACKGROUND (ĐỔI NỀN CỜ)
    -------------------------
    Ý tưởng:
    - CSS dùng 2 biến:
        --src-bg  (nền nửa trên / hoặc vùng src)
        --dst-bg  (nền nửa dưới / hoặc vùng dst)
      và 2 màu phủ:
        --src-tint, --dst-tint

    Khi user chọn ngôn ngữ:
    - Ta đọc srcHidden.value / dstHidden.value
    - Set CSS variables trên documentElement (:root)
  ========================= */
  function applyBackground() {
    const src = srcHidden.value; // "vi" | "zh" | "en"
    const dst = dstHidden.value;

    // Đổi ảnh nền theo ngôn ngữ
    document.documentElement.style.setProperty(
      "--src-bg",
      `url("${LANG[src].flag}")`,
    );
    document.documentElement.style.setProperty(
      "--dst-bg",
      `url("${LANG[dst].flag}")`,
    );

    // Đổi tint (màu phủ nhẹ)
    document.documentElement.style.setProperty("--src-tint", LANG[src].tint);
    document.documentElement.style.setProperty("--dst-tint", LANG[dst].tint);
  }

  /* =========================
    6) SET LANGUAGE (CẬP NHẬT STATE + UI)
    -------------------------
    setLang(which, code):
    - which: "src" hoặc "dst"
    - code: "vi" | "zh" | "en"

    Nó sẽ:
    1) cập nhật hidden input (#srcLang/#dstLang)  -> backend/name.js nên đọc
    2) cập nhật dataset (#app.dataset.src / .dst) -> thêm kênh đọc state
    3) cập nhật icon + label trên nút dropdown
    4) gọi applyBackground() để đổi nền
    5) đóng menu
  ========================= */
  function setLang(which, code) {
    // code không hợp lệ thì bỏ qua
    if (!LANG[code]) return;

    if (which === "src") {
      // 1) STATE: ngôn ngữ nguồn
      srcHidden.value = code;
      app.dataset.src = code;

      // 2) UI: icon + label
      srcLangFlag.src = LANG[code].flag;
      srcLangLabel.textContent = LANG[code].label;
    } else {
      // 1) STATE: ngôn ngữ đích
      dstHidden.value = code;
      app.dataset.dst = code;

      // 2) UI: icon + label
      dstLangFlag.src = LANG[code].flag;
      dstLangLabel.textContent = LANG[code].label;
    }

    // 3) đổi nền
    applyBackground();

    // 4) đóng menu
    closeMenus();
  }

  /* =========================
    7) EVENTS (GẮN SỰ KIỆN)
    -------------------------
    Drawer:
    - Click #btnDrawer -> openDrawer
    - Click #btnDrawerClose (backdrop) -> closeDrawer

    Esc:
    - đóng menu + đóng drawer

    Click ngoài dropdown:
    - đóng menu để tránh bị kẹt open

    Dropdown:
    - Click nút src/dst -> toggleMenu("src"/"dst")
    - Click item trong menu -> setLang(...)

    Swap:
    - đổi src <-> dst
  ========================= */

  // Drawer open/close
  btnDrawer.addEventListener("click", openDrawer);
  btnDrawerClose.addEventListener("click", closeDrawer);

  // Nhấn ESC để đóng hết
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeMenus();
      closeDrawer();
    }
  });

  // Click ra ngoài dropdown thì đóng dropdown
  document.addEventListener("click", (e) => {
    const inLangUI = e.target.closest(".lang-select");
    if (!inLangUI) closeMenus();
  });

  // Toggle dropdown
  srcLangBtn.addEventListener("click", (e) => {
    // stopPropagation để không bị document click đóng ngay lập tức
    e.stopPropagation();
    toggleMenu("src");
  });

  dstLangBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    toggleMenu("dst");
  });

  // Chọn item trong menu nguồn
  srcLangMenu.addEventListener("click", (e) => {
    const item = e.target.closest(".lang-item");
    if (!item) return;

    // item.dataset.lang lấy từ HTML: data-lang="vi|zh|en"
    setLang("src", item.dataset.lang);
  });

  // Chọn item trong menu đích
  dstLangMenu.addEventListener("click", (e) => {
    const item = e.target.closest(".lang-item");
    if (!item) return;

    setLang("dst", item.dataset.lang);
  });

  // Swap 2 ngôn ngữ
  btnSwap.addEventListener("click", () => {
    const a = srcHidden.value; // src hiện tại
    const b = dstHidden.value; // dst hiện tại

    // swap
    setLang("src", b);
    setLang("dst", a);
  });

  /* =========================
    8) INIT (KHỞI TẠO)
    -------------------------
    Khi vừa load trang:
    - đọc giá trị mặc định trong hidden input
    - applyBackground() để nền hiển thị đúng ngay từ đầu
  ========================= */
  applyBackground();

  /* =========================
    9) GHI CHÚ CHO FILE name.js (DATA FLOW)
    -------------------------
    name.js / backend sẽ làm:
    - LẤY DỮ LIỆU:
        const src = document.getElementById("srcLang").value;
        const dst = document.getElementById("dstLang").value;
        const text = document.getElementById("inputText").value;

    - ĐỔ KẾT QUẢ:
        document.getElementById("outputText").innerText = resultText;

    Không cần gọi hàm trong app.js (vì app.js được bọc IIFE).
  ========================= */
})();
