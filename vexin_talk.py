#!/usr/bin/env python3
"""
vexin_talk.py — One-command voice chat with the local AI

Just speak, then listen to the answer. Designed for hands-free use.
Records from default mic, transcribes, asks dual brain, speaks answer.

Usage:
  vexin_talk.py                  # 5s record, dual brain, speak
  vexin_talk.py -d 10            # 10s record
  vexin_talk.py -d 10 --voice es-MX-JorgeNeural  # Spanish voice
  vexin_talk.py --loop           # continuous conversation mode
  vexin_talk.py --text           # just type, no mic
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
              model=None, no_rag=False, language="en", silent=False):
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

    # Think + Execute
    print("🧠 CPU thinking...")
    thinking, summary, cpu_time = cpu_think(question)
    print(f"  ⏱  {cpu_time:.2f}s")

    print("⚡ GPU executing...")
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
    parser.add_argument("--model", help="Override GPU model")
    parser.add_argument("--no-rag", action="store_true", help="Disable RAG")
    parser.add_argument("--language", default="en", help="STT language (en, es, etc)")
    parser.add_argument("--loop", action="store_true", help="Continuous conversation mode")
    parser.add_argument("--text", help="Skip recording, use this text as question")
    parser.add_argument("--silent", action="store_true", help="Quiet mode (just transcript)")

    args = parser.parse_args()

    # Pre-load whisper so first iteration is fast
    print("Loading Whisper model...")
    get_whisper()

    if args.text:
        # Direct text mode
        question = args.text
        print(f"📝 Question: \"{question}\"")
        print("🧠 CPU thinking...")
        thinking, summary, cpu_time = cpu_think(question)
        print(f"  ⏱  {cpu_time:.2f}s")
        print("⚡ GPU executing...")
        answer, gpu_time, sid = gpu_execute(question, summary, model=args.model, use_rag=not args.no_rag)
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
                    model=args.model,
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
            model=args.model,
            no_rag=args.no_rag,
            language=args.language,
            silent=args.silent,
        )


if __name__ == "__main__":
    main()