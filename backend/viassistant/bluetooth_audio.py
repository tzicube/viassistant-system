"""
Bluetooth A2DP audio streaming for speaker (MAP140, etc)
Streams TTS WAV audio directly to Bluetooth speaker
"""

import logging
import platform
import subprocess
import asyncio
import io
import wave
from typing import Optional

logger = logging.getLogger("viassistant.bluetooth")


class BluetoothAudioPlayer:
    """Stream WAV audio to Bluetooth A2DP speaker"""

    def __init__(self, speaker_name: str = "MAP140"):
        self.speaker_name = speaker_name
        self.is_connected = False
        self.system = platform.system()  # "Linux", "Windows", "Darwin"
        self._current_proc: Optional[subprocess.Popen] = None

    async def connect(self) -> bool:
        """Connect to Bluetooth speaker"""
        try:
            if self.system == "Linux":
                return await self._connect_linux()
            elif self.system == "Windows":
                return await self._connect_windows()
            elif self.system == "Darwin":
                return await self._connect_macos()
            else:
                logger.error("[bt] unsupported platform: %s", self.system)
                return False
        except Exception as e:
            logger.error("[bt] connection failed: %s", e)
            return False

    async def _connect_linux(self) -> bool:
        """Connect via bluetoothctl on Linux"""
        try:
            # Get device address
            result = subprocess.run(
                ["bluetoothctl", "devices"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            lines = result.stdout.strip().split("\n")
            mac_addr = None

            for line in lines:
                if self.speaker_name in line:
                    parts = line.split()
                    if len(parts) >= 2:
                        mac_addr = parts[1]
                        break

            if not mac_addr:
                logger.warning("[bt] device not found: %s", self.speaker_name)
                return False

            logger.info("[bt] found device %s: %s", self.speaker_name, mac_addr)

            # Trust device
            subprocess.run(
                ["bluetoothctl", "trust", mac_addr],
                capture_output=True,
                timeout=5,
            )

            # Connect
            result = subprocess.run(
                ["bluetoothctl", "connect", mac_addr],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if "Connection successful" in result.stdout or result.returncode == 0:
                self.is_connected = True
                logger.info("[bt] connected to %s (%s)", self.speaker_name, mac_addr)
                return True
            else:
                logger.error("[bt] connection failed: %s", result.stdout)
                return False

        except subprocess.TimeoutExpired:
            logger.error("[bt] connection timeout")
            return False
        except FileNotFoundError:
            logger.error("[bt] bluetoothctl not found (install bluez-tools)")
            return False
        except Exception as e:
            logger.error("[bt] connection error: %s", e)
            return False

    async def _connect_windows(self) -> bool:
        """Connect on Windows (simplified)"""
        logger.info("[bt] Windows Bluetooth connection requires manual pairing")
        self.is_connected = True
        return True

    async def _connect_macos(self) -> bool:
        """Connect on macOS (simplified)"""
        logger.info("[bt] macOS Bluetooth connection requires manual pairing")
        self.is_connected = True
        return True

    async def play_wav_bytes(self, wav_bytes: bytes) -> bool:
        """
        Stream WAV bytes to Bluetooth speaker
        Uses ffplay or similar audio player
        """
        if not wav_bytes:
            logger.warning("[bt] empty audio data")
            return False

        try:
            if self.system == "Linux":
                return await self._play_linux(wav_bytes)
            elif self.system == "Windows":
                return await self._play_windows(wav_bytes)
            elif self.system == "Darwin":
                return await self._play_macos(wav_bytes)
            else:
                return False
        except Exception as e:
            logger.error("[bt] playback failed: %s", e)
            return False

    async def _play_linux(self, wav_bytes: bytes) -> bool:
        """Play audio on Linux via ffplay/paplay"""
        try:
            # Try paplay first (ALSA)
            proc = subprocess.Popen(
                ["paplay", "--device=" + self.speaker_name],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self._current_proc = proc
            try:
                # Stream data in chunks to allow interruption
                chunk_size = 4096
                for i in range(0, len(wav_bytes), chunk_size):
                    chunk = wav_bytes[i:i+chunk_size]
                    proc.stdin.write(chunk)
                    proc.stdin.flush()
                    # Check if process died
                    if proc.poll() is not None:
                        break
                    # Allow other tasks to run
                    await asyncio.sleep(0.001)
                
                proc.stdin.close()
                # Wait for process to finish with timeout
                await asyncio.wait_for(asyncio.to_thread(proc.wait), timeout=5.0)
                logger.info("[bt] audio played via paplay")
                return True
            finally:
                self._current_proc = None
                if proc.poll() is None:
                    proc.terminate()
        except FileNotFoundError:
            # Fallback to ffplay
            try:
                proc = subprocess.Popen(
                    ["ffplay", "-nodisp", "-autoexit", "-"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                self._current_proc = proc
                try:
                    # Stream data in chunks to allow interruption
                    chunk_size = 4096
                    for i in range(0, len(wav_bytes), chunk_size):
                        chunk = wav_bytes[i:i+chunk_size]
                        proc.stdin.write(chunk)
                        proc.stdin.flush()
                        # Check if process died
                        if proc.poll() is not None:
                            break
                        # Allow other tasks to run
                        await asyncio.sleep(0.001)
                    
                    proc.stdin.close()
                    # Wait for process to finish with timeout
                    await asyncio.wait_for(asyncio.to_thread(proc.wait), timeout=5.0)
                    logger.info("[bt] audio played via ffplay")
                    return True
                finally:
                    self._current_proc = None
                    if proc.poll() is None:
                        proc.terminate()
            except FileNotFoundError:
                logger.error("[bt] no audio player found (install ffmpeg or pulseaudio)")
                return False
        except asyncio.TimeoutError:
            logger.warning("[bt] playback timeout")
            self._current_proc = None
            if proc.poll() is None:
                proc.terminate()
            return False
        except Exception as e:
            self._current_proc = None
            if proc and proc.poll() is None:
                proc.terminate()
            logger.error("[bt] playback error: %s", e)
            return False

    async def _play_windows(self, wav_bytes: bytes) -> bool:
        """Play audio on Windows"""
        try:
            # Write to temp file and use winsound
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(wav_bytes)
                temp_path = f.name

            try:
                import winsound

                await asyncio.to_thread(winsound.PlaySound, temp_path, winsound.SND_FILENAME | winsound.SND_SYNC | winsound.SND_NODEFAULT)
                logger.info("[bt] audio played via winsound")
            except Exception as e:
                logger.warning("[bt] winsound failed (%s), fallback PowerShell SoundPlayer", e)
                ps_cmd = [
                    "powershell",
                    "-Command",
                    "(New-Object Media.SoundPlayer '{0}').PlaySync()".format(temp_path.replace("'", "''")),
                ]
                result = await asyncio.to_thread(subprocess.run, ps_cmd, check=False, creationflags=subprocess.CREATE_NO_WINDOW)
                if result.returncode != 0:
                    logger.error("[bt] PowerShell SoundPlayer rc=%s", result.returncode)
                    return False
            return True
        except Exception as e:
            logger.error("[bt] playback error: %s", e)
            return False

    async def _play_macos(self, wav_bytes: bytes) -> bool:
        """Play audio on macOS"""
        try:
            # Use afplay (built-in)
            proc = subprocess.Popen(
                ["afplay", "-"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self._current_proc = proc
            try:
                # Stream data in chunks to allow interruption
                chunk_size = 4096
                for i in range(0, len(wav_bytes), chunk_size):
                    chunk = wav_bytes[i:i+chunk_size]
                    proc.stdin.write(chunk)
                    proc.stdin.flush()
                    # Check if process died
                    if proc.poll() is not None:
                        break
                    # Allow other tasks to run
                    await asyncio.sleep(0.001)
                
                proc.stdin.close()
                # Wait for process to finish with timeout
                await asyncio.wait_for(asyncio.to_thread(proc.wait), timeout=5.0)
                logger.info("[bt] audio played via afplay")
                return True
            finally:
                self._current_proc = None
                if proc.poll() is None:
                    proc.terminate()
        except FileNotFoundError:
            logger.error("[bt] afplay not found")
            return False
        except asyncio.TimeoutError:
            logger.warning("[bt] playback timeout")
            self._current_proc = None
            if proc.poll() is None:
                proc.terminate()
            return False
        except Exception as e:
            self._current_proc = None
            if proc and proc.poll() is None:
                proc.terminate()
            logger.error("[bt] playback error: %s", e)
            return False

    async def stop_playback(self) -> bool:
        """Best-effort stop of any in-progress playback."""
        try:
            if self.system == "Windows":
                try:
                    import winsound
                    winsound.PlaySound(None, winsound.SND_PURGE)
                except Exception:
                    pass

            proc = self._current_proc
            if proc and proc.poll() is None:
                logger.warning("[bt] stop_playback: terminating audio process...")
                proc.terminate()
                try:
                    await asyncio.to_thread(proc.wait, 1)
                except Exception:
                    pass
                if proc.poll() is None:
                    logger.warning("[bt] stop_playback: killing audio process!")
                    proc.kill()
                logger.warning("[bt] stop_playback: process stopped.")
            else:
                logger.warning("[bt] stop_playback: no active process.")
            self._current_proc = None
            return True
        except Exception as e:
            logger.error("[bt] stop playback failed: %s", e)
            return False

    async def disconnect(self):
        """Disconnect from Bluetooth speaker"""
        if self.system == "Linux":
            try:
                subprocess.run(
                    ["bluetoothctl", "disconnect"],
                    capture_output=True,
                    timeout=5,
                )
            except Exception:
                pass
        self.is_connected = False


# Global instance
_bt_player: Optional[BluetoothAudioPlayer] = None


async def init_bluetooth_speaker(speaker_name: str = "MAP140") -> bool:
    """Initialize Bluetooth speaker connection"""
    global _bt_player
    _bt_player = BluetoothAudioPlayer(speaker_name)
    return await _bt_player.connect()


async def play_tts_audio(wav_bytes: bytes) -> bool:
    """Play TTS audio on Bluetooth speaker"""
    global _bt_player
    if not _bt_player:
        logger.warning("[bt] player not initialized")
        return False
    return await _bt_player.play_wav_bytes(wav_bytes)


async def stop_bluetooth_playback() -> bool:
    """Stop current Bluetooth playback if any (best effort)."""
    global _bt_player
    if not _bt_player:
        return False
    try:
        return await _bt_player.stop_playback()
    except Exception:
        logger.exception("[bt] stop playback failed")
        return False


async def shutdown_bluetooth():
    """Shutdown Bluetooth connection"""
    global _bt_player
    if _bt_player:
        await _bt_player.disconnect()
        _bt_player = None
