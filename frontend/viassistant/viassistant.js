const recordBtn = document.getElementById("recordBtn");
const stopBtn = document.getElementById("stopBtn");
const sendBtn = document.getElementById("sendBtn");
const statusEl = document.getElementById("status");
const sttText = document.getElementById("sttText");
const aiText = document.getElementById("aiText");
const ttsAudio = document.getElementById("ttsAudio");
const recordedAudio = document.getElementById("recordedAudio");
const langEl = document.getElementById("lang");

const WS_URL = "ws://127.0.0.1:8000/ws/viassistant/";
const TARGET_SAMPLE_RATE = 16000;

let audioContext = null;
let mediaStream = null;
let processor = null;
let recording = false;
let ws = null;
let inputSampleRate = 48000;

function setStatus(msg) {
  statusEl.textContent = msg;
}

function setBusy(busy) {
  sendBtn.disabled = true;
  recordBtn.disabled = busy;
  stopBtn.disabled = busy || !recording;
  if (busy) {
    setStatus("Streaming...");
  }
}

function mergeBuffers(buffers, length) {
  const result = new Float32Array(length);
  let offset = 0;
  for (const b of buffers) {
    result.set(b, offset);
    offset += b.length;
  }
  return result;
}

function downsampleBuffer(buffer, sampleRate, outRate) {
  if (outRate === sampleRate) {
    return buffer;
  }
  const ratio = sampleRate / outRate;
  const newLength = Math.round(buffer.length / ratio);
  const result = new Float32Array(newLength);
  let offsetResult = 0;
  let offsetBuffer = 0;
  while (offsetResult < result.length) {
    const nextOffsetBuffer = Math.round((offsetResult + 1) * ratio);
    let sum = 0;
    let count = 0;
    for (let i = offsetBuffer; i < nextOffsetBuffer && i < buffer.length; i++) {
      sum += buffer[i];
      count++;
    }
    result[offsetResult] = sum / count;
    offsetResult++;
    offsetBuffer = nextOffsetBuffer;
  }
  return result;
}

function encodeWav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);

  function writeString(offset, s) {
    for (let i = 0; i < s.length; i++) {
      view.setUint8(offset + i, s.charCodeAt(i));
    }
  }

  let offset = 0;
  writeString(offset, "RIFF"); offset += 4;
  view.setUint32(offset, 36 + samples.length * 2, true); offset += 4;
  writeString(offset, "WAVE"); offset += 4;
  writeString(offset, "fmt "); offset += 4;
  view.setUint32(offset, 16, true); offset += 4; // PCM
  view.setUint16(offset, 1, true); offset += 2;  // PCM
  view.setUint16(offset, 1, true); offset += 2;  // mono
  view.setUint32(offset, sampleRate, true); offset += 4;
  view.setUint32(offset, sampleRate * 2, true); offset += 4;
  view.setUint16(offset, 2, true); offset += 2;
  view.setUint16(offset, 16, true); offset += 2;
  writeString(offset, "data"); offset += 4;
  view.setUint32(offset, samples.length * 2, true); offset += 4;

  for (let i = 0; i < samples.length; i++, offset += 2) {
    let s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return buffer;
}

async function startRecording() {
  if (recording) return;
  recordedAudio.removeAttribute("src");
  sttText.textContent = "";
  aiText.textContent = "";
  ttsAudio.removeAttribute("src");

  mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  audioContext = new (window.AudioContext || window.webkitAudioContext)();
  inputSampleRate = audioContext.sampleRate || 48000;
  const source = audioContext.createMediaStreamSource(mediaStream);
  processor = audioContext.createScriptProcessor(4096, 1, 1);
  source.connect(processor);
  processor.connect(audioContext.destination);

  if (!ws || ws.readyState !== WebSocket.OPEN) {
    ws = new WebSocket(WS_URL);
    ws.onopen = () => {
      ws.send(JSON.stringify({ type: "start", language: "en" }));
      setStatus("Recording...");
    };
    ws.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data);
        if (data.type === "result") {
          sttText.textContent = data.stt_text || "";
          aiText.textContent = data.ai_text || "";
          if (data.audio_b64) {
            const bytes = atob(data.audio_b64);
            const buf = new Uint8Array(bytes.length);
            for (let i = 0; i < bytes.length; i++) {
              buf[i] = bytes.charCodeAt(i);
            }
            const blob = new Blob([buf], { type: data.audio_mime || "audio/wav" });
            ttsAudio.src = URL.createObjectURL(blob);
          }
          setStatus("Done.");
        }
      } catch (e) {
        setStatus("Bad WS message");
      }
    };
    ws.onclose = () => {
      setStatus("WS closed");
    };
  } else {
    ws.send(JSON.stringify({ type: "start", language: "en" }));
  }

  processor.onaudioprocess = (e) => {
    if (!recording || !ws || ws.readyState !== WebSocket.OPEN) return;
    const input = e.inputBuffer.getChannelData(0);
    const downsampled = downsampleBuffer(input, inputSampleRate, TARGET_SAMPLE_RATE);
    const pcm16 = new Int16Array(downsampled.length);
    for (let i = 0; i < downsampled.length; i++) {
      let s = Math.max(-1, Math.min(1, downsampled[i]));
      pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    ws.send(pcm16.buffer);
  };

  recording = true;
  recordBtn.disabled = true;
  stopBtn.disabled = false;
  sendBtn.disabled = true;
  setStatus("Recording...");
}

async function stopRecording() {
  if (!recording) return;
  recording = false;
  stopBtn.disabled = true;
  recordBtn.disabled = false;

  if (processor) {
    processor.disconnect();
    processor = null;
  }
  if (audioContext) {
    await audioContext.close();
    audioContext = null;
  }
  if (mediaStream) {
    mediaStream.getTracks().forEach((t) => t.stop());
    mediaStream = null;
  }

  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "stop" }));
  }
  setStatus("Stopped. Processing...");
}

recordBtn.addEventListener("click", async () => {
  try {
    await startRecording();
  } catch (err) {
    setStatus(`Mic error: ${err.message}`);
  }
});

stopBtn.addEventListener("click", async () => {
  try {
    await stopRecording();
  } catch (err) {
    setStatus(`Stop error: ${err.message}`);
  }
});

sendBtn.addEventListener("click", async () => {
  setStatus("WebSocket mode. Use Start/Stop.");
});
