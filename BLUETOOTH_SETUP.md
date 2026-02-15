# ESP32 Bluetooth Speaker Setup Guide (MAP140)

## Overview
ESP32 Vi Assistant has been modified to use **Bluetooth A2DP** instead of the physical I2S amplifier (MAX98357A). Audio will now stream directly to a Bluetooth speaker named **MAP140**.

## What Changed

### Hardware Changes
- **Removed**: MAX98357A I2S amplifier (GPIO23, GPIO25, GPIO19)
- **Added**: Bluetooth connection to Bluetooth speaker "MAP140"
- **Kept**: INMP441 microphone (I2S RX) on GPIO26, GPIO25, GPIO34

### Software Changes
- Removed I2S TX driver setup
- Added BluetoothA2DP Sink support
- Audio playback functions now use Bluetooth instead of I2S
- Old `writeMonoToI2S()` → New `writeMonoToBluetooth()`

## Required Libraries

Add the following libraries to your Arduino IDE:

```
1. BluetoothA2DPSink - Search for and install from Library Manager
   - Author: Phil Schatzmann
```

### Installation Steps (Arduino IDE):
1. Go to **Sketch** → **Include Library** → **Manage Libraries**
2. Search for "BluetoothA2DPSink"
3. Install the latest version
4. Restart Arduino IDE

## Bluetooth Speaker Setup (MAP140)

### Pairing Steps:
1. **Power on the MAX140 Bluetooth speaker**
   - Speaker should enter pairing mode (usually indicated by blinking LED)
   
2. **Flash the ESP32 with the updated firmware**
   - The ESP32 will automatically:
     - Initialize Bluetooth
     - Scan for available devices
     - Attempt to connect to "MAP140"
   
3. **Monitor Serial Output**
   - Open Serial Monitor (115200 baud)
   - Look for messages like:
     ```
     [bt] initializing Bluetooth A2DP...
     [bt] connecting to MAP140...
     [bt] connection state: connected
     ```

4. **If connection fails:**
   - Check that MAP140 is powered on and in pairing mode
   - Verify the speaker name is exactly "MAP140"
   - Restart both ESP32 and speaker
   - Check for Bluetooth conflicts with other devices

## Audio Flow

```
Inference (Server)
    ↓
WAV Audio (Base64)
    ↓
ESP32 WebSocket
    ↓
Base64 Decode → Parse WAV
    ↓
Convert Mono to Stereo
    ↓
Bluetooth A2DP Sink
    ↓
MAP140 Speaker
    ↓
🔊 Sound Output
```

## Code Changes Summary

### Key Functions Modified:

1. **setupBluetooth()** (NEW)
   - Initializes A2DP Sink
   - Sets up connection callbacks
   - Connects to MAP140

2. **writeMonoToBluetooth()** (REPLACED writeMonoToI2S)
   - Converts mono PCM to stereo
   - Sends audio via Bluetooth A2DP
   - Includes delay to prevent buffer overflow

3. **playPcmChunkNow()** (UPDATED)
   - Uses new Bluetooth function
   - Checks Bluetooth connection status

4. **serviceAudioPlayback()** (UPDATED)
   - Now depends on `btConnected` flag
   - Pauses playback if Bluetooth disconnects

## Configuration

### Bluetooth Device Name
To change the target speaker name, edit line in viesp.ino:
```cpp
const char* BT_SPEAKER_NAME = "MAP140";
```

Change "MAP140" to your speaker name if different.

## Troubleshooting

### Bluetooth Won't Connect
- **Issue**: "connection state: disconnected"
- **Solution**: 
  - Power cycle both ESP32 and speaker
  - Verify speaker is in pairing mode
  - Check speaker name spelling exactly matches

### No Audio Output
- **Issue**: Connected but no sound
- **Solution**:
  - Check speaker volume level
  - Verify server is sending audio data
  - Monitor serial output for "[tts]" messages

### Audio Cuts Out
- **Issue**: Playback stops mid-sentence
- **Solution**:
  - Reduce WiFi interference
  - Move ESP32 closer to speaker
  - Check WiFi signal quality

### Memory Issues (No PSRAM)
Since ESP32 has no PSRAM:
- Chunk size is limited to 1024 bytes
- Audio playback uses buffering
- Bluetooth buffer is managed internally

## Benefits of Bluetooth Solution

✅ **No physical amplifier needed** - Remove MAX98357A circuitry  
✅ **Wireless audio** - Better portability  
✅ **Less power consumption** - No I2S amplifier overhead  
✅ **More flexible** - Easy to switch speakers  
✅ **No PSRAM required** - Works on basic ESP32

## Original I2S Setup (Reference)

If you need to revert to I2S amplifier:
- Uncomment `setupI2STx()` call in setup()
- Change `writeMonoToBluetooth()` back to `writeMonoToI2S()`
- Change `playPcmChunkNow()` to use I2S functions
- Restore GPIO23, GPIO25, GPIO19 connections to MAX98357A

## Specifications

- **Bluetooth Version**: A2DP (Audio Distribution Profile)
- **Sample Rate**: 16000 Hz (16 kHz)
- **Bit Depth**: 16-bit
- **Channels**: Stereo (converted from mono)
- **Target Speaker**: MAP140 (or compatible Bluetooth speaker)

---

**Last Updated**: 2026-02-16  
**Compatible**: ESP32 without PSRAM
