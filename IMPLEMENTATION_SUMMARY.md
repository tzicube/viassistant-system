# ESP32 Bluetooth Integration - Implementation Summary

## 📋 Overview
The ViAssistant ESP32 firmware has been successfully modified to support **Bluetooth A2DP audio output** instead of the I2S amplifier (MAX98357A). This enables wireless audio streaming to the MAP140 Bluetooth speaker.

## ✅ Changes Made

### 1. **Code Modifications** (viesp.ino)

#### Header Files
```cpp
✅ Added: #include "BluetoothA2DPSink.h"
```

#### Pin Configuration
```cpp
❌ Removed: I2S TX pins (GPIO23, GPIO25, GPIO19)
✅ Added: BT_SPEAKER_NAME = "MAP140"
```

#### Global Variables
```cpp
✅ Added: BluetoothA2DPSink a2dp_sink;
✅ Added: bool btConnected = false;
```

#### Bluetooth Functions
```cpp
✅ New:    setupBluetooth()                    // Initialize Bluetooth A2DP
✅ New:    avrc_connection_state_changed()    // Handle connection events
✅ New:    avrc_audio_state_changed()         // Handle audio state events
```

#### Audio Playback Functions
```cpp
❌ Removed: setupI2STx()                       // I2S TX driver setup
❌ Removed: writeMonoToI2S()                   // I2S audio transmission
✅ New:    writeMonoToBluetooth()              // Bluetooth audio transmission
✅ Updated: playPcmChunkNow()                  // Uses Bluetooth
✅ Updated: serviceAudioPlayback()             // Uses Bluetooth + btConnected check
```

#### Setup & Loop
```cpp
✅ Updated: setup()  - Calls setupBluetooth() instead of setupI2STx()
✅ Checked: loop()   - serviceAudioPlayback() already handles Bluetooth status
```

### 2. **Documentation Files**

#### Created Files
- ✅ **BLUETOOTH_SETUP.md** - Complete setup and troubleshooting guide
- ✅ **IMPLEMENTATION_SUMMARY.md** - This file

#### Updated Files
- ✅ **readme.md** - Replaced I2S amplifier info with Bluetooth speaker info

## 🔧 Technical Details

### Audio Processing Pipeline

```
Server (TTS Response)
    ↓
Audio Data (Base64 + WAV)
    ↓
ESP32 WebSocket Client
    ↓
Base64 Decoding
    ↓
WAV Parsing (Extract PCM)
    ↓
Mono PCM (16-bit, 16kHz)
    ↓
Stereo Conversion (L/R channels)
    ↓
Bluetooth A2DP Write
    ↓
MAP140 Speaker
    ↓
🔊 Sound Output
```

### Key Functions Explained

#### `setupBluetooth()`
- Initializes A2DP Sink driver
- Registers connection state callbacks
- Initiates connection to MAP140
- Runs automatically in setup()

#### `writeMonoToBluetooth()`
- **Input**: 16-bit mono PCM data (16kHz)
- **Process**: 
  1. Converts mono to stereo (duplicate to L/R channels)
  2. Sends via `a2dp_sink.write()`
  3. Includes micro-delays to prevent buffer overflow
- **Chunk Size**: 1024 bytes per write
- **Checks**: `btConnected` flag before transmission

#### `serviceAudioPlayback()`
- Called in main loop to stream queued audio
- Processes audio in 512-byte chunks
- Pauses if Bluetooth disconnects
- Auto-stops when playback finishes

## 📚 Required Libraries

### Arduino IDE Setup
1. Open Library Manager: **Sketch** → **Include Library** → **Manage Libraries**
2. Search: "BluetoothA2DPSink"
3. Install by: Phil Schatzmann
4. Restart Arduino IDE

### Alternative (Manual Installation)
```bash
cd ~/Documents/Arduino/libraries
git clone https://github.com/pschatzmann/ESP32-A2DP.git
```

## 🔌 Hardware Changes

### Before (I2S Amplifier)
```
ESP32 (GPIO23, GPIO25, GPIO19) 
    → MAX98357A (I2S Amplifier)
    → Physical Speaker (3.5mm/4Ω jack)
```

### After (Bluetooth)
```
ESP32 (Bluetooth Module - Built-in)
    → MAP140 Wireless Speaker
    → 🔊 Wireless Audio (no cables)
```

### GPIO Status

| GPIO | Function | Before | After |
|------|----------|--------|-------|
| 23   | I2S DOUT | Used   | Free  |
| 25   | I2S WS   | Shared | MIC Only |
| 19   | I2S BCLK | Used   | Free  |
| 26   | I2S BCLK | MIC    | MIC   |
| 34   | I2S DIN  | MIC    | MIC   |
| 33   | BUTTON   | Button | Button|
| 21   | I2C SDA  | OLED   | OLED  |
| 22   | I2C SCL  | OLED   | OLED  |

## 🚀 Quick Start

1. **Install Required Library**
   ```
   BluetoothA2DPSink (by Phil Schatzmann)
   ```

2. **Flash Updated Firmware**
   ```
   Upload viesp.ino to ESP32
   ```

3. **Power On MAP140 Speaker**
   ```
   Speaker enters pairing mode automatically
   ```

4. **Monitor Connection**
   ```
   Open Serial Monitor (115200 baud)
   Look for: "[bt] connection state: connected"
   ```

5. **Test**
   ```
   Press button to start recording
   Speak a command
   Audio response plays on speaker
   ```

## ⚙️ Configuration Options

### Bluetooth Device Name
**File**: `viesp.ino`, **Line**: ~34
```cpp
const char* BT_SPEAKER_NAME = "MAP140";  // Change to your speaker name
```

### Audio Sample Rate
**File**: `viesp.ino`, **Line**: ~45
```cpp
const int SAMPLE_RATE = 16000;  // 16 kHz (Matches TTS output)
```

### Chunk Size
**File**: `viesp.ino`, **writeMonoToBluetooth()** function
```cpp
const size_t chunk = 1024;  // Adjust if buffer issues occur
```

## 🐛 Troubleshooting

### Connection Issues
```
[bt] connection state: disconnected
```
**Solution**: 
- Restart ESP32
- Power cycle MAP140
- Check speaker name spelling

### No Audio Output
```
[tts] start
[tts] end chunks=5 bytes=2048
(but no sound)
```
**Solution**:
- Verify speaker volume
- Check Bluetooth connection status
- Restart both devices

### Memory/Buffer Issues
```
Audio cuts out or crashes
```
**Solution**:
- Reduce chunk size: `const size_t chunk = 512;`
- Increase delay: `vTaskDelay(pdMS_TO_TICKS(2));`
- Get PSRAM version of ESP32 (optional)

## 📊 Memory Footprint

| Component | RAM Used | PSRAM |
|-----------|----------|-------|
| Bluetooth A2DP | ~60KB | None |
| WAV Buffer | Variable | None |
| Audio Chunk Buffer | ~4KB | None |
| WebSocket | ~20KB | None |
| **Total** | **~150+KB** | **Not Required** |

✅ **Compatible with ESP32 without PSRAM**

## 🔄 Reverting to I2S Speaker

If you need to go back to MAX98357A setup:

1. **Restore I2S TX Setup**
   ```cpp
   void setupI2STx() {
     // Original code from backup
   }
   ```

2. **Restore I2S TX Pins**
   ```cpp
   const int I2S_SPK_BCLK = 25;
   const int I2S_SPK_WS   = 19;
   const int I2S_SPK_DOUT = 23;
   ```

3. **Revert Audio Functions**
   - Replace `writeMonoToBluetooth()` with `writeMonoToI2S()`
   - Update `playPcmChunkNow()` to use I2S
   - Update `serviceAudioPlayback()` to use I2S

4. **Update Setup**
   ```cpp
   setupI2STx();  // Instead of setupBluetooth();
   ```

## 📞 Support

For issues:
1. Check **BLUETOOTH_SETUP.md** for detailed troubleshooting
2. Monitor **Serial Output** (115200 baud) for debug messages
3. Verify **library installation** in Arduino IDE
4. Check **speaker power** and **pairing mode**

## 📝 Changelog

### Version 2.0 (Current)
- ✅ Bluetooth A2DP support
- ✅ MAP140 speaker integration
- ✅ Removed I2S amplifier code
- ✅ No PSRAM required
- ✅ Wireless audio streaming

### Version 1.0 (Previous)
- I2S MAX98357A amplifier
- Physical audio jack connection
- Required GPIO23, GPIO25, GPIO19

---

**Implementation Date**: February 16, 2026  
**Firmware Version**: 2.0  
**Compatible Hardware**: ESP32 (without PSRAM)  
**Target Speaker**: MAP140 (or compatible Bluetooth A2DP speaker)
