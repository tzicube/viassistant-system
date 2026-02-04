#include <WiFi.h>
#include <WebServer.h>

// =========================
// CONFIG WIFI (anh sửa 2 dòng này)
// =========================
const char* WIFI_SSID = "ZiCube";
const char* WIFI_PASS = "Duy31122005@";

// HTTP server port 80
WebServer server(80);

// GPIO mapping
const int PIN_LIVING = 27;
const int PIN_KITCHEN = 26;
const int PIN_BED = 25;

int _room_to_pin(const String& room) {
  if (room == "living") return PIN_LIVING;
  if (room == "kitchen") return PIN_KITCHEN;
  if (room == "bed") return PIN_BED;
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

void handleStatus() {
  int living = digitalRead(PIN_LIVING);
  int kitchen = digitalRead(PIN_KITCHEN);
  int bed = digitalRead(PIN_BED);
  String resp = "living=" + String(living) + " kitchen=" + String(kitchen) + " bed=" + String(bed);
  server.send(200, "text/plain", resp);
}

void handleRoot() {
  String msg = "ViAssistant ESP32 is online\n";
  msg += "Try: /ping\n";
  server.send(200, "text/plain", msg);
}

void setup() {
  Serial.begin(115200);
  delay(200);

  Serial.println("\n[BOOT] ViAssistant ESP32");

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  Serial.print("[WIFI] Connecting");
  while (WiFi.status() != WL_CONNECTED) {
    delay(300);
    Serial.print(".");
  }
  Serial.println("\n[WIFI] Connected!");

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

  server.begin();
  Serial.println("[HTTP] Server started on port 80");
  Serial.println("[TEST] Open browser: http://<IP_ESP>/ping");

  pinMode(PIN_LIVING, OUTPUT);
  pinMode(PIN_KITCHEN, OUTPUT);
  pinMode(PIN_BED, OUTPUT);
  digitalWrite(PIN_LIVING, LOW);
  digitalWrite(PIN_KITCHEN, LOW);
  digitalWrite(PIN_BED, LOW);
}

void loop() {
  server.handleClient();
}
