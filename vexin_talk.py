#!/usr/bin/env python3
"""
vexin_talk.py — One-command voice chat with the local AI

Just speak, then listen to the answer. Designed for hands-free use.
Records from default mic, transcribes, asks dual brain, speaks answer.

Models available:
  Local (no cloud, runs on your GPU):
    - llama3.1:8b (default, 4.9 GB, ~90 tok/s, best general)
    - llama3.2:3b (faster, 2.0 GB, simpler tasks)
    - qwen2.5-coder:7b (code questions)
    - deepseek-r1:8b (slow but thinks deeply)
  Cloud (slower latency, more capable):
    - minimax-m3 (default if --cloud, fast chat)
    - glm-5.2, nemotron-3-ultra (use --cloud-model)

Usage:
  ./vexin_talk.py                          # 5s voice in, voice out (local llama3.1)
  ./vexin_talk.py --cloud                  # use cloud model instead
  ./vexin_talk.py -d 10 --local-model qwen2.5-coder:7b  # local coder for code Qs
  ./vexin_talk.py --loop                   # keep talking
  ./vexin_talk.py --text "hi"              # just type, get voice answer
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

# Add the dual brain module
sys.path.insert(0, "/home/vexin/projects")
from vexin_dual_brain import cpu_think, gpu_execute, speak_text, record_audio, transcribe_audio, get_whisper


def talk_once(duration=5, device="default", voice="en-US-AriaNeural",
              local_model="llama3.1:8b", cloud=False, cloud_model="minimax-m3",
              no_rag=False, language="en", silent=False):
    """One voice-in, voice-out conversation."""
    print()
    print("=" * 60)
    print(f"🎤 Speak now ({duration}s)...")
    print("=" * 60)

    # Record
    audio = record_audio(duration=duration, device=device)
    if not audio:
        return None

    # Transcribe
    question = transcribe_audio(audio, language=language)
    if not question or not question.strip():
        print("❌ Didn't catch that. Try again.")
        return None

    print(f"\n📝 You said: \"{question}\"")
    if not silent:
        print()

    # Think
    print("🧠 CPU thinking...")
    thinking, summary, cpu_time = cpu_think(question)
    print(f"  ⏱  {cpu_time:.2f}s")

    # Execute on local OR cloud
    if cloud:
        model = cloud_model
        print(f"☁️  GPU (cloud) executing with {model}...")
    else:
        model = local_model
        print(f"💻 GPU (local) executing with {model}...")

    answer, gpu_time, sid = gpu_execute(question, summary, model=model, use_rag=not no_rag)
    print(f"  ⏱  {gpu_time:.2f}s")

    print(f"\n💬 Answer: {answer}\n")

    # Speak
    text_to_speak = answer[:5000] if len(answer) > 5000 else answer
    out_path = f"/tmp/talk_{int(time.time())}.mp3"
    print(f"🔊 Speaking ({voice})...")
    result = speak_text(text_to_speak, voice=voice, output=out_path, play=True)

    return answer


def main():
    parser = argparse.ArgumentParser(
        description="One-command voice chat with the local AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  vexin_talk.py                  # 5s record, AI answers with voice
  vexin_talk.py -d 10            # longer recording
  vexin_talk.py -d 10 --voice es-MX-JorgeNeural  # Spanish voice
  vexin_talk.py --loop           # keep talking
  vexin_talk.py --text "hi"      # just type, get voice answer
        """
    )
    parser.add_argument("-d", "--duration", type=int, default=5,
                        help="Recording duration in seconds (default: 5)")
    parser.add_argument("--device", default="default",
                        help="ALSA device (default, plughw:1,0, etc)")
    parser.add_argument("--voice", default="en-US-AriaNeural",
                        help="Edge TTS voice (try: es-MX-JorgeNeural for Spanish)")
    parser.add_argument("--cloud", action="store_true",
                        help="Use cloud model instead of local (default: local)")
    parser.add_argument("--local-model", default="llama3.1:8b",
                        help="Local ollama model (llama3.1:8b, llama3.2:3b, qwen2.5-coder:7b, etc)")
    parser.add_argument("--cloud-model", default="minimax-m3",
                        help="Cloud model (minimax-m3, glm-5.2, nemotron-3-ultra)")
    parser.add_argument("--no-rag", action="store_true", help="Disable RAG")
    parser.add_argument("--language", default="en", help="STT language (en, es, etc)")
    parser.add_argument("--loop", action="store_true", help="Continuous conversation mode")
    parser.add_argument("--text", help="Skip recording, use this text as question")
    parser.add_argument("--silent", action="store_true", help="Quiet mode (just transcript)")

    args = parser.parse_args()

    # Pre-load whisper so first iteration is fast
    print("Loading Whisper model...")
    get_whisper()

    # Pick the model
    if args.cloud:
        active_model = args.cloud_model
        backend = "cloud"
    else:
        active_model = args.local_model
        backend = "local"
    print(f"GPU executor: {active_model} ({backend})")

    if args.text:
        # Direct text mode
        question = args.text
        print(f"\n📝 Question: \"{question}\"")
        print(f"🧠 CPU thinking...")
        thinking, summary, cpu_time = cpu_think(question)
        print(f"  ⏱  {cpu_time:.2f}s")
        if args.cloud:
            print(f"☁️  GPU (cloud) executing with {active_model}...")
        else:
            print(f"💻 GPU (local) executing with {active_model}...")
        answer, gpu_time, sid = gpu_execute(question, summary, model=active_model, use_rag=not args.no_rag)
        print(f"  ⏱  {gpu_time:.2f}s")
        print(f"\n💬 Answer: {answer}\n")
        out_path = f"/tmp/talk_{int(time.time())}.mp3"
        print(f"🔊 Speaking ({args.voice})...")
        speak_text(answer[:5000], voice=args.voice, output=out_path, play=True)
        return

    if args.loop:
        print("=" * 60)
        print("🎙️ CONVERSATION MODE (Ctrl+C to exit)")
        print("=" * 60)
        turn = 0
        try:
            while True:
                turn += 1
                print(f"\n--- Turn {turn} ---")
                answer = talk_once(
                    duration=args.duration,
                    device=args.device,
                    voice=args.voice,
                    local_model=args.local_model,
                    cloud=args.cloud,
                    cloud_model=args.cloud_model,
                    no_rag=args.no_rag,
                    language=args.language,
                    silent=args.silent,
                )
                if answer is None:
                    continue
        except KeyboardInterrupt:
            print(f"\n\n👋 Goodbye after {turn} turns")
    else:
        talk_once(
            duration=args.duration,
            device=args.device,
            voice=args.voice,
            local_model=args.local_model,
            cloud=args.cloud,
            cloud_model=args.cloud_model,
            no_rag=args.no_rag,
            language=args.language,
            silent=args.silent,
        )


if __name__ == "__main__":
    main()