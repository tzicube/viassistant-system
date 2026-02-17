// OK - ESP32S3 NO-PSRAM: MIC + OLED(U8g2 Face Anim + Speaking) + WS (Mic Record + NO Text)
// Server sends audio directly to Bluetooth speaker
// ESP32: Mic recording + OLED face only (no text mode)
// Flow: Idle -> (BTN start) ListeningActive -> (BTN stop) Thinking -> (tts_start/BIN) Speaking -> (tts_end) Idle

#include <WiFi.h>

// Reduce static WS buffers on low-DRAM boards.
#define WEBSOCKETS_MAX_DATA_SIZE   1024
#define WEBSOCKETS_MAX_HEADER_SIZE 256
#include <WebSocketsClient.h>

#include "driver/i2s.h"
#include "esp_system.h"

#include <Wire.h>
#include <U8g2lib.h>
#include <math.h>

// =========================
// WIFI
// =========================
const char* WIFI_SSID = "ZiCube";
const char* WIFI_PASS = "Duy31122005@";

// =========================
// SERVER (WebSocket)
// =========================
const char* WS_HOST = "192.168.1.112";
const int   WS_PORT = 8000;
const char* WS_PATH = "/ws/viassistant/";

// =========================
// PINS
// =========================
// I2S MIC (INMP441)
const int I2S_BCLK = 26;
const int I2S_WS   = 25;
const int I2S_DIN  = 34;

// BUTTON
const int BTN_PIN = 14;        // Record/Stop toggle

// OLED I2C
const int OLED_SDA = 21;
const int OLED_SCL = 22;

// =========================
// AUDIO CONFIG
// =========================
const int SAMPLE_RATE = 16000; // MIC input rate + server PCM rate

// =========================
// OLED (U8g2)
// =========================
U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE);

// =========================
// STATE
// =========================
bool recording = false;
unsigned long lastBtnMs = 0;
const unsigned long DEBOUNCE_MS = 200;
int lastBtnState = HIGH;

WebSocketsClient ws;
bool wsConnected = false;

// OLED mode control
enum OledMode { OLED_FACE, OLED_THINKING, OLED_SPEAKING, OLED_SERVER_DOWN };
OledMode oledMode = OLED_SERVER_DOWN;

// Speaking control (server-driven)
bool speaking = false;
unsigned long speakUntilMs = 0;
const unsigned long SPEAK_TIMEOUT_MS = 12000; // fallback safety

// After stop: server will send {"type":"result","audio_stream":true...} then tts_start + BIN stream + tts_end
bool awaitingAudio = false;

// =========================
// ANIMATION TICK (for blink + mouth cadence)
// =========================
int tick = 0;
unsigned long lastUpdate = 0; // tick timebase
const unsigned long TICK_MS = 200;

unsigned long lastFaceFrameMs = 0;
const unsigned long FACE_FRAME_MS = 30;

// =================================================
// UTIL
// =================================================
const char* resetReasonToString(esp_reset_reason_t reason) {
  switch (reason) {
    case ESP_RST_UNKNOWN: return "unknown";
    case ESP_RST_POWERON: return "poweron";
    case ESP_RST_EXT: return "ext";
    case ESP_RST_SW: return "software";
    case ESP_RST_PANIC: return "panic";
    case ESP_RST_INT_WDT: return "int_wdt";
    case ESP_RST_TASK_WDT: return "task_wdt";
    case ESP_RST_WDT: return "other_wdt";
    case ESP_RST_DEEPSLEEP: return "deepsleep";
    case ESP_RST_BROWNOUT: return "brownout";
    case ESP_RST_SDIO: return "sdio";
    default: return "n/a";
  }
}

String payloadToString(const uint8_t* payload, size_t length) {
  if (!payload || length == 0) return String();
  String out;
  out.reserve(length);
  for (size_t i = 0; i < length; i++) out += (char)payload[i];
  return out;
}

// JSON string extractor (simple; works for quoted strings)
bool extractJsonString(const String& body, const String& key, String& out) {
  String needle = "\"" + key + "\"";
  int idx = body.indexOf(needle);
  if (idx < 0) return false;

  int colon = body.indexOf(':', idx + needle.length());
  if (colon < 0) return false;

  int q1 = body.indexOf('\"', colon + 1);
  if (q1 < 0) return false;

  int q2 = q1 + 1;
  bool escaped = false;
  while (q2 < body.length()) {
    char c = body[q2];
    if (c == '\\' && !escaped) { escaped = true; q2++; continue; }
    if (c == '\"' && !escaped) break;
    escaped = false;
    q2++;
  }
  if (q2 >= body.length()) return false;

  out = body.substring(q1 + 1, q2);
  out.replace("\\n", "\n");
  out.replace("\\\"", "\"");
  out.replace("\\\\", "\\");
  return true;
}

static inline String toLowerCopy(String s) {
  s.toLowerCase();
  return s;
}

// Keyword matcher for server events
bool isSpeakStartTag(const String& tagLower) {
  return tagLower.indexOf("speak_start") >= 0 ||
         tagLower.indexOf("tts_start")   >= 0 ||
         tagLower.indexOf("audio_start") >= 0 ||
         tagLower.indexOf("play_start")  >= 0 ||
         tagLower.indexOf("speaking")    >= 0;
}

bool isSpeakEndTag(const String& tagLower) {
  return tagLower.indexOf("speak_end") >= 0 ||
         tagLower.indexOf("tts_end")   >= 0 ||
         tagLower.indexOf("audio_end") >= 0 ||
         tagLower.indexOf("play_end")  >= 0 ||
         tagLower.indexOf("done")      >= 0 ||
         tagLower.indexOf("final")     >= 0 ||
         tagLower.indexOf("end")       >= 0;
}

// =================================================
// TICK UPDATE
// =================================================
void updateTick(unsigned long now) {
  if (now - lastUpdate >= TICK_MS) {
    lastUpdate = now;
    tick++;
  }
}

// =================================================
// BLINK LOGIC
// =================================================
bool isBlinking() {
  int blinkCycle = tick % 20;
  return (blinkCycle == 0 || blinkCycle == 1);
}

// =================================================
// EYES – NORMAL
// =================================================
void drawEyesSmooth(int offsetX, int offsetY) {
  u8g2.drawRBox(22 + offsetX, 16 + offsetY, 28, 32, 13);
  u8g2.drawRBox(78 + offsetX, 16 + offsetY, 28, 32, 13);
}

void drawEyesBlink(int offsetX, int offsetY) {
  u8g2.drawRBox(24 + offsetX, 33 + offsetY, 24, 4, 2);
  u8g2.drawRBox(80 + offsetX, 33 + offsetY, 24, 4, 2);
}

// =================================================
// LISTEN BARS (3 cột sóng 2 bên mắt)
// =================================================
void drawListeningBars(unsigned long now, int offsetX, int offsetY) {
  const int leftEyeX  = 22 + offsetX;
  const int rightEyeX = 78 + offsetX;
  const int eyeY      = 16 + offsetY;
  const int eyeW      = 28;
  const int eyeH      = 32;

  int phase = (int)((now / 120UL) % 6UL);
  int level = (phase <= 3) ? phase : (6 - phase);

  int midY = eyeY + (eyeH / 2);
  int leftBaseX  = leftEyeX - 8;
  int rightBaseX = rightEyeX + eyeW + 6;

  for (int i = 0; i < 3; i++) {
    int amp = (i <= level) ? (i + 1) * 4 : 2;
    int hh  = 4 + amp;
    int yy  = midY - (hh / 2);

    u8g2.drawBox(leftBaseX - (i * 4),  yy, 2, hh);
    u8g2.drawBox(rightBaseX + (i * 4), yy, 2, hh);
  }
}

// =================================================
// MOUTH – LISTENING (smile)
// =================================================
void drawMouthSmileSmooth() {
  int cx = 64;
  int cy = 47;
  int radius = 12;

  for (int layer = 0; layer < 5; layer++) {
    int prevX = 0;
    int prevY = 0;
    bool firstPoint = true;

    for (int angle = 20; angle <= 160; angle += 2) {
      float rad = angle * 3.1416f / 180.0f;
      int x = cx + (int)(radius * cos(rad));
      int y = cy + (int)(radius * sin(rad)) + layer;

      if (!firstPoint) u8g2.drawLine(prevX, prevY, x, y);
      prevX = x;
      prevY = y;
      firstPoint = false;
    }
  }
}

// =================================================
// MOUTH – THINKING (flat)
// =================================================
void drawMouthFlat() {
  u8g2.drawRBox(52, 54, 24, 6, 3);
}

// =================================================
// MOUTH – SPEAKING
// =================================================
void drawMouthTalkSmooth(bool open) {
  if (open) u8g2.drawRBox(48, 50, 32, 14, 5);
  else      u8g2.drawRBox(50, 54, 28, 6, 3);
}

// =================================================
// UI DRAW: FACE idle
// =================================================
void drawListening() {
  int eyeMove = (tick % 8 < 4) ? -2 : 2;

  u8g2.clearBuffer();
  if (isBlinking()) drawEyesBlink(eyeMove, 0);
  else              drawEyesSmooth(eyeMove, 0);

  drawMouthSmileSmooth();
  u8g2.sendBuffer();
}

// =================================================
// UI DRAW: RECORDING (LISTENING_ACTIVE)
// =================================================
void drawListeningActive(unsigned long now) {
  u8g2.clearBuffer();

  if (isBlinking()) drawEyesBlink(0, 0);
  else              drawEyesSmooth(0, 0);

  // mouth small
  u8g2.drawRBox(56, 54, 16, 5, 2);

  // bars
  drawListeningBars(now, 0, 0);

  u8g2.sendBuffer();
}

// =================================================
// UI DRAW: THINKING
// =================================================
void drawThinking() {
  u8g2.clearBuffer();

  if (isBlinking()) drawEyesBlink(0, -4);
  else              drawEyesSmooth(0, -4);

  drawMouthFlat();

  int d = tick % 3;
  if (d >= 0) u8g2.drawDisc(54, 10, 2);
  if (d >= 1) u8g2.drawDisc(64, 8, 2);
  if (d >= 2) u8g2.drawDisc(74, 10, 2);

  u8g2.sendBuffer();
}

// =================================================
// UI DRAW: SPEAKING
// =================================================
void drawSpeaking() {
  bool open = (tick % 2) == 0;
  int eyeMove = (tick % 8 < 4) ? -2 : 2;

  u8g2.clearBuffer();

  if (isBlinking()) drawEyesBlink(eyeMove, 0);
  else              drawEyesSmooth(eyeMove, 0);

  drawMouthTalkSmooth(open);
  u8g2.sendBuffer();
}

// =================================================
// UI DRAW: SERVER DOWN
// =================================================
void drawServerDown() {
  u8g2.clearBuffer();
  u8g2.drawRBox(22, 32, 28, 6, 3);
  u8g2.drawRBox(78, 32, 28, 6, 3);
  u8g2.sendBuffer();
}

// =================================================
// MODE SETTERS
// =================================================
void setListeningUi() { oledMode = OLED_FACE;     lastFaceFrameMs = 0; }
void setThinkingUi()  { oledMode = OLED_THINKING; lastFaceFrameMs = 0; }

void setSpeakingUi(unsigned long now) {
  speaking = true;
  speakUntilMs = now + SPEAK_TIMEOUT_MS;
  oledMode = OLED_SPEAKING;
  lastFaceFrameMs = 0;
}

void stopSpeakingUi() {
  speaking = false;
  oledMode = OLED_FACE;
  lastFaceFrameMs = 0;
}

void setServerUnavailableUi() {
  oledMode = OLED_SERVER_DOWN;
  speaking = false;
  awaitingAudio = false;
  lastFaceFrameMs = 0;
  drawServerDown();
}

// =========================
// I2S MIC RX ONLY (low DMA)
// =========================
void setupI2SRx() {
  i2s_config_t i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,

    // reduce DMA usage
    .dma_buf_count = 4,
    .dma_buf_len = 256,

    .use_apll = false,
    .tx_desc_auto_clear = false,
    .fixed_mclk = 0
  };

  i2s_pin_config_t pin_config = {
    .bck_io_num = I2S_BCLK,
    .ws_io_num = I2S_WS,
    .data_out_num = -1,
    .data_in_num = I2S_DIN
  };

  i2s_driver_install(I2S_NUM_0, &i2s_config, 0, NULL);
  i2s_set_pin(I2S_NUM_0, &pin_config);
  i2s_zero_dma_buffer(I2S_NUM_0);
}

// =========================
// WS handling
// =========================
void handleWsText(const String& body) {
  unsigned long now = millis();

  // If recording, ignore speak signals (listening bars have priority)
  if (recording) return;

  // Get tag from multiple keys
  String tag, tmp;
  if (extractJsonString(body, "type", tmp)) tag = tmp;
  else if (extractJsonString(body, "event", tmp)) tag = tmp;
  else if (extractJsonString(body, "status", tmp)) tag = tmp;
  else if (extractJsonString(body, "action", tmp)) tag = tmp;
  else if (extractJsonString(body, "state", tmp)) tag = tmp;

  String tagLower = toLowerCopy(tag);

  // 1) result: server says it will stream audio
  if (tagLower == "result") {
    awaitingAudio = true;
    // keep THINKING (already set after stop)
    return;
  }

  // 2) tts_start: start speaking
  if (tagLower == "tts_start" || isSpeakStartTag(tagLower)) {
    awaitingAudio = false;
    setSpeakingUi(now);
    return;
  }

  // 3) tts_end: stop speaking
  if (tagLower == "tts_end" || isSpeakEndTag(tagLower)) {
    awaitingAudio = false;
    stopSpeakingUi();
    return;
  }

  // 4) fallback audio_b64: if we're still thinking, allow speaking briefly (optional)
  String audioB64;
  if (extractJsonString(body, "audio_b64", audioB64) && audioB64.length() > 0) {
    // If server sends fallback after stream, this may come after tts_end; harmless.
    if (oledMode == OLED_THINKING || awaitingAudio) {
      awaitingAudio = false;
      setSpeakingUi(now);
    } else if (oledMode == OLED_SPEAKING) {
      speakUntilMs = now + SPEAK_TIMEOUT_MS;
    }
    return;
  }

  // 5) Any other TEXT while speaking: extend timeout so it doesn't drop early
  if (oledMode == OLED_SPEAKING) {
    speakUntilMs = now + SPEAK_TIMEOUT_MS;
  }

  (void)body;
}

void webSocketEvent(WStype_t type, uint8_t* payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED:
      wsConnected = true;
      Serial.printf("[ws] connected -> ws://%s:%d%s\n", WS_HOST, WS_PORT, WS_PATH);
      oledMode = OLED_FACE;
      speaking = false;
      awaitingAudio = false;
      lastFaceFrameMs = 0;
      break;

    case WStype_DISCONNECTED:
      wsConnected = false;
      recording = false;
      speaking = false;
      awaitingAudio = false;
      if (payload && length) {
        String reason = payloadToString(payload, length);
        Serial.printf("[ws] disconnected: %s\n", reason.c_str());
      } else {
        Serial.println("[ws] disconnected");
      }
      setServerUnavailableUi();
      break;

    case WStype_TEXT: {
      String msg = payloadToString(payload, length);
      handleWsText(msg);
      break;
    }

    case WStype_BIN: {
      // Server streams PCM bytes_data here.
      // If we are not recording, treat BIN as "speaking in progress"
      if (!recording) {
        unsigned long now = millis();

        // If we were thinking/awaiting audio, switch to speaking when first BIN arrives
        if (oledMode == OLED_THINKING || awaitingAudio) {
          awaitingAudio = false;
          setSpeakingUi(now);
        }

        // Extend speak timeout while audio is streaming
        if (oledMode == OLED_SPEAKING) {
          speakUntilMs = now + SPEAK_TIMEOUT_MS;
        }
      }
      break;
    }

    case WStype_ERROR:
      wsConnected = false;
      recording = false;
      speaking = false;
      awaitingAudio = false;
      if (payload && length) {
        String err = payloadToString(payload, length);
        Serial.printf("[ws] error: %s\n", err.c_str());
      } else {
        Serial.println("[ws] error");
      }
      setServerUnavailableUi();
      break;

    default:
      break;
  }
}

// =========================
// SETUP / LOOP
// =========================
void setup() {
  Serial.begin(115200);
  delay(200);

  esp_reset_reason_t resetReason = esp_reset_reason();
  Serial.printf("[boot] reset_reason=%d (%s)\n", (int)resetReason, resetReasonToString(resetReason));
  Serial.printf("[mem] heap=%u psram=%u psramFree=%u\n",
                (unsigned)ESP.getFreeHeap(),
                (unsigned)ESP.getPsramSize(),
                (unsigned)ESP.getFreePsram());

  pinMode(BTN_PIN, INPUT_PULLUP);

  // OLED I2C
  Wire.begin(OLED_SDA, OLED_SCL);
  u8g2.begin();

  // Start with server-down face until connected
  setServerUnavailableUi();

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) delay(200);
  Serial.printf("[wifi] connected ip=%s rssi=%d\n",
                WiFi.localIP().toString().c_str(), WiFi.RSSI());

  // MIC RX
  setupI2SRx();

  // WS
  String wsHeaders = String("Origin: http://") + WS_HOST + ":" + String(WS_PORT);
  ws.setExtraHeaders(wsHeaders.c_str());
  ws.begin(WS_HOST, WS_PORT, WS_PATH, "");
  ws.onEvent(webSocketEvent);
  ws.setReconnectInterval(2000);
  ws.enableHeartbeat(30000, 5000, 3);

  Serial.printf("[ws] connecting -> ws://%s:%d%s free_heap=%u\n",
                WS_HOST, WS_PORT, WS_PATH, (unsigned)ESP.getFreeHeap());
}

void loop() {
  unsigned long now = millis();
  ws.loop();

  // tick for animations
  updateTick(now);

  // Speaking timeout fallback
  if (oledMode == OLED_SPEAKING && speaking) {
    if ((long)(now - speakUntilMs) >= 0) {
      stopSpeakingUi();
    }
  }

  if (wsConnected) {
    // Button - Record Toggle
    int btn = digitalRead(BTN_PIN);
    if (lastBtnState == HIGH && btn == LOW && (now - lastBtnMs) > DEBOUNCE_MS) {
      lastBtnMs = now;
      recording = !recording;

      if (recording) {
        // recording: listening bars have priority, cancel speaking
        speaking = false;
        awaitingAudio = false;
        oledMode = OLED_FACE;
        lastFaceFrameMs = 0;
        ws.sendTXT("{\"type\":\"start\",\"language\":\"en\",\"client\":\"esp32\"}");
      } else {
        // stop -> thinking, and wait for audio result/tts
        awaitingAudio = true;
        setThinkingUi();
        ws.sendTXT("{\"type\":\"stop\"}");
      }
    }
    lastBtnState = btn;

    // MIC -> WS BIN (PCM16 16k mono)
    if (recording) {
      int32_t samples[256];
      size_t bytesRead = 0;
      i2s_read(I2S_NUM_0, samples, sizeof(samples), &bytesRead, portMAX_DELAY);
      size_t n = bytesRead / sizeof(int32_t);

      static uint8_t outBuf[512];
      size_t outIdx = 0;

      for (size_t i = 0; i < n; i++) {
        int32_t s = samples[i] >> 14; // 32->16
        int16_t s16 = (int16_t)s;
        outBuf[outIdx++] = (uint8_t)(s16 & 0xff);
        outBuf[outIdx++] = (uint8_t)((s16 >> 8) & 0xff);

        if (outIdx >= sizeof(outBuf)) {
          ws.sendBIN(outBuf, outIdx);
          outIdx = 0;
        }
      }
      if (outIdx > 0) ws.sendBIN(outBuf, outIdx);
    }

  } else {
    recording = false;
    speaking = false;
    awaitingAudio = false;
    if (oledMode != OLED_SERVER_DOWN) setServerUnavailableUi();
    lastBtnState = digitalRead(BTN_PIN);
  }

  // OLED render loop
  if (wsConnected) {
    if (now - lastFaceFrameMs >= FACE_FRAME_MS) {
      lastFaceFrameMs = now;

      if (oledMode == OLED_THINKING) {
        drawThinking();
      } else if (oledMode == OLED_SPEAKING) {
        drawSpeaking();
      } else if (oledMode == OLED_FACE) {
        if (recording) drawListeningActive(now);
        else           drawListening();
      } else {
        drawServerDown();
      }
    }
  }

  // Let WiFi tasks run
  delay(1);
}
