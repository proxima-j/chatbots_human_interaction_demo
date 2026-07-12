# pyright: reportMissingImports=false
import os
import wave
import time
import argparse
import tempfile
import threading

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
from pythonosc import dispatcher
from pythonosc import osc_server
from pythonosc.udp_client import SimpleUDPClient


# ============================================================
# CONFIG
# ============================================================

MODEL_PATH = (
    r"C:\Users\12235\LOPs_Python\stt_models"
    r"\local--Systran--faster-whisper-base"
)

# Use None for the default Windows input device.
# To choose a specific microphone, run:
# python stt_bot_service.py --list-devices
# Then replace None with the device index.
DEVICE_INDEX = None

SAMPLE_RATE = 48000
CHANNELS = 1

# Start safely with CPU.
DEVICE = "cpu"
COMPUTE_TYPE = "int8"


# ============================================================
# OSC NETWORK
# ============================================================

# TouchDesigner sends STT commands to Python here.
LISTEN_IP = "127.0.0.1"
LISTEN_PORT = 9000

# Python sends transcript/status back to TouchDesigner here.
TD_IP = "127.0.0.1"
TD_PORT = 9001

# Python forwards completed transcripts to Bot A here.
BOT_A_IP = "127.0.0.1"
BOT_A_PORT = 9100

# This can be disabled temporarily while testing STT alone.
FORWARD_TRANSCRIPT_TO_BOT_A = True


# ============================================================
# RECORDING SETTINGS
# ============================================================

AUTO_STOP_ON_SILENCE = True
SILENCE_SECONDS = 2.5
SILENCE_RMS_THRESHOLD = 0.002
MIN_RECORD_SECONDS = 0.8

# Optional hard limit so users cannot speak forever.
MAX_RECORD_SECONDS = 20.0

DEBUG_AUDIO_LEVEL = False


# ============================================================
# GLOBAL STATE
# ============================================================

recording = False
audio_chunks: list[np.ndarray] = []
last_level = 0.0

recording_started_at = 0.0
last_voice_time = 0.0

lock = threading.Lock()

td_client = SimpleUDPClient(TD_IP, TD_PORT)
bot_a_client = SimpleUDPClient(BOT_A_IP, BOT_A_PORT)


# ============================================================
# OSC OUTPUT HELPERS
# ============================================================

def send_status(status: str) -> None:
    print(f"[status] {status}")
    td_client.send_message("/stt/status", status)


def send_result(text: str) -> None:
    print(f"[result] {text}")
    td_client.send_message("/stt/result", text)


def send_error(message: str) -> None:
    print(f"[error] {message}")
    td_client.send_message("/stt/error", message)


def send_transcript_to_bot_a(text: str) -> None:
    """
    Forward one completed STT transcript to Bot A.

    TouchDesigner still receives the same transcript through /stt/result.
    Bot A receives the transcript separately through /user/transcript.
    """
    clean_text = text.strip()

    if not FORWARD_TRANSCRIPT_TO_BOT_A or not clean_text:
        return

    print(f"[STT -> Bot A] {clean_text}")
    bot_a_client.send_message("/user/transcript", clean_text)


# ============================================================
# AUDIO CALLBACK
# ============================================================

def audio_callback(indata, frames, time_info, status) -> None:
    global last_level, audio_chunks, recording, last_voice_time

    if status:
        print("[audio status]", status)

    mono = indata[:, 0].copy()
    rms = float(np.sqrt(np.mean(mono * mono))) if mono.size else 0.0
    now = time.time()

    with lock:
        last_level = rms

        if recording:
            audio_chunks.append(mono.copy())

            if rms > SILENCE_RMS_THRESHOLD:
                last_voice_time = now


def level_sender() -> None:
    """Send microphone level to TouchDesigner while recording."""
    while True:
        with lock:
            level = last_level
            is_recording = recording

        if is_recording:
            td_client.send_message("/stt/level", level)

        if DEBUG_AUDIO_LEVEL and is_recording:
            print(f"[level] {level:.6f}")

        time.sleep(0.1)


# ============================================================
# LOAD MODEL
# ============================================================

print("Loading faster-whisper model...")
model = WhisperModel(
    MODEL_PATH,
    device=DEVICE,
    compute_type=COMPUTE_TYPE,
)
print("Model loaded.")


# ============================================================
# TRANSCRIPTION
# ============================================================

def save_wav(audio: np.ndarray, sample_rate: int) -> str:
    audio = np.clip(audio, -1.0, 1.0)
    audio_i16 = (audio * 32767).astype(np.int16)

    tmp = tempfile.NamedTemporaryFile(
        delete=False,
        suffix=".wav",
    )
    wav_path = tmp.name
    tmp.close()

    with wave.open(wav_path, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_i16.tobytes())

    return wav_path


def transcribe_audio(audio: np.ndarray) -> None:
    if audio.size == 0:
        send_result("")
        send_status("ready")
        return

    duration = audio.size / SAMPLE_RATE
    print(f"Recorded duration: {duration:.2f}s")

    if duration < 0.3:
        send_result("")
        send_status("ready")
        return

    wav_path = save_wav(audio, SAMPLE_RATE)

    try:
        segments, info = model.transcribe(
            wav_path,
            language="en",
            vad_filter=True,
            beam_size=3,
        )

        text = "".join(
            segment.text
            for segment in segments
        ).strip()

        # Keep the existing TouchDesigner connection.
        send_result(text)

        # Add Bot A as a second destination.
        send_transcript_to_bot_a(text)

        send_status("ready")

    except Exception as error:
        send_error(str(error))
        send_status("ready")

    finally:
        try:
            os.remove(wav_path)
        except OSError:
            pass


# ============================================================
# RECORDING CONTROL
# ============================================================

def stop_recording_and_transcribe(reason: str = "manual") -> None:
    global recording, audio_chunks

    with lock:
        if not recording:
            return

        recording = False
        chunks = list(audio_chunks)
        audio_chunks = []

    print(f"Recording stopped. Reason: {reason}")
    send_status("transcribing")

    if not chunks:
        send_result("")
        send_status("ready")
        return

    audio = np.concatenate(chunks, axis=0)

    threading.Thread(
        target=transcribe_audio,
        args=(audio,),
        daemon=True,
    ).start()


def osc_start(address, *args) -> None:
    global recording, audio_chunks
    global recording_started_at, last_voice_time

    now = time.time()

    with lock:
        if recording:
            print("Start ignored: already recording.")
            return

        audio_chunks = []
        recording = True
        recording_started_at = now
        last_voice_time = now

    send_status("recording")
    print("Recording started.")


def osc_stop(address, *args) -> None:
    stop_recording_and_transcribe(reason="manual")


def osc_cancel(address, *args) -> None:
    global recording, audio_chunks

    with lock:
        recording = False
        audio_chunks = []

    send_status("ready")
    print("Recording cancelled.")


def osc_ping(address, *args) -> None:
    send_status("ready")
    print("Ping received.")


# ============================================================
# AUTO-STOP MONITOR
# ============================================================

def silence_monitor() -> None:
    while True:
        time.sleep(0.1)

        if not AUTO_STOP_ON_SILENCE:
            continue

        with lock:
            is_recording = recording
            started_at = recording_started_at
            last_voice = last_voice_time

        if not is_recording:
            continue

        now = time.time()
        record_duration = now - started_at
        silence_duration = now - last_voice

        if (
            MAX_RECORD_SECONDS is not None
            and record_duration >= MAX_RECORD_SECONDS
        ):
            stop_recording_and_transcribe(
                reason="max_duration"
            )
            continue

        if (
            record_duration >= MIN_RECORD_SECONDS
            and silence_duration >= SILENCE_SECONDS
        ):
            stop_recording_and_transcribe(
                reason="silence"
            )


# ============================================================
# LOCAL KEYBOARD TEST
# ============================================================

def keyboard_control() -> None:
    print("")
    print("Keyboard test controls:")
    print("  r + Enter = start recording")
    print("  s + Enter = stop and transcribe")
    print("  c + Enter = cancel recording")
    print("  q + Enter = quit")
    print("")

    while True:
        try:
            cmd = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            cmd = "q"

        if cmd == "r":
            osc_start("/keyboard")

        elif cmd == "s":
            osc_stop("/keyboard")

        elif cmd == "c":
            osc_cancel("/keyboard")

        elif cmd == "q":
            print("Exiting.")
            os._exit(0)


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    print("Opening microphone stream...")

    stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="float32",
        device=DEVICE_INDEX,
        callback=audio_callback,
        blocksize=0,
    )

    stream.start()
    print("Microphone stream started.")

    threading.Thread(
        target=level_sender,
        daemon=True,
    ).start()

    threading.Thread(
        target=silence_monitor,
        daemon=True,
    ).start()

    threading.Thread(
        target=keyboard_control,
        daemon=True,
    ).start()

    disp = dispatcher.Dispatcher()
    disp.map("/stt/start", osc_start)
    disp.map("/stt/stop", osc_stop)
    disp.map("/stt/cancel", osc_cancel)
    disp.map("/stt/ping", osc_ping)

    server = osc_server.ThreadingOSCUDPServer(
        (LISTEN_IP, LISTEN_PORT),
        disp,
    )

    print(
        "Listening for TouchDesigner commands on "
        f"{LISTEN_IP}:{LISTEN_PORT}"
    )
    print(
        "Sending transcript/status to TouchDesigner on "
        f"{TD_IP}:{TD_PORT}"
    )
    print(
        "Forwarding completed transcripts to Bot A on "
        f"{BOT_A_IP}:{BOT_A_PORT}"
    )

    send_status("ready")

    try:
        server.serve_forever()

    finally:
        stream.stop()
        stream.close()
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--list-devices",
        action="store_true",
    )

    args = parser.parse_args()

    if args.list_devices:
        print(sd.query_devices())
    else:
        main()
