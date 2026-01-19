// =======================
// CONFIG
// =======================
const API_BASE = "http://localhost:3000"; // đổi theo BE 
const CHUNK_DURATION = 2000; // 2s
const SILENCE_TIMEOUT = 5000; // 5s

let mediaRecorder;
let audioChunks = [];
let silenceTimer = null;
let currentTopicId = null;

// =======================
// CREATE NEW TOPIC
// =======================
async function createTopic(titleName) {
  const res = await fetch(`${API_BASE}/api/new_topic`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title_name: titleName })
  });

  const data = await res.json();
  currentTopicId = data.title_id;
  console.log("New topic:", data);
  return data;
}

// =======================
// START RECORDING
// =======================
async function startRecording(topicId) {
  currentTopicId = topicId;

  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  mediaRecorder = new MediaRecorder(stream, {
    mimeType: "audio/webm"
  });

  mediaRecorder.ondataavailable = async (e) => {
    if (e.data.size > 0) {
      resetSilenceTimer();
      const wavBlob = await webmToWav(e.data);
      sendAudio(wavBlob);
    }
  };

  mediaRecorder.start(CHUNK_DURATION);
  resetSilenceTimer();
  console.log("Recording started...");
}

// =======================
// STOP RECORDING
// =======================
function stopRecording() {
  if (mediaRecorder) {
    mediaRecorder.stop();
    mediaRecorder = null;
  }
  clearTimeout(silenceTimer);
  console.log("Recording stopped");
}

// =======================
// SEND AUDIO TO SERVER
// =======================
async function sendAudio(wavBlob) {
  const base64Audio = await blobToBase64(wavBlob);

  await fetch(`${API_BASE}/api/virecord`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      topic_id: currentTopicId,
      audio: base64Audio,
      source_language: "vi",
      target_language: "zh"
    })
  });
}

// =======================
// Phát hiện người dùng NGỪNG NÓI trong 5 giây
// =======================
function resetSilenceTimer() {
  clearTimeout(silenceTimer);
  silenceTimer = setTimeout(sendSilenceSignal, SILENCE_TIMEOUT);
}

async function sendSilenceSignal() {
  console.log("Silence detected → new line");
// Báo cho backend biết
  await fetch(`${API_BASE}/api/virecord/silence`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic_id: currentTopicId })
  });
}

// =======================
// HISTORY
// =======================
async function getRecordHistory() {
  const res = await fetch(`${API_BASE}/api/record_history`);
  return res.json();
}

// =======================
// DETAIL
// =======================
async function getRecordDetail(titleId) {
  const res = await fetch(
    `${API_BASE}/api/record_detail?title_id=${titleId}`
  );
  return res.json();
}

// =======================
// DELETE
// =======================
async function deleteRecord(titleId) {
  const res = await fetch(
    `${API_BASE}/api/record_delete/title_id=${titleId}`
  );
  return res.json();
}

// =======================
// biến file âm thanh thành chữ để nhét vào JSON gửi server
// =======================
function blobToBase64(blob) {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onloadend = () =>
      resolve(reader.result.split(",")[1]);
    reader.readAsDataURL(blob);
  });
}

// Convert webm → wav
async function webmToWav(webmBlob) {
  const audioCtx = new AudioContext({ sampleRate: 16000 });
  const arrayBuffer = await webmBlob.arrayBuffer();
  const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);

  return encodeWav(audioBuffer);
}

// Encode WAV PCM 16bit (biến audio RAM thành file WAV thật)
function encodeWav(audioBuffer) {
  const channelData = audioBuffer.getChannelData(0);
  const buffer = new ArrayBuffer(44 + channelData.length * 2);
  const view = new DataView(buffer);

  writeString(view, 0, "RIFF");
  view.setUint32(4, 36 + channelData.length * 2, true);
  writeString(view, 8, "WAVE");
  writeString(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, 16000, true);
  view.setUint32(28, 16000 * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(view, 36, "data");
  view.setUint32(40, channelData.length * 2, true);

  let offset = 44;
  for (let i = 0; i < channelData.length; i++) {
    const sample = Math.max(-1, Math.min(1, channelData[i]));
    view.setInt16(offset, sample * 0x7fff, true);
    offset += 2;
  }

  return new Blob([buffer], { type: "audio/wav" });
}
// Ghi chữ (ASCII string) vào buffer nhị phân để tạo header file WAV.
function writeString(view, offset, str) {
  for (let i = 0; i < str.length; i++) {
    view.setUint8(offset + i, str.charCodeAt(i));
  }
}
