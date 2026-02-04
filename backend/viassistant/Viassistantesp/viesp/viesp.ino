// ViAssistant main ESP (MIC + OLED + button)
// - Press button: start recording
// - Press again: stop, upload WAV to server
// - Display AI text on OLED

#include <WiFi.h>
#include <WebSocketsClient.h>
#include "driver/i2s.h"

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
const char* WS_HOST = "192.168.1.103"; // TODO: set your backend IP
const int WS_PORT = 8000;
const char* WS_PATH = "/ws/viassistant/";

// =========================
// PINS (from readme)
// =========================
// I2S MIC (INMP441)
const int I2S_BCLK = 26;
const int I2S_WS = 25;
const int I2S_DIN = 34;

// BUTTON
const int BTN_PIN = 33;

// OLED (SSD1306)
const int OLED_SDA = 21;
const int OLED_SCL = 22;

// =========================
// AUDIO CONFIG
// =========================
const int SAMPLE_RATE = 16000;
const int BITS_PER_SAMPLE = 16;
const int CHANNELS = 1;
const int MAX_SECONDS = 6; // keep short for RAM

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

// =========================
// UTILS
// =========================
void oledShow(const String& line1, const String& line2 = "") {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);
  display.println(line1);
  if (line2.length() > 0) {
    display.println(line2);
  }
  display.display();
}

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
  int q1 = body.indexOf("\"", idx + needle.length());
  q1 = body.indexOf("\"", q1 + 1);
  int q2 = body.indexOf("\"", q1 + 1);
  if (q1 < 0 || q2 <= q1) return false;
  out = body.substring(q1 + 1, q2);
  return true;
}

void handleWsText(const String& body) {
  String aiText;
  String audioB64;
  if (extractJsonString(body, "ai_text", aiText)) {
    oledShow("AI:", aiText);
  }
  if (extractJsonString(body, "audio_b64", audioB64)) {
    // Audio received (not played yet)
  }
}

void webSocketEvent(WStype_t type, uint8_t* payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED:
      oledShow("WS", "Connected");
      break;
    case WStype_DISCONNECTED:
      oledShow("WS", "Disconnected");
      break;
    case WStype_TEXT: {
      String msg = String((char*)payload).substring(0, length);
      handleWsText(msg);
      break;
    }
    default:
      break;
  }
}

void setup() {
  Serial.begin(115200);
  delay(200);

  pinMode(BTN_PIN, INPUT_PULLUP);

  Wire.begin(OLED_SDA, OLED_SCL);
  display.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  oledShow("Mic OFF");

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  oledShow("WiFi...", "Connecting");
  while (WiFi.status() != WL_CONNECTED) {
    delay(300);
  }
  oledShow("WiFi OK", WiFi.localIP().toString());

  setupI2SRx();

  ws.begin(WS_HOST, WS_PORT, WS_PATH);
  ws.onEvent(webSocketEvent);
  ws.setReconnectInterval(2000);
}

void loop() {
  int btn = digitalRead(BTN_PIN);
  unsigned long now = millis();

  if (lastBtnState == HIGH && btn == LOW && (now - lastBtnMs) > DEBOUNCE_MS) {
    lastBtnMs = now;
    recording = !recording;
    if (recording) {
      oledShow("Mic ON", "Recording...");
      ws.sendTXT("{\"type\":\"start\",\"language\":\"en\"}");
    } else {
      oledShow("Mic OFF", "Processing...");
      ws.sendTXT("{\"type\":\"stop\"}");
    }
  }
  lastBtnState = btn;

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
    if (outIdx > 0) {
      ws.sendBIN(outBuf, outIdx);
    }
  }

  ws.loop();
}
