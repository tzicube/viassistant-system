#include <WiFi.h>
#include <WebServer.h>
#include <DHT.h>

// =========================
// CONFIG WIFI (anh sửa 2 dòng này)
// =========================
const char* WIFI_SSID = "ZiCube";
const char* WIFI_PASS = "Duy31122005@";

// HTTP server port 80
WebServer server(80);
const int LED_WIFI = 2;
// GPIO mapping
const int PIN_LIVING = 27;
const int PIN_KITCHEN = 26;
const int PIN_BED = 25;
const int PIN_BATHROOM = 13;  // D13
const int PIN_GARDEN = 12;    // D12
const int PIN_DHT22 = 33;     // DHT22 DATA
#define DHTTYPE DHT22

DHT dht(PIN_DHT22, DHTTYPE);
const unsigned long DHT_MIN_INTERVAL_MS = 2200;
float lastTempC = NAN;
float lastHumidity = NAN;
unsigned long lastDhtReadMs = 0;

int _room_to_pin(const String& room) {
  if (room == "living") return PIN_LIVING;
  if (room == "kitchen") return PIN_KITCHEN;
  if (room == "bed") return PIN_BED;
  if (room == "bathroom") return PIN_BATHROOM;
  if (room == "garden") return PIN_GARDEN;
  return -1;
}

void handleRelay() {
  String room = server.arg("room");
  String state = server.arg("state");

  int pin = _room_to_pin(room);
  if (pin < 0 || (state != "on" && state != "off")) {
    server.send(400, "text/plain", "bad_payload");
    return;
  }

  digitalWrite(pin, state == "on" ? HIGH : LOW);

  String resp = "ok room=" + room + " state=" + state;
  server.send(200, "text/plain", resp);
}

void handlePing() {
  server.send(200, "text/plain", "pong");
}

bool readDht(float& humidity, float& tempC, bool forceRead = false) {
  unsigned long now = millis();
  if (!forceRead && !isnan(lastHumidity) && !isnan(lastTempC) && (now - lastDhtReadMs) < DHT_MIN_INTERVAL_MS) {
    humidity = lastHumidity;
    tempC = lastTempC;
    return true;
  }

  humidity = dht.readHumidity();
  tempC = dht.readTemperature();
  if (isnan(humidity) || isnan(tempC)) {
    Serial.printf("[DHT] read failed force=%d h=%.2f t=%.2f\n", forceRead ? 1 : 0, humidity, tempC);
    return false;
  }

  lastHumidity = humidity;
  lastTempC = tempC;
  lastDhtReadMs = now;
  Serial.printf("[DHT] ok h=%.1f t=%.1f\n", humidity, tempC);
  return true;
}

void handleStatus() {
  int living = digitalRead(PIN_LIVING);
  int kitchen = digitalRead(PIN_KITCHEN);
  int bed = digitalRead(PIN_BED);
  int bathroom = digitalRead(PIN_BATHROOM);
  int garden = digitalRead(PIN_GARDEN);
  float humidity = NAN;
  float tempC = NAN;
  readDht(humidity, tempC, false);
  String resp = "living=" + String(living)
    + " kitchen=" + String(kitchen)
    + " bed=" + String(bed)
    + " bathroom=" + String(bathroom)
    + " garden=" + String(garden);
  if (!isnan(tempC)) {
    resp += " temp_c=" + String(tempC, 1);
  }
  if (!isnan(humidity)) {
    resp += " humidity=" + String(humidity, 1);
  }
  server.send(200, "text/plain", resp);
}

void handleDht() {
  float humidity = NAN;
  float tempC = NAN;
  if (!readDht(humidity, tempC, true)) {
    delay(DHT_MIN_INTERVAL_MS);
    readDht(humidity, tempC, true);
  }
  if (isnan(humidity) || isnan(tempC)) {
    server.send(500, "application/json", "{\"ok\":false,\"error\":\"dht_read_error\"}");
    return;
  }

  String resp = "{\"ok\":true,\"temperature_c\":"
    + String(tempC, 1)
    + ",\"humidity\":"
    + String(humidity, 1)
    + "}";
  Serial.println("[DHT] /dht => " + resp);
  server.send(200, "application/json", resp);
}

void handleRoot() {
  String msg = "ViAssistant ESP32 is online\n";
  msg += "Try: /ping\n";
  server.send(200, "text/plain", msg);
}

void setup() {
  Serial.begin(115200);
  delay(200);
  pinMode(LED_WIFI, OUTPUT);
  digitalWrite(LED_WIFI, LOW);   // Tắt LED lúc boot

  Serial.println("\n[BOOT] ViAssistant ESP32");

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  Serial.print("[WIFI] Connecting");
  while (WiFi.status() != WL_CONNECTED) {
    delay(300);
    Serial.print(".");
  }
  Serial.println("\n[WIFI] Connected!");
  digitalWrite(LED_WIFI, HIGH);
  IPAddress ip = WiFi.localIP();
  Serial.print("[WIFI] IP: ");
  Serial.println(ip);

  // ===== Base URL in ra đây =====
  Serial.print("[BASE_URL] http://");
  Serial.println(ip);

  // Routes
  server.on("/", handleRoot);
  server.on("/ping", handlePing);
  server.on("/status", HTTP_GET, handleStatus);
  server.on("/relay", HTTP_GET, handleRelay);
  server.on("/dht", HTTP_GET, handleDht);
  server.on("/sensor", HTTP_GET, handleDht);

  server.begin();
  Serial.println("[HTTP] Server started on port 80");
  Serial.println("[TEST] Open browser: http://<IP_ESP>/ping");

  pinMode(PIN_LIVING, OUTPUT);
  pinMode(PIN_KITCHEN, OUTPUT);
  pinMode(PIN_BED, OUTPUT);
  pinMode(PIN_BATHROOM, OUTPUT);
  pinMode(PIN_GARDEN, OUTPUT);
  digitalWrite(PIN_LIVING, LOW);
  digitalWrite(PIN_KITCHEN, LOW);
  digitalWrite(PIN_BED, LOW);
  digitalWrite(PIN_BATHROOM, LOW);
  digitalWrite(PIN_GARDEN, LOW);

  pinMode(PIN_DHT22, INPUT_PULLUP);
  dht.begin();
  delay(2000);
}

void loop() {
  server.handleClient();
}
