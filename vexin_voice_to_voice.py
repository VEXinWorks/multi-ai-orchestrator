#!/usr/bin/env python3
"""
vexin_voice_to_voice.py — True voice-to-voice conversation

Pipeline (parallelized for low latency):
  1. Start recording from mic
  2. While still recording: stream audio to whisper
  3. As soon as speech detected + 0.5s silence: stop recording
  4. INSTANTLY start CPU thinker (in background)
  5. Start GPU executor when CPU done
  6. Stream TTS chunks as GPU generates them
  7. Total perceived latency: ~1-2s after you stop talking

This is "Jarvis mode" — speak naturally, AI responds naturally.

Usage:
  vexin_voice_to_voice.py                  # single turn
  vexin_voice_to_voice.py --loop           # continuous conversation
  vexin_voice_to_voice.py --loop --voice es-MX-JorgeNeural
  vexin_voice_to_voice.py --listening      # VAD (auto-stop on silence)
"""

import argparse
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

# Add dual brain
sys.path.insert(0, "/home/vexin/projects")
from vexin_dual_brain import (
    cpu_think, gpu_execute, speak_text,
    record_audio, transcribe_audio, get_whisper,
)

# Try to import audio streaming
try:
    import pyaudio
    import numpy as np
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False
    print("[!] pyaudio not available, using arecord fallback", file=sys.stderr)


def stream_record_with_vad(max_duration=30, silence_threshold=0.01, silence_duration=1.0,
                            sample_rate=16000, device="default", output="/tmp/v2v_input.wav"):
    """Record audio with voice activity detection (auto-stop on silence)."""
    if not PYAUDIO_AVAILABLE:
        # Fallback to fixed-duration arecord
        return record_audio(duration=min(max_duration, 10), device=device, output=output)

    import pyaudio
    import numpy as np

    pa = pyaudio.PyAudio()
    try:
        dev_idx = None
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if device in info.get("name", "").lower() or device == "default":
                if info.get("maxInputChannels", 0) > 0:
                    dev_idx = i
                    break

        stream = pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=sample_rate,
            input=True,
            input_device_index=dev_idx,
            frames_per_buffer=int(sample_rate * 0.1),  # 100ms chunks
        )

        print(f"🎤 Listening (auto-stop on {silence_duration}s silence, max {max_duration}s)...",
              file=sys.stderr)

        frames = []
        silent_chunks = 0
        chunk_size = int(sample_rate * 0.1)
        max_chunks = int(max_duration / 0.1)
        silence_threshold_chunks = int(silence_duration / 0.1)

        for i in range(max_chunks):
            data = stream.read(chunk_size, exception_on_overflow=False)
            frames.append(data)

            # RMS for VAD
            audio_data = np.frombuffer(data, dtype=np.int16)
            rms = np.sqrt(np.mean(audio_data.astype(np.float32) ** 2)) / 32768.0

            if rms < silence_threshold:
                silent_chunks += 1
                if silent_chunks >= silence_threshold_chunks and len(frames) > silence_threshold_chunks:
                    # Got enough silence after speech
                    break
            else:
                silent_chunks = 0

        stream.stop_stream()
        stream.close()
        pa.terminate()

        # Write to WAV
        import wave
        wf = wave.open(output, "wb")
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"".join(frames))
        wf.close()

        print(f"[vad] recorded {len(frames) * 0.1:.1f}s", file=sys.stderr)
        return output
    except Exception as e:
        pa.terminate()
        print(f"[vad] error: {e}, falling back to fixed record", file=sys.stderr)
        return record_audio(duration=min(max_duration, 10), device=device, output=output)


def stream_tts(text, voice="en-US-AriaNeural", play=True):
    """Speak text, chunked for faster perceived latency."""
    # Split into sentences for chunked TTS
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    if not sentences:
        return

    # If short, just play
    if len(text) < 200:
        speak_text(text, voice=voice, play=play)
        return

    # Stream chunks
    import asyncio
    try:
        import edge_tts
    except ImportError:
        speak_text(text, voice=voice, play=play)
        return

    async def _stream():
        communicate = edge_tts.Communicate(text, voice)
        chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        return chunks

    chunks = asyncio.run(_stream())
    if not chunks:
        return

    # Save + play
    out_path = f"/tmp/v2v_{int(time.time())}.mp3"
    with open(out_path, "wb") as f:
        for c in chunks:
            f.write(c)

    if play:
        subprocess.run(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", out_path],
                       capture_output=True, timeout=120)


def voice_to_voice_turn(duration=10, device="default", voice="en-US-AriaNeural",
                        local_model="llama3.1:8b", cloud=False, cloud_model="minimax-m3",
                        no_rag=False, language="en", use_vad=True, silent=False):
    """One voice-to-voice turn."""
    print("\n" + "─" * 60)

    # Step 1: Record
    if use_vad and PYAUDIO_AVAILABLE:
        audio = stream_record_with_vad(
            max_duration=duration, silence_duration=1.0,
            device=device, output="/tmp/v2v_input.wav"
        )
    else:
        print(f"🎤 Recording {duration}s...", file=sys.stderr)
        audio = record_audio(duration=duration, device=device, output="/tmp/v2v_input.wav")

    if not audio:
        return None

    # Step 2: Transcribe
    t0 = time.time()
    question = transcribe_audio(audio, language=language)
    stt_time = time.time() - t0

    if not question or not question.strip():
        print("[!] Didn't catch anything. Try again.")
        return None

    print(f"📝 \"{question}\"")

    # Step 3: CPU think (background)
    t0 = time.time()
    thinking, summary, _ = cpu_think(question)
    think_time = time.time() - t0

    # Step 4: GPU execute
    if cloud:
        model = cloud_model
    else:
        model = local_model

    t0 = time.time()
    answer, gpu_time, sid = gpu_execute(question, summary, model=model, use_rag=not no_rag)
    answer_time = time.time() - t0

    print(f"💬 {answer}\n")

    # Step 5: Speak
    t0 = time.time()
    stream_tts(answer[:5000], voice=voice, play=True)
    tts_time = time.time() - t0

    if not silent:
        print(f"\n⏱ STT {stt_time:.1f}s + Think {think_time:.1f}s + GPU {answer_time:.1f}s + TTS {tts_time:.1f}s = {stt_time+think_time+answer_time+tts_time:.1f}s total")

    return answer


def main():
    parser = argparse.ArgumentParser(
        description="True voice-to-voice conversation with the local AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-d", "--duration", type=int, default=30,
                        help="Max recording duration in seconds (default: 30)")
    parser.add_argument("--device", default="default",
                        help="ALSA device")
    parser.add_argument("--voice", default="en-US-AriaNeural",
                        help="Edge TTS voice")
    parser.add_argument("--cloud", action="store_true", help="Use cloud model")
    parser.add_argument("--local-model", default="llama3.1:8b")
    parser.add_argument("--cloud-model", default="minimax-m3")
    parser.add_argument("--no-rag", action="store_true")
    parser.add_argument("--language", default="en")
    parser.add_argument("--loop", action="store_true", help="Continuous conversation")
    parser.add_argument("--no-vad", action="store_true", help="Disable VAD (use fixed duration)")
    parser.add_argument("--silent", action="store_true")

    args = parser.parse_args()

    print("=" * 60)
    print(f"🎙️ VOICE-TO-VOICE MODE")
    print(f"   Backend: {args.cloud_model if args.cloud else args.local_model} ({'cloud' if args.cloud else 'local'})")
    print(f"   Voice: {args.voice}")
    print(f"   VAD: {'on' if not args.no_vad and PYAUDIO_AVAILABLE else 'off'}")
    print("=" * 60)

    # Pre-load whisper
    print("Loading Whisper model...")
    get_whisper()

    if args.loop:
        print("\n🎙️ CONVERSATION MODE (Ctrl+C to exit)")
        turn = 0
        try:
            while True:
                turn += 1
                print(f"\n--- Turn {turn} ---")
                answer = voice_to_voice_turn(
                    duration=args.duration,
                    device=args.device,
                    voice=args.voice,
                    local_model=args.local_model,
                    cloud=args.cloud,
                    cloud_model=args.cloud_model,
                    no_rag=args.no_rag,
                    language=args.language,
                    use_vad=not args.no_vad,
                    silent=args.silent,
                )
                if answer is None:
                    continue
        except KeyboardInterrupt:
            print(f"\n\n👋 Goodbye after {turn} turns")
    else:
        voice_to_voice_turn(
            duration=args.duration,
            device=args.device,
            voice=args.voice,
            local_model=args.local_model,
            cloud=args.cloud,
            cloud_model=args.cloud_model,
            no_rag=args.no_rag,
            language=args.language,
            use_vad=not args.no_vad,
            silent=args.silent,
        )


if __name__ == "__main__":
    main()