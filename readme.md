┌──────────────────────────── MAX98357A (I2S AMP) ────────────────────────────┐
│                                                                              │
│   VIN   → 5V                                                                 │
│   GND   → GND                                                                │
│                                                                              │
│   BCLK  → GPIO18   (I2S BCLK - DÙNG CHUNG với INMP441 SCK)                   │
│   LRC   → GPIO19   (I2S LRCLK/WS - DÙNG CHUNG với INMP441 WS)                │
│   DIN   → GPIO23   (I2S DATA OUT: ESP32S → AMP)                              │
│                                                                              │
│   SD    → 3V3      (ENABLE: kéo lên để AMP chạy)                             │
│   GAIN  → GND      (~9 dB, ổn cho loa 4Ω–2W)                                 │
│                                                                              │
│   SPK+  → LOA (+)                                                            │
│   SPK-  → LOA (-)                                                            │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
┌────────────────────────────── INMP441 (I2S MIC) ────────────────────────────┐
│                                                                              │
│   VDD  → 3V3                                                                 │
│   GND  → GND                                                                │
│                                                                              │
│   SCK  → GPIO26   (I2S BCLK - DÙNG CHUNG với MAX98357A BCLK)                 │
│   WS   → GPIO25   (I2S LRCLK/WS - DÙNG CHUNG với MAX98357A LRC)              │
│   SD   → GPIO34   (MIC DATA IN: MIC → ESP32S)                                │
│                                                                              │
│   L/R  → GND      (chọn kênh)                                                │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
┌──────────────────────────── OLED SSD1306 (I2C) ─────────────────────────────┐
│                                                                              │
│   VCC  → 3V3                                                                 │
│   GND  → GND                                                                │
│   SDA  → GPIO21                                                             │
│   SCL  → GPIO22                                                             │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
┌────────────────────────────── BUTTON (Tact) ────────────────────────────────┐
│                                                                              │
│   1 chân → GPIO33                                                            │
│   1 chân đối diện → GND                                                      │
│   (INPUT_PULLUP: thả HIGH, nhấn LOW)                                         │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
