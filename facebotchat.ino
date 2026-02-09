#include <U8g2lib.h>
#include <Wire.h>
#include <math.h>

// ================= OLED =================
U8G2_SSD1306_128X64_NONAME_F_HW_I2C
u8g2(U8G2_R0, U8X8_PIN_NONE);

// ================= BOT STATE =================
enum BotState {
  LISTENING,
  THINKING,
  SPEAKING,
  SAD,
  ANGRY
};

BotState state = LISTENING;

// ================= ANIMATION =================
int tick = 0;
unsigned long lastUpdate = 0;

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
// EYES – SAD (cụp)
// =================================================
void drawEyesSad(int offsetX, int offsetY) {
  u8g2.drawRBox(22 + offsetX, 20 + offsetY, 28, 22, 8);
  u8g2.drawRBox(78 + offsetX, 20 + offsetY, 28, 22, 8);
}

// =================================================
// EYES – ANGRY
// =================================================
void drawEyesAngry(int offsetX, int offsetY) {
  u8g2.drawTriangle(22 + offsetX, 18 + offsetY,
                    50 + offsetX, 18 + offsetY,
                    50 + offsetX, 40 + offsetY);

  u8g2.drawTriangle(78 + offsetX, 18 + offsetY,
                    106 + offsetX, 18 + offsetY,
                    78 + offsetX, 40 + offsetY);
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
      float rad = angle * 3.1416 / 180.0;
      int x = cx + radius * cos(rad);
      int y = cy + radius * sin(rad) + layer;

      if (!firstPoint) {
        u8g2.drawLine(prevX, prevY, x, y);
      }

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
  if (open) {
    u8g2.drawRBox(48, 50, 32, 14, 5);
  } else {
    u8g2.drawRBox(50, 54, 28, 6, 3);
  }
}

// =================================================
// MOUTH – SAD
// =================================================
void drawMouthSadCurve() {
  int cx = 64;
  int cy = 56;   // hạ thấp xuống
  int radius = 10;

  for (int layer = 0; layer < 4; layer++) {
    int prevX = 0;
    int prevY = 0;
    bool firstPoint = true;

    for (int angle = 200; angle <= 340; angle += 3) {
      float rad = angle * 3.1416 / 180.0;
      int x = cx + radius * cos(rad);
      int y = cy + radius * sin(rad) + layer;

      if (!firstPoint) {
        u8g2.drawLine(prevX, prevY, x, y);
      }

      prevX = x;
      prevY = y;
      firstPoint = false;
    }
  }
}

// =================================================
// MOUTH – ANGRY
// =================================================
void drawMouthAngry() {
  u8g2.drawRBox(52, 54, 24, 6, 2);
}

// =================================================
// STATE: LISTENING
// =================================================
void drawListening() {
  int eyeMove = (tick % 8 < 4) ? -2 : 2;

  u8g2.clearBuffer();

  if (isBlinking())
    drawEyesBlink(eyeMove, 0);
  else
    drawEyesSmooth(eyeMove, 0);

  drawMouthSmileSmooth();
  u8g2.sendBuffer();
}

// =================================================
// STATE: THINKING
// =================================================
void drawThinking() {
  u8g2.clearBuffer();

  if (isBlinking())
    drawEyesBlink(0, -4);
  else
    drawEyesSmooth(0, -4);

  drawMouthFlat();

  int d = tick % 3;
  if (d >= 0) u8g2.drawDisc(54, 10, 2);
  if (d >= 1) u8g2.drawDisc(64, 8, 2);
  if (d >= 2) u8g2.drawDisc(74, 10, 2);

  u8g2.sendBuffer();
}

// =================================================
// STATE: SPEAKING
// =================================================
void drawSpeaking() {
  bool open = tick % 2;

  u8g2.clearBuffer();

  if (isBlinking())
    drawEyesBlink(0, 0);
  else
    drawEyesSmooth(0, 0);

  drawMouthTalkSmooth(open);
  u8g2.sendBuffer();
}


// ================= SETUP =================
void setup() {
  u8g2.begin();
}

// ================= LOOP =================
void loop() {
  if (millis() - lastUpdate > 200) {
    lastUpdate = millis();
    tick++;
  }

  if (tick < 20) state = LISTENING;
  else if (tick < 40) state = THINKING;
  else if (tick < 60) state = SPEAKING;
  else tick = 0;

  switch (state) {
    case LISTENING: drawListening(); break;
    case THINKING:  drawThinking(); break;
    case SPEAKING:  drawSpeaking(); break;
  }
}









