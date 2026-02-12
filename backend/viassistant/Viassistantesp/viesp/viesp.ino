// OK - ESP32S3 NO-PSRAM: MIC + OLED + WS + Bluetooth A2DP (MAP140)
// Receive server: PCM16 mono 16k via BIN chunk -> FIFO -> Bluetooth A2DP
// Remove I2S speaker output completely.
// NOTE: No PSRAM => must keep RAM small.

#include <WiFi.h>

// Reduce static WS buffers on low-DRAM boards.
#define WEBSOCKETS_MAX_DATA_SIZE   1024
#define WEBSOCKETS_MAX_HEADER_SIZE 256
#include <WebSocketsClient.h>

#include "driver/i2s.h"
#include "esp_system.h"

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// ===== Bluetooth A2DP (Classic) =====
#include "BluetoothA2DPSource.h"
#include "esp_bt.h"
#include "esp_bt_main.h"

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
const int BTN_PIN = 14;

// OLED (SSD1306)
const int OLED_SDA = 21;
const int OLED_SCL = 22;

// =========================
// AUDIO CONFIG
// =========================
const int SAMPLE_RATE = 16000; // MIC input rate + server PCM rate

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

// FIX: avoid name conflict with esp32-hal-bt.h: bool btStarted();
bool a2dpStarted = false;
unsigned long a2dpStartAtMs = 0;   // deferred start time

String lastAiText = "";

// track server TTS
bool ttsStreamActive = false;
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
int leftEyeX  = 45;
int rightEyeX = 80;
int eyeY      = 16;
int eyeWidth  = 25;
int eyeHeight = 30;

int targetOffsetX = 0;
int targetOffsetY = 0;
int moveSpeed = 5;

int gazeDir = 0;
unsigned long moveTime = 0;

int blinkState = 0;                // 0 open, 1 closed
int blinkDelayMs = 4000;
unsigned long lastBlinkTime = 0;

unsigned long lastFaceFrameMs = 0;
const unsigned long FACE_FRAME_MS = 30;

int GAZE_SCALE = 2;

const int8_t GAZE_8[8][2] = {
  {  0, -7 }, {  5, -5 }, {  9,  0 }, {  5,  5 },
  {  0,  7 }, { -5,  5 }, { -9,  0 }, { -5, -5 }
};

// =========================
// Bluetooth A2DP -> MAP140 (stream from FIFO)
// =========================
BluetoothA2DPSource a2dp;
static const char* BT_SPK_NAME = "MAP140";
static constexpr uint8_t BT_VOL = 90;
static constexpr int BT_SR = 44100;

// NO-PSRAM => keep FIFO small
static constexpr size_t BT_FIFO_SAMPLES_DRAM = 3000;  // try 2000 if still unstable

static int16_t* btFifo = nullptr;
static size_t btFifoSamples = 0;
static volatile size_t btW = 0;
static volatile size_t btR = 0;
static portMUX_TYPE btMux = portMUX_INITIALIZER_UNLOCKED;

static uint32_t rs_acc = 0;  // 16k -> 44.1k accumulator

static inline void btResetFifo() {
  portENTER_CRITICAL(&btMux);
  btW = btR = 0;
  rs_acc = 0;
  portEXIT_CRITICAL(&btMux);
}

static inline void btPush_unsafe(int16_t s) {
  btFifo[btW] = s;
  btW = (btW + 1) % btFifoSamples;
  if (btW == btR) btR = (btR + 1) % btFifoSamples;
}

static inline bool btPop_unsafe(int16_t& s) {
  if (btR == btW) return false;
  s = btFifo[btR];
  btR = (btR + 1) % btFifoSamples;
  return true;
}

static void pushPcm16kToBtFifo(const uint8_t* data, size_t len) {
  if (!btFifo || btFifoSamples == 0 || !data || len < 2) return;
  len &= ~((size_t)1);

  portENTER_CRITICAL(&btMux);
  for (size_t i = 0; i < len; i += 2) {
    int16_t s16 = (int16_t)((uint16_t)data[i] | ((uint16_t)data[i + 1] << 8));
    rs_acc += (uint32_t)BT_SR;
    while (rs_acc >= (uint32_t)SAMPLE_RATE) {
      rs_acc -= (uint32_t)SAMPLE_RATE;
      btPush_unsafe(s16);
    }
  }
  portEXIT_CRITICAL(&btMux);
}

// A2DP callback: fill stereo 16-bit interleaved @44100.
static int32_t a2dp_cb(uint8_t* data, int32_t len) {
  if (!data || len <= 0 || !btFifo || btFifoSamples == 0) return 0;

  int32_t usable = (len / 4) * 4;
  int16_t* out = (int16_t*)data;
  int32_t frames = usable / 4;

  portENTER_CRITICAL(&btMux);
  for (int32_t f = 0; f < frames; f++) {
    int16_t s = 0;
    (void)btPop_unsafe(s);
    out[f * 2 + 0] = s;
    out[f * 2 + 1] = s;
  }
  portEXIT_CRITICAL(&btMux);
  return usable;
}

static void startA2dpIfNeeded() {
  if (a2dpStarted) return;

  // Important: A2DP eats heap. Start only when WS already stable.
  a2dp.set_volume(BT_VOL);
  a2dp.start_raw(BT_SPK_NAME, a2dp_cb);
  a2dpStarted = true;

  Serial.printf("[bt] A2DP started -> %s vol=%u free_heap=%u\n",
                BT_SPK_NAME, BT_VOL, (unsigned)ESP.getFreeHeap());
}

// =========================
// UTIL
// =========================
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

// JSON string extractor (simple)
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

// =========================
// OLED DRAW
// =========================
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
    int hh = 4 + amp;
    int yy = midY - (hh / 2);
    display.fillRect(leftBaseX - (i * 4), yy, 2, hh, SSD1306_WHITE);
    display.fillRect(rightBaseX + (i * 4), yy, 2, hh, SSD1306_WHITE);
  }
}

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

  if (recording) drawListeningAnimation(now, offsetX, offsetY);

  display.display();
}

void drawThinkingEffect(unsigned long now) {
  int dots = (int)((now / 280UL) % 4UL);
  int cx = 64;
  int y = 54;

  for (int i = 0; i < dots; i++) display.fillCircle(cx - 6 + i * 6, y, 1, SSD1306_WHITE);

  int s = (int)((now / 120UL) % 8UL);
  int mx = 64;
  int my = 46;
  const int8_t RING[8][2] = {
    { 0, -6 }, { 4, -4 }, { 6, 0 }, { 4, 4 },
    { 0,  6 }, { -4, 4 }, { -6, 0 }, { -4, -4 }
  };

  for (int i = 0; i < 8; i++) {
    int px = mx + RING[i][0];
    int py = my + RING[i][1];
    if (i == s) display.fillCircle(px, py, 1, SSD1306_WHITE);
    else       display.drawPixel(px, py, SSD1306_WHITE);
  }
}

void thinkingUpdateAndDraw(unsigned long now) {
  updateBlink(now);

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
  drawThinkingEffect(now);
  display.display();
}

void oledShowTextWrapped(const String& text) {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);
  display.println("Vi:");

  const int maxCharsPerLine = 21;
  int start = 0;
  int printedLines = 1;

  while (start < (int)text.length() && printedLines < 8) {
    int end = min((int)text.length(), start + maxCharsPerLine);
    if (end < (int)text.length()) {
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

void setListeningUi() { oledMode = OLED_FACE; textModeUntilMs = 0; lastFaceFrameMs = 0; }
void setThinkingUi()  { oledMode = OLED_THINKING; textModeUntilMs = 0; lastFaceFrameMs = 0; }

void setServerUnavailableUi() {
  oledMode = OLED_SERVER_DOWN;
  textModeUntilMs = 0;

  display.clearDisplay();
  display.fillRect(leftEyeX,  eyeY + eyeHeight / 2 - 2, eyeWidth, 4, SSD1306_WHITE);
  display.fillRect(rightEyeX, eyeY + eyeHeight / 2 - 2, eyeWidth, 4, SSD1306_WHITE);
  display.display();
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
  String aiText;
  String msgType;

  if (oledMode == OLED_THINKING) {
    oledMode = OLED_FACE;
    lastFaceFrameMs = 0;
  }

  if (extractJsonString(body, "type", msgType)) {
    if (msgType == "tts_start") {
      ttsStreamActive = true;
      ttsRxBytes = 0;
      ttsRxChunks = 0;
      btResetFifo();
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
}

void webSocketEvent(WStype_t type, uint8_t* payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED:
      wsConnected = true;
      ttsStreamActive = false;
      Serial.printf("[ws] connected -> ws://%s:%d%s\n", WS_HOST, WS_PORT, WS_PATH);

      // defer A2DP start (avoid peak memory right in handshake)
      if (!a2dpStarted) a2dpStartAtMs = millis() + 1500;

      oledMode = OLED_FACE;
      textModeUntilMs = 0;
      lastFaceFrameMs = 0;
      break;

    case WStype_DISCONNECTED:
      wsConnected = false;
      recording = false;
      ttsStreamActive = false;
      btResetFifo();
      a2dpStartAtMs = 0;

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

    case WStype_BIN:
      if (ttsStreamActive && length > 0) {
        ttsRxChunks++;
        ttsRxBytes += length;
        pushPcm16kToBtFifo(payload, length);
      }
      break;

    case WStype_ERROR:
      wsConnected = false;
      recording = false;
      ttsStreamActive = false;
      btResetFifo();
      a2dpStartAtMs = 0;

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

  Wire.begin(OLED_SDA, OLED_SCL);
  display.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  randomSeed(esp_random());

  oledMode = OLED_FACE;

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) delay(200);
  Serial.printf("[wifi] connected ip=%s rssi=%d\n",
                WiFi.localIP().toString().c_str(), WiFi.RSSI());

  // MIC RX
  setupI2SRx();

  // FIFO DRAM (small)
  btFifo = (int16_t*)malloc(BT_FIFO_SAMPLES_DRAM * sizeof(int16_t));
  btFifoSamples = btFifo ? BT_FIFO_SAMPLES_DRAM : 0;
  Serial.printf("[bt] fifo DRAM=%u samples\n", (unsigned)btFifoSamples);
  btResetFifo();

  // Free BLE RAM (A2DP uses Classic)
  esp_bt_controller_mem_release(ESP_BT_MODE_BLE);

  Serial.printf("[bt] deferred start free_heap=%u\n", (unsigned)ESP.getFreeHeap());

  // WS
  String wsHeaders = String("Origin: http://") + WS_HOST + ":" + String(WS_PORT);
  ws.setExtraHeaders(wsHeaders.c_str());
  ws.begin(WS_HOST, WS_PORT, WS_PATH, "");
  ws.onEvent(webSocketEvent);
  ws.setReconnectInterval(2000);
  ws.enableHeartbeat(30000, 5000, 3);

  Serial.printf("[ws] connecting -> ws://%s:%d%s free_heap=%u\n",
                WS_HOST, WS_PORT, WS_PATH, (unsigned)ESP.getFreeHeap());

  setServerUnavailableUi();
}

void loop() {
  unsigned long now = millis();
  ws.loop();

  // Start A2DP later (NO-PSRAM stabilizer)
  if (wsConnected && !a2dpStarted && a2dpStartAtMs != 0 && (long)(now - a2dpStartAtMs) >= 0) {
    startA2dpIfNeeded();
    a2dpStartAtMs = 0;
  }

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
    ttsStreamActive = false;
    btResetFifo();
    a2dpStartAtMs = 0;
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

  // Let WiFi/BT tasks run
  delay(1);
}
