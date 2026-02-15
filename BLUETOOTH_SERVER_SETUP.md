# Server Bluetooth Audio Streaming Implementation

## Overview

The server backend now has **Bluetooth A2DP audio streaming** capability to send TTS (Text-to-Speech) audio directly to Bluetooth speakers like MAP140.

```
Server (Django)
    ↓
Generate TTS WAV
    ↓
Bluetooth A2DP Stream
    ↓
MAP140 Speaker 🔊
```

## Architecture

```
┌─────────────────────────────────────┐
│   ESP32 (Mic Record + Text)         │
│   ↓ WebSocket                       │
┌─────────────────────────────────────┐
│   Server (Django Backend)           │
│   • Process STT                     │
│   • Generate TTS (WAV)              │
│   • Stream to Bluetooth A2DP        │──→ 🔊 MAP140 Speaker
└─────────────────────────────────────┘
```

## New Files

### `bluetooth_audio.py`
Main Bluetooth audio module with:
- `BluetoothAudioPlayer` class - manages connection & playback
- `init_bluetooth_speaker()` - connects to speaker on startup
- `play_tts_audio()` - streams WAV audio to speaker
- Cross-platform support: **Linux**, **Windows**, **macOS**

### `apps.py`
Django app configuration that:
- Initializes Bluetooth speaker on server startup
- Uses environment variable: `VI_BLUETOOTH_SPEAKER_NAME` (default: "MAP140")
- Handles connection gracefully (non-blocking)

## Installation

### Linux (Ubuntu/Debian)

```bash
# Install Bluetooth tools
sudo apt-get install bluez bluez-tools pulseaudio-module-bluetooth

# Or for ALSA:
sudo apt-get install alsa-utils pulseaudio

# Install ffmpeg as fallback:
sudo apt-get install ffmpeg
```

### macOS
```bash
# Requires manual Bluetooth pairing in System Preferences
# Uses native afplay command
```

### Windows
```bash
# Uses Windows built-in winsound
# Requires manual Bluetooth pairing in Settings
```

## Setup & Pairing

### Pair your Bluetooth Speaker

**On Linux (with bluetoothctl):**
```bash
# Start Bluetooth manager
sudo bluetoothctl

# Scan for devices
scan on

# Look for your speaker (e.g., "MAP140")
# Then connect and trust it:
connect <MAC_ADDRESS>
trust <MAC_ADDRESS>
exit
```

**On Windows/macOS:**
Use system Bluetooth settings to pair the speaker manually.

### Configure Speaker Name

Set environment variable:
```bash
export VI_BLUETOOTH_SPEAKER_NAME="MAP140"
```

Or in `.env` file:
```
VI_BLUETOOTH_SPEAKER_NAME=MAP140
```

## Modified Files

### `consumers.py`
- Added `play_tts_audio()` calls after TTS generation
- Plays audio on Bluetooth speaker for both ESP32 and other clients
- Error handling (graceful fallback if Bluetooth unavailable)
- Logging for debugging

### `__init__.py`
- Sets default app config to use custom `ViassistantConfig`

## How It Works

1. **Startup**: Server initializes Bluetooth A2DP connection to MAP140
2. **User speaks**: ESP32 captures mic audio, sends text to server
3. **Server processes**: Generates TTS response as WAV bytes
4. **Stream audio**: Plays WAV on Bluetooth speaker **immediately**
5. **Simultaneous**: ESP32 also receives response text for OLED display

## Code Flow

```python
# In consumers.py receive() method
tts_bytes = tts_text_to_wav_bytes(esp_tts_text)  # Generate TTS

# NEW: Play audio on Bluetooth speaker
if tts_bytes:
    await play_tts_audio(tts_bytes)  # Stream to MAP140 🔊

# Also send text to ESP32 for display
await self.send(...)
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VI_BLUETOOTH_SPEAKER_NAME` | `MAP140` | Bluetooth speaker device name |
| `VI_EDGE_TTS_VOICE` | `en-US-JennyNeural` | TTS voice (Edge TTS) |
| `VI_EDGE_TTS_RATE` | `+0%` | TTS speed |
| `VI_EDGE_TTS_VOLUME` | `+0%` | TTS volume |

## Testing

### Check Bluetooth Connection

```bash
# Linux
bluetoothctl devices
bluetoothctl info <MAC_ADDRESS>

# Check audio players available
which paplay  # or
which ffplay  # or
which afplay  # (macOS)
```

### Test TTS Audio

```python
# In Django shell
from viassistant.bluetooth_audio import play_tts_audio
from viassistant.voice_pipeline import tts_text_to_wav_bytes

import asyncio

# Generate test audio
wav_bytes = tts_text_to_wav_bytes("Hello, this is a test")

# Play on speaker
asyncio.run(play_tts_audio(wav_bytes))
```

## Troubleshooting

### Audio not playing
1. Check Bluetooth connection: `bluetoothctl devices` (Linux)
2. Verify speaker name matches `VI_BLUETOOTH_SPEAKER_NAME`
3. Check speaker volume level
4. Look at Django logs: `[bt]` tag

### Connection failed
```
"no audio player found (install ffmpeg or pulseaudio)"
```
→ Install missing audio tools (see Installation above)

### Linux: Device not found
→ Pair device first using `bluetoothctl`
→ Check speaker is powered on
→ Make sure device name in config matches: `bluetoothctl devices`

### Windows/macOS: No connection
→ Pair manually in System Bluetooth settings
→ Device must be visible to system

## Fallback Behavior

If Bluetooth is unavailable:
- ❌ Audio won't play on speaker
- ✅ Server still works normally
- ✅ Text still sent to ESP32 (OLED display)
- ⚠️ Warning logged but server continues

## Architecture Benefits

✅ **Real-time audio** - No ESP32 limitations  
✅ **Server-side processing** - Full TTS control  
✅ **Wireless audio** - Bluetooth freedom  
✅ **Instant playback** - No buffering on device  
✅ **Better quality** - Server TTS engines  

## Future Improvements

- [ ] A2DP sink support (receive audio from Bluetooth devices)
- [ ] Volume control via WebSocket
- [ ] Multiple speaker support
- [ ] Audio queue management
- [ ] Disconnect/reconnect handling
- [ ] Bluetooth device discovery UI

## API Reference

### `BluetoothAudioPlayer`

```python
player = BluetoothAudioPlayer(speaker_name="MAP140")
await player.connect()           # Connect to speaker
await player.play_wav_bytes(wav) # Stream audio
await player.disconnect()        # Cleanup
```

### Module Functions

```python
# Initialize (called automatically on app startup)
await init_bluetooth_speaker("MAP140")

# Play audio anywhere
await play_tts_audio(wav_bytes)

# Cleanup on shutdown
await shutdown_bluetooth()
```

---

**Status**: ✅ Ready to use  
**Last Updated**: 2026-02-16  
**Platform Support**: Linux ✅ | Windows ✅ | macOS ✅
