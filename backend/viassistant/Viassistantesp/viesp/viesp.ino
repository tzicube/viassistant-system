// ViAssistant main ESP (MIC + OLED face + button)
// - Press button: start recording (send start)
// - Press again: stop (send stop)
// - While idle/recording/processing: show FACE animation on OLED
// - When AI text arrives: show wrapped text temporarily, then return to FACE
// - While waiting server reply after stop: show THINKING animation (no text)
// - If audio_b64 arrives: decode WAV + play via I2S AMP

#include <WiFi.h>
#include <WebSocketsClient.h>
#include "driver/i2s.h"
#include "esp_system.h"

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// =========================
// WIFI
// =========================
const char* WIFI_SSID = "ZiCube";
const char* WIFI_PASS = "Duy31122005@";

// =========================
// SERVER (WebSocket)
// =========================
const char* WS_HOST = "192.168.1.103";
const int WS_PORT = 8000;
const char* WS_PATH = "/ws/viassistant/";

// =========================
// PINS
// =========================
// I2S MIC (INMP441)
const int I2S_BCLK = 26;
const int I2S_WS   = 25;
const int I2S_DIN  = 34;

// I2S AMP (MAX98357A)
const int I2S_SPK_BCLK = 25;
const int I2S_SPK_WS   = 19;
const int I2S_SPK_DOUT = 23;

// BUTTON
const int BTN_PIN = 33;

// OLED (SSD1306)
const int OLED_SDA = 21;
const int OLED_SCL = 22;

// =========================
// AUDIO CONFIG
// =========================
const int SAMPLE_RATE = 16000;

// =========================
// OLED
// =========================
#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);

// =========================
// STATE
// =========================
bool recording = false;
unsigned long lastBtnMs = 0;
const unsigned long DEBOUNCE_MS = 200;
int lastBtnState = HIGH;

WebSocketsClient ws;
bool wsConnected = false;

String lastAiText = "";

bool audioPlaying = false;
bool ttsStreamActive = false;
uint8_t* playingWavBuf = nullptr;
const uint8_t* playingPcm = nullptr;
size_t playingPcmLen = 0;
size_t playingPcmOffset = 0;
size_t ttsRxBytes = 0;
size_t ttsRxChunks = 0;

// OLED mode control
enum OledMode { OLED_FACE, OLED_TEXT, OLED_THINKING, OLED_SERVER_DOWN };
OledMode oledMode = OLED_FACE;
unsigned long textModeUntilMs = 0;
const unsigned long TEXT_SHOW_MS = 8000;

// =========================
// FACE
// =========================
// Eye position and size
int leftEyeX  = 45;
int rightEyeX = 80;
int eyeY      = 16;
int eyeWidth  = 25;
int eyeHeight = 30;

// Movement
int targetOffsetX = 0;
int targetOffsetY = 0;
int moveSpeed = 5;

// 8-direction gaze (N, NE, E, SE, S, SW, W, NW)
int gazeDir = 0;
unsigned long moveTime = 0;

// Blink
int blinkState = 0;               // 0 open, 1 closed
int blinkDelayMs = 4000;
unsigned long lastBlinkTime = 0;

// Render cadence
unsigned long lastFaceFrameMs = 0;
const unsigned long FACE_FRAME_MS = 30;

// ====== TUNE: eye travel distance ======
int GAZE_SCALE = 2; // 1 = gần, 2 = xa, 3 = rất xa (anh tăng/giảm ở đây)

// Base direction vectors (small), scale up with GAZE_SCALE
const int8_t GAZE_8[8][2] = {
  {  0, -7 },  // N
  {  5, -5 },  // NE
  {  9,  0 },  // E
  {  5,  5 },  // SE
  {  0,  7 },  // S
  { -5,  5 },  // SW
  { -9,  0 },  // W
  { -5, -5 }   // NW
};

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

void drawEye(int x, int y, int w, int h) {
  display.fillRoundRect(x, y, w, h, 5, SSD1306_WHITE);
}

void drawListeningAnimation(unsigned long now, int offsetX, int offsetY) {
  int phase = (int)((now / 120UL) % 6UL);
  int level = (phase <= 3) ? phase : (6 - phase);

  int midY = eyeY + offsetY + eyeHeight / 2;
  int leftBaseX = leftEyeX + offsetX - 8;
  int rightBaseX = rightEyeX + offsetX + eyeWidth + 6;

  for (int i = 0; i < 3; i++) {
    int amp = (i <= level) ? (i + 1) * 4 : 2;
    int h = 4 + amp;
    int y = midY - (h / 2);
    display.fillRect(leftBaseX - (i * 4), y, 2, h, SSD1306_WHITE);
    display.fillRect(rightBaseX + (i * 4), y, 2, h, SSD1306_WHITE);
  }
}

// Cycle direction (8 hướng)
void advanceGazeDirection() {
  gazeDir = (gazeDir + 1) % 8;
  targetOffsetX = (int)GAZE_8[gazeDir][0] * GAZE_SCALE;
  targetOffsetY = (int)GAZE_8[gazeDir][1] * GAZE_SCALE;
}

void updateBlink(unsigned long now) {
  if (blinkState == 0 && (now - lastBlinkTime > (unsigned long)blinkDelayMs)) {
    blinkState = 1;
    lastBlinkTime = now;
  } else if (blinkState == 1 && (now - lastBlinkTime > 150UL)) {
    blinkState = 0;
    lastBlinkTime = now;
  }
}

void drawEyesWithOffset(int offsetX, int offsetY) {
  if (blinkState == 0) {
    drawEye(leftEyeX + offsetX,  eyeY + offsetY, eyeWidth, eyeHeight);
    drawEye(rightEyeX + offsetX, eyeY + offsetY, eyeWidth, eyeHeight);
  } else {
    display.fillRect(leftEyeX + offsetX,  eyeY + offsetY + eyeHeight / 2 - 2, eyeWidth, 4, SSD1306_WHITE);
    display.fillRect(rightEyeX + offsetX, eyeY + offsetY + eyeHeight / 2 - 2, eyeWidth, 4, SSD1306_WHITE);
  }
}

void faceUpdateAndDraw(unsigned long now) {
  updateBlink(now);

  if (blinkState == 0 && (now - moveTime > (unsigned long)random(900, 1600))) {
    advanceGazeDirection();
    moveTime = now;
  }

  static int offsetX = 0;
  static int offsetY = 0;
  offsetX += (targetOffsetX - offsetX) / moveSpeed;
  offsetY += (targetOffsetY - offsetY) / moveSpeed;

  display.clearDisplay();
  drawEyesWithOffset(offsetX, offsetY);

  if (recording) {
    drawListeningAnimation(now, offsetX, offsetY);
  }

  // NO TEXT in FACE mode
  display.display();
}

// THINKING effect: 3 dots + small spinner (no text)
void drawThinkingEffect(unsigned long now) {
  // 3 dots: . .. ...
  int dots = (int)((now / 280UL) % 4UL); // 0..3
  int cx = 64;
  int y = 54;

  for (int i = 0; i < dots; i++) {
    display.fillCircle(cx - 6 + i * 6, y, 1, SSD1306_WHITE);
  }

  // spinner: 8 points around center
  int s = (int)((now / 120UL) % 8UL);
  int mx = 64;
  int my = 46;
  const int8_t RING[8][2] = {
    { 0, -6 }, { 4, -4 }, { 6, 0 }, { 4, 4 },
    { 0,  6 }, { -4, 4 }, { -6, 0 }, { -4, -4 }
  };

  // draw faint ring points (outline) + one "active" point
  for (int i = 0; i < 8; i++) {
    int px = mx + RING[i][0];
    int py = my + RING[i][1];
    if (i == s) display.fillCircle(px, py, 1, SSD1306_WHITE);
    else       display.drawPixel(px, py, SSD1306_WHITE);
  }
}

void thinkingUpdateAndDraw(unsigned long now) {
  updateBlink(now);

  // thinking: move faster a bit
  if (blinkState == 0 && (now - moveTime > (unsigned long)random(450, 900))) {
    advanceGazeDirection();
    moveTime = now;
  }

  static int offsetX = 0;
  static int offsetY = 0;
  offsetX += (targetOffsetX - offsetX) / moveSpeed;
  offsetY += (targetOffsetY - offsetY) / moveSpeed;

  display.clearDisplay();
  drawEyesWithOffset(offsetX, offsetY);

  // No text, only effects
  drawThinkingEffect(now);

  display.display();
}

// =========================
// OLED TEXT (ONLY "Vi:" shown)
// =========================
void oledShowTextWrapped(const String& text) {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);
  display.println("Vi:");

  const int maxCharsPerLine = 21;
  int start = 0;
  int printedLines = 1;

  while (start < text.length() && printedLines < 8) {
    int end = min((int)text.length(), start + maxCharsPerLine);
    if (end < text.length()) {
      int lastSpace = text.lastIndexOf(' ', end);
      if (lastSpace > start) end = lastSpace;
    }
    String line = text.substring(start, end);
    line.trim();
    display.println(line);
    printedLines++;
    start = end + 1;
  }
  display.display();
}

void setListeningUi() {
  oledMode = OLED_FACE;
  textModeUntilMs = 0;
  lastFaceFrameMs = 0;
}

void setThinkingUi() {
  oledMode = OLED_THINKING;
  textModeUntilMs = 0;
  lastFaceFrameMs = 0;
}

void setServerUnavailableUi() {
  oledMode = OLED_SERVER_DOWN;
  textModeUntilMs = 0;

  // no text. show "closed eyes"
  display.clearDisplay();
  display.fillRect(leftEyeX,  eyeY + eyeHeight / 2 - 2, eyeWidth, 4, SSD1306_WHITE);
  display.fillRect(rightEyeX, eyeY + eyeHeight / 2 - 2, eyeWidth, 4, SSD1306_WHITE);
  display.display();
}

// =========================
// I2S
// =========================
void setupI2SRx() {
  i2s_config_t i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 8,
    .dma_buf_len = 512,
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

void setupI2STx() {
  i2s_config_t i2s_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT, // duplicate mono to L/R
    .communication_format = I2S_COMM_FORMAT_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 8,
    .dma_buf_len = 256,
    .use_apll = false,
    .tx_desc_auto_clear = true,
    .fixed_mclk = 0
  };

  i2s_pin_config_t pin_config = {
    .bck_io_num = I2S_SPK_BCLK,
    .ws_io_num = I2S_SPK_WS,
    .data_out_num = I2S_SPK_DOUT,
    .data_in_num = -1
  };

  esp_err_t err = i2s_driver_install(I2S_NUM_1, &i2s_config, 0, NULL);
  if (err != ESP_OK) {
    Serial.printf("[i2s] tx driver install failed: %d\n", (int)err);
    return;
  }
  err = i2s_set_pin(I2S_NUM_1, &pin_config);
  if (err != ESP_OK) {
    Serial.printf("[i2s] tx set pin failed: %d\n", (int)err);
  }
  i2s_zero_dma_buffer(I2S_NUM_1);
}

// =========================
// Base64 + WAV parse + play
// =========================
int _b64_index(char c) {
  if (c >= 'A' && c <= 'Z') return c - 'A';
  if (c >= 'a' && c <= 'z') return c - 'a' + 26;
  if (c >= '0' && c <= '9') return c - '0' + 52;
  if (c == '+') return 62;
  if (c == '/') return 63;
  return -1;
}

bool decodeBase64(const String& in, uint8_t** outBuf, size_t* outLen) {
  size_t len = in.length();
  if (len == 0) return false;
  size_t pad = 0;
  if (in.endsWith("==")) pad = 2;
  else if (in.endsWith("=")) pad = 1;
  size_t outSize = (len * 3) / 4 - pad;

  uint8_t* buf = (uint8_t*)malloc(outSize);
  if (!buf) return false;

  size_t oi = 0;
  int val = 0, valb = -8;
  for (size_t i = 0; i < len; i++) {
    int c = _b64_index(in[i]);
    if (c < 0) continue;
    val = (val << 6) + c;
    valb += 6;
    if (valb >= 0) {
      buf[oi++] = (uint8_t)((val >> valb) & 0xFF);
      valb -= 8;
      if (oi >= outSize) break;
    }
  }
  *outBuf = buf;
  *outLen = oi;
  return true;
}

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

bool parseWavData(const uint8_t* wav, size_t wavLen, const uint8_t** pcm, size_t* pcmLen) {
  if (!wav || wavLen < 44) return false;
  if (!(wav[0] == 'R' && wav[1] == 'I' && wav[2] == 'F' && wav[3] == 'F')) return false;
  if (!(wav[8] == 'W' && wav[9] == 'A' && wav[10] == 'V' && wav[11] == 'E')) return false;

  size_t i = 12;
  while (i + 8 <= wavLen) {
    uint32_t chunkSize = (uint32_t)wav[i + 4] |
                         ((uint32_t)wav[i + 5] << 8) |
                         ((uint32_t)wav[i + 6] << 16) |
                         ((uint32_t)wav[i + 7] << 24);
    if (wav[i] == 'd' && wav[i + 1] == 'a' && wav[i + 2] == 't' && wav[i + 3] == 'a') {
      size_t dataPos = i + 8;
      if (dataPos + chunkSize > wavLen) return false;
      *pcm = wav + dataPos;
      *pcmLen = chunkSize;
      return true;
    }
    i += 8 + chunkSize + (chunkSize & 1);
  }
  return false;
}

size_t writeMonoToI2S(const uint8_t* pcm, size_t pcmLen, TickType_t timeoutTicks) {
  if (!pcm || pcmLen < 2) return 0;

  const size_t chunk = 512;
  static int16_t stereoBuf[512]; // 256 mono samples -> 512 stereo samples
  size_t offset = 0;

  while (offset < pcmLen) {
    size_t toWrite = min(chunk, pcmLen - offset);
    toWrite &= ~((size_t)1);
    if (toWrite == 0) break;

    size_t monoSamples = toWrite / 2;
    for (size_t i = 0; i < monoSamples; i++) {
      uint16_t lo = pcm[offset + i * 2];
      uint16_t hi = pcm[offset + i * 2 + 1];
      int16_t s = (int16_t)((hi << 8) | lo);
      stereoBuf[i * 2] = s;
      stereoBuf[i * 2 + 1] = s;
    }

    size_t stereoBytes = monoSamples * 4;
    size_t written = 0;
    esp_err_t err = i2s_write(I2S_NUM_1, stereoBuf, stereoBytes, &written, timeoutTicks);
    if (err != ESP_OK || written == 0) break;

    offset += (written / 4) * 2;
    if (written < stereoBytes) break;
  }
  return offset;
}

void stopAudioPlayback() {
  if (playingWavBuf) {
    free(playingWavBuf);
    playingWavBuf = nullptr;
  }
  playingPcm = nullptr;
  playingPcmLen = 0;
  playingPcmOffset = 0;
  audioPlaying = false;
}

bool startAudioPlaybackFromBase64(const String& audioB64) {
  stopAudioPlayback();

  size_t wavLen = 0;
  if (!decodeBase64(audioB64, &playingWavBuf, &wavLen)) return false;

  const uint8_t* pcm = nullptr;
  size_t pcmLen = 0;
  bool ok = parseWavData(playingWavBuf, wavLen, &pcm, &pcmLen);
  if (!ok) {
    stopAudioPlayback();
    return false;
  }

  playingPcm = pcm;
  playingPcmLen = pcmLen;
  playingPcmOffset = 0;
  audioPlaying = true;
  return true;
}

void serviceAudioPlayback() {
  if (!audioPlaying || !playingPcm || playingPcmOffset >= playingPcmLen) return;

  const size_t chunk = 512;
  size_t toWrite = min(chunk, playingPcmLen - playingPcmOffset);
  size_t consumed = writeMonoToI2S(playingPcm + playingPcmOffset, toWrite, pdMS_TO_TICKS(4));
  if (consumed == 0) return;
  playingPcmOffset += consumed;

  if (playingPcmOffset >= playingPcmLen) stopAudioPlayback();
}

void playPcmChunkNow(const uint8_t* data, size_t len) {
  if (!data || len == 0) return;
  size_t offset = 0;
  while (offset < len) {
    size_t consumed = writeMonoToI2S(data + offset, len - offset, pdMS_TO_TICKS(6));
    if (consumed == 0) break;
    offset += consumed;
  }
}

// =========================
// WS handling
// =========================
void handleWsText(const String& body) {
  String aiText;
  String audioB64;
  String msgType;

  // Any WS text during THINKING -> server started responding -> leave thinking
  if (oledMode == OLED_THINKING) {
    oledMode = OLED_FACE;
    lastFaceFrameMs = 0;
  }

  if (extractJsonString(body, "type", msgType)) {
    if (msgType == "tts_start") {
      ttsStreamActive = true;
      ttsRxBytes = 0;
      ttsRxChunks = 0;
      stopAudioPlayback();
      Serial.println("[tts] start");
    } else if (msgType == "tts_end") {
      ttsStreamActive = false;
      Serial.printf("[tts] end chunks=%u bytes=%u\n", (unsigned)ttsRxChunks, (unsigned)ttsRxBytes);
    }
  }

  if (!extractJsonString(body, "ai_text", aiText)) {
    if (!extractJsonString(body, "text", aiText)) {
      extractJsonString(body, "answer", aiText);
    }
  }

  if (aiText.length() > 0) {
    lastAiText = aiText;
    oledMode = OLED_TEXT;
    textModeUntilMs = millis() + TEXT_SHOW_MS;
    oledShowTextWrapped(lastAiText);
  }

  if (extractJsonString(body, "audio_b64", audioB64)) {
    bool ok = startAudioPlaybackFromBase64(audioB64);
    if (ok) serviceAudioPlayback();
  }
}

void webSocketEvent(WStype_t type, uint8_t* payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED:
      wsConnected = true;
      ttsStreamActive = false;
      Serial.println("[ws] connected");
      oledMode = OLED_FACE;
      textModeUntilMs = 0;
      lastFaceFrameMs = 0;
      break;

    case WStype_DISCONNECTED:
      wsConnected = false;
      recording = false;
      ttsStreamActive = false;
      stopAudioPlayback();
      Serial.println("[ws] disconnected");
      setServerUnavailableUi();
      break;

    case WStype_TEXT: {
      String msg = payloadToString(payload, length);
      handleWsText(msg);
      break;
    }

    case WStype_BIN:
      if (ttsStreamActive && length > 0) {
        ttsRxChunks++;
        ttsRxBytes += length;
        playPcmChunkNow(payload, length);
      }
      break;

    case WStype_ERROR:
      wsConnected = false;
      recording = false;
      ttsStreamActive = false;
      stopAudioPlayback();
      Serial.println("[ws] error");
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

  pinMode(BTN_PIN, INPUT_PULLUP);

  Wire.begin(OLED_SDA, OLED_SCL);
  display.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  randomSeed(esp_random());

  oledMode = OLED_FACE;

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) delay(200);

  setupI2SRx();
  setupI2STx();

  ws.begin(WS_HOST, WS_PORT, WS_PATH);
  ws.onEvent(webSocketEvent);
  ws.setReconnectInterval(2000);
  ws.enableHeartbeat(30000, 5000, 3);

  setServerUnavailableUi();
}

void loop() {
  unsigned long now = millis();
  ws.loop();

  if (wsConnected) {
    // Button
    int btn = digitalRead(BTN_PIN);
    if (lastBtnState == HIGH && btn == LOW && (now - lastBtnMs) > DEBOUNCE_MS) {
      lastBtnMs = now;
      recording = !recording;

      if (recording) {
        setListeningUi();
        ws.sendTXT("{\"type\":\"start\",\"language\":\"en\",\"client\":\"esp32\"}");
      } else {
        // stop -> enter THINKING mode until server replies
        setThinkingUi();
        ws.sendTXT("{\"type\":\"stop\"}");
      }
    }
    lastBtnState = btn;

    // Audio streaming MIC -> WS BIN
    if (recording) {
      int32_t samples[256];
      size_t bytesRead = 0;
      i2s_read(I2S_NUM_0, samples, sizeof(samples), &bytesRead, portMAX_DELAY);
      size_t n = bytesRead / sizeof(int32_t);

      static uint8_t outBuf[512];
      size_t outIdx = 0;

      for (size_t i = 0; i < n; i++) {
        int32_t s = samples[i] >> 14; // 32-bit to 16-bit
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

    serviceAudioPlayback();
  } else {
    recording = false;
    ttsStreamActive = false;
    stopAudioPlayback();
    if (oledMode != OLED_SERVER_DOWN) setServerUnavailableUi();
    lastBtnState = digitalRead(BTN_PIN);
  }

  // TEXT timeout -> return to FACE
  if (wsConnected && oledMode == OLED_TEXT) {
    if ((long)(now - textModeUntilMs) >= 0) {
      oledMode = OLED_FACE;
      lastFaceFrameMs = 0;
    }
  }

  // OLED animations
  if (wsConnected && oledMode == OLED_FACE) {
    if (now - lastFaceFrameMs >= FACE_FRAME_MS) {
      lastFaceFrameMs = now;
      faceUpdateAndDraw(now);
    }
  }

  if (wsConnected && oledMode == OLED_THINKING) {
    if (now - lastFaceFrameMs >= FACE_FRAME_MS) {
      lastFaceFrameMs = now;
      thinkingUpdateAndDraw(now);
    }
  }
}
