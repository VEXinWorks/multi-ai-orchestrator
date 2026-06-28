#!/usr/bin/env python3
"""
vexin_dual_brain.py — CPU thinking layer + GPU execution layer

Architecture:
  USER QUESTION
       ↓
  [CPU THINKER: deepseek-r1:1.5b] ← always warm, low latency (1-3s)
       ↓ (produces thought summary + plan)
  [GPU EXECUTOR: qwen2.5-coder / llama3.1 / minimax-m3] ← does the heavy work
       ↓ (gets context: question + CPU thought + retrieved memories)
  RESULT (with reasoning shown)

Benefits:
  - CPU thinker runs in parallel with GPU work (doesn't compete for VRAM)
  - CPU thought gives the GPU model a "first draft" to refine
  - Always-on: even when GPU is busy with Ollama inference, CPU is ready
  - Cheap: 1.5B model on CPU = ~3s per thought

Usage:
  ./vexin_dual_brain.py chat "What's the SAS tax threshold in Paraguay?"
  ./vexin_dual_brain.py think "complex question"     # CPU-only
  ./vexin_dual_brain.py execute "what to do"         # GPU only
  ./vexin_dual_brain.py dual "question"              # both
  ./vexin_dual_brain.py info                          # status

Models:
  - CPU thinker: deepseek-r1:1.5b (1.1 GB, fast on CPU, reasoning)
  - GPU executor: minimax-m3 (cloud, default) or llama3.1:8b (local)
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Endpoints
LOCAL_OLLAMA = "http://localhost:11434"
LOCAL_ENDPOINT_ID = "262a8872"  # local Ollama
CLOUD_ENDPOINT_ID = "d2947ec9"  # Ollama Cloud

# Models
CPU_THINKER = "deepseek-r1:1.5b"  # small, fast, reasoning
GPU_EXECUTOR_DEFAULT = "minimax-m3"  # cloud, fast chat

# Odysseus
ODYSSEUS_URL = "http://localhost:7000"
COOKIE_FILE = "/tmp/c.txt"


def get_ody_session():
    """Login to Odysseus and return cookie + base URL."""
    import urllib.request
    import urllib.error
    import re

    # Read cookie if cached (handle both plain token and curl format)
    try:
        with open(COOKIE_FILE) as f:
            content = f.read().strip()
        # Try to extract token from curl format
        m = re.search(r'odysseus_session\s+(\S+)', content)
        cookie = m.group(1) if m else content
    except FileNotFoundError:
        cookie = None

    if cookie:
        return cookie, ODYSSEUS_URL

    # Login
    pw_file = Path("/tmp/_pw.txt")
    if not pw_file.exists():
        raise RuntimeError("No Odysseus cookie and no password file")

    pw = pw_file.read_text().strip()

    data = json.dumps({"username": "admin", "password": pw}).encode()
    req = urllib.request.Request(
        f"{ODYSSEUS_URL}/api/auth/login",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
            token = body.get("session_token") or body.get("token")
            if token:
                with open(COOKIE_FILE, "w") as f:
                    f.write(token)
                return token, ODYSSEUS_URL
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"login failed: {e.code} {body[:200]}")
    raise RuntimeError("login: no token returned")


def get_or_create_session(name, model, endpoint_id, rag=True):
    """Get or create an Odysseus chat session."""
    cookie, base = get_ody_session()
    import urllib.request
    import urllib.error

    # List existing
    req = urllib.request.Request(
        f"{base}/api/sessions",
        headers={"Cookie": f"odysseus_session={cookie}"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        sessions = json.loads(resp.read())

    for s in sessions:
        if s.get("name") == name:
            return s.get("id")

    # Create
    body = urllib.parse.urlencode({
        "name": name, "model": model, "endpoint_id": endpoint_id,
        "rag": str(rag).lower(),
    }).encode()
    req = urllib.request.Request(
        f"{base}/api/session",
        data=body,
        headers={
            "Cookie": f"odysseus_session={cookie}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        s = json.loads(resp.read())
        return s.get("id")


def cpu_think(question, max_thinking_tokens=400, max_summary_tokens=200):
    """CPU thinker: deepseek-r1:1.5b. Returns (thinking, summary, elapsed).

    Pipeline:
      1. First call: thinking only (max_thinking_tokens)
      2. Second call: condense to a 2-3 sentence summary (max_summary_tokens)
    """
    t0 = time.time()
    import urllib.request

    # Step 1: Think
    thinking_prompt = f"""Think briefly about this question.

Question: {question}

Consider:
- What's being asked
- What context is needed
- What approach to take
- Pitfalls to avoid

Be concise but thorough. Don't use <think> tags."""

    body = json.dumps({
        "model": CPU_THINKER,
        "prompt": thinking_prompt,
        "stream": False,
        "options": {
            "num_predict": max_thinking_tokens,
            "temperature": 0.6,
            "num_ctx": 2048,
            "num_gpu": 0,  # FORCE CPU ONLY
        },
    }).encode()

    req = urllib.request.Request(
        f"{LOCAL_OLLAMA}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    thinking = ""
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            # DeepSeek-R1 returns BOTH 'thinking' (chain of thought) and 'response' (final answer)
            thinking = data.get("thinking", "").strip()
            response = data.get("response", "").strip()
            # Use thinking if present, else fall back to response
            if not thinking:
                thinking = response
            thinking = thinking.replace("<think>", "").replace("</think>", "").strip()
    except Exception as e:
        return f"(CPU thinker error: {e})", "", time.time() - t0

    # Step 2: Summarize
    summary_prompt = f"""Based on this thinking:
---
{thinking}
---

Write a CONCISE 2-3 sentence brief for another AI that will execute the answer.
Focus on: what to research, what approach to take, key constraints.
No preamble, just the brief:"""

    body = json.dumps({
        "model": CPU_THINKER,
        "prompt": summary_prompt,
        "stream": False,
        "options": {
            "num_predict": max_summary_tokens,
            "temperature": 0.5,
            "num_ctx": 1024,
            "num_gpu": 0,
        },
    }).encode()

    req = urllib.request.Request(
        f"{LOCAL_OLLAMA}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    summary = ""
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            # Prefer 'thinking' (richer for R1), fall back to 'response'
            summary = data.get("thinking", "").strip() or data.get("response", "").strip()
            summary = summary.replace("<think>", "").replace("</think>", "").strip()
    except Exception as e:
        summary = ""

    return thinking, summary, time.time() - t0


def gpu_execute(question, cpu_summary=None, model=None, endpoint_id=None,
                use_rag=True):
    """GPU executor: chat with question + CPU thought summary."""
    if model is None:
        model = GPU_EXECUTOR_DEFAULT
    if endpoint_id is None:
        # Cloud model
        endpoint_id = CLOUD_ENDPOINT_ID if model in ("minimax-m3", "nemotron-3-ultra", "glm-5.2") else LOCAL_ENDPOINT_ID

    sid = get_or_create_session(f"dual-brain-{model}", model, endpoint_id, rag=use_rag)
    cookie, base = get_ody_session()

    # Build prompt with CPU thought as context
    if cpu_summary:
        user_msg = f"""[CPU THINKER ANALYSIS]
{cpu_summary}

[USER QUESTION]
{question}

[YOUR TASK]
Use the CPU thinker's analysis above to answer the user's question directly.
The thinker already broke down the problem — your job is to give the
final, polished answer."""
    else:
        user_msg = question

    import urllib.request
    body = json.dumps({
        "message": user_msg,
        "session": sid,
        "use_rag": use_rag,
    }).encode()
    req = urllib.request.Request(
        f"{base}/api/chat",
        data=body,
        headers={
            "Cookie": f"odysseus_session={cookie}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read())
            elapsed = time.time() - t0
            return data.get("response", "(no response)"), elapsed, sid
    except Exception as e:
        return f"(GPU executor error: {e})", time.time() - t0, sid


def cmd_dual(question):
    """Full pipeline: CPU think + GPU execute."""
    print(f"\n{'='*70}")
    print(f"DUAL BRAIN: thinking + executing")
    print(f"{'='*70}\n")
    print(f"Question: {question}\n")

    # Step 1: CPU think
    print("─" * 70)
    print("[1/2] CPU THINKER (deepseek-r1:1.5b)")
    print("─" * 70)
    thinking, summary, cpu_time = cpu_think(question)
    print(f"⏱  {cpu_time:.2f}s")
    if thinking:
        print(f"\nThinking:\n{thinking[:600]}{'...' if len(thinking) > 600 else ''}")
    if summary:
        print(f"\n📋 Summary for GPU:\n{summary[:300]}")

    # Step 2: GPU execute
    print("\n" + "─" * 70)
    print("[2/2] GPU EXECUTOR (minimax-m3:cloud)")
    print("─" * 70)
    answer, gpu_time, sid = gpu_execute(question, summary)
    print(f"⏱  {gpu_time:.2f}s")
    print(f"\nAnswer:\n{answer}")

    print(f"\n{'='*70}")
    print(f"Total: {cpu_time + gpu_time:.2f}s (CPU: {cpu_time:.2f}s + GPU: {gpu_time:.2f}s)")
    print(f"{'='*70}")


def cmd_think(question):
    """CPU-only thinking."""
    print(f"\n[CPU THINKER]: {question}")
    thinking, summary, elapsed = cpu_think(question)
    print(f"\n⏱  {elapsed:.2f}s\n")
    print(f"Thinking:\n{thinking}\n")
    if summary:
        print(f"Summary:\n{summary}")


def cmd_execute(question):
    """GPU-only execution (no CPU thinking)."""
    print(f"\n[GPU EXECUTOR]: {question}")
    answer, elapsed, sid = gpu_execute(question, cpu_summary=None)
    print(f"\n⏱  {elapsed:.2f}s\n")
    print(f"Answer:\n{answer}")


def cmd_info():
    """System status."""
    print("=" * 70)
    print("VEXinWorks DUAL BRAIN")
    print("=" * 70)

    # Models
    r = subprocess.run(["ollama", "list"], capture_output=True, text=True)
    print("\nInstalled models:")
    print(r.stdout)

    # VRAM
    try:
        with open("/sys/class/drm/card1/device/mem_info_vram_used") as f:
            vram_used = int(f.read()) / 1e9
        with open("/sys/class/drm/card1/device/mem_info_vram_total") as f:
            vram_total = int(f.read()) / 1e9
        print(f"VRAM: {vram_used:.2f}GB / {vram_total:.2f}GB ({vram_total - vram_used:.2f}GB free)")
    except Exception:
        pass

    # RAM
    r = subprocess.run(["free", "-h"], capture_output=True, text=True)
    print(f"\nRAM:")
    print(r.stdout.split("\n")[1])

    # CPU
    r = subprocess.run(["nproc"], capture_output=True, text=True)
    print(f"CPU cores: {r.stdout.strip()}")

    # CPU thinker status
    print(f"\nCPU thinker: {CPU_THINKER}")
    r = subprocess.run(["ollama", "show", CPU_THINKER], capture_output=True, text=True)
    for line in r.stdout.split("\n"):
        if any(k in line for k in ["parameters", "quantization", "architecture"]):
            print(f"  {line.strip()}")

    print(f"\nGPU executor default: {GPU_EXECUTOR_DEFAULT} (cloud)")

    # Voice tools
    print(f"\nVoice tools:")
    for tool in ["arecord", "aplay", "ffmpeg", "edge-tts", "faster-whisper"]:
        r = subprocess.run(["which", tool], capture_output=True, text=True)
        status = "✓" if r.returncode == 0 else "✗"
        print(f"  {status} {tool}")
    r = subprocess.run(["arecord", "-l"], capture_output=True, text=True)
    print("  Capture devices:")
    for line in r.stdout.split("\n"):
        if "card" in line.lower() and "device" in line.lower():
            print(f"    {line.strip()}")


# ============================================================
# VOICE METHODS (Method 3: speak/listen)
# ============================================================

# Whisper model (lazy-loaded)
_WHISPER_MODEL = None


def get_whisper():
    """Lazy-load faster-whisper model (small, fast, CPU)."""
    global _WHISPER_MODEL
    if _WHISPER_MODEL is None:
        try:
            from faster_whisper import WhisperModel
            print("[whisper] loading model (small, cpu)...", file=sys.stderr)
            _WHISPER_MODEL = WhisperModel("small", device="cpu", compute_type="int8")
            print("[whisper] ready", file=sys.stderr)
        except Exception as e:
            print(f"[whisper] load error: {e}", file=sys.stderr)
            return None
    return _WHISPER_MODEL


def record_audio(duration=5, device="default", output="/tmp/voice_input.wav"):
    """Record audio from microphone for N seconds."""
    print(f"[record] recording {duration}s from '{device}' device...", file=sys.stderr)
    try:
        # -D for device, -d for duration, -f for format (S16_LE), -r for rate
        r = subprocess.run([
            "arecord",
            "-D", device,
            "-d", str(duration),
            "-f", "S16_LE",
            "-r", "16000",  # 16kHz is enough for speech
            "-c", "1",      # mono
            output,
        ], capture_output=True, text=True, timeout=duration + 5)
        if r.returncode == 0:
            print(f"[record] saved to {output}", file=sys.stderr)
            return output
        else:
            print(f"[record] error: {r.stderr}", file=sys.stderr)
            return None
    except Exception as e:
        print(f"[record] exception: {e}", file=sys.stderr)
        return None


def transcribe_audio(audio_path, language="en"):
    """Transcribe audio file to text using faster-whisper."""
    model = get_whisper()
    if model is None:
        return None
    try:
        print(f"[stt] transcribing {audio_path}...", file=sys.stderr)
        segments, info = model.transcribe(audio_path, language=language, beam_size=5)
        text = " ".join([seg.text for seg in segments]).strip()
        print(f"[stt] language: {info.language}, text: {text}", file=sys.stderr)
        return text
    except Exception as e:
        print(f"[stt] error: {e}", file=sys.stderr)
        return None


def speak_text(text, voice="en-US-AriaNeural", output="/tmp/voice_output.mp3",
               play=True, rate="+0%"):
    """Convert text to speech using edge-tts. Optionally play it."""
    try:
        import edge_tts
        import asyncio

        async def _gen():
            communicate = edge_tts.Communicate(text, voice, rate=rate)
            await communicate.save(output)

        asyncio.run(_gen())

        if play:
            print(f"[tts] playing {output}...", file=sys.stderr)
            # Use ffplay for MP3 (aplay can't do mp3)
            r = subprocess.run(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", output],
                              capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                # Fallback: use mpg123 or play
                r = subprocess.run(["mpg123", "-q", output], capture_output=True, text=True, timeout=60)
                if r.returncode != 0:
                    print(f"[tts] could not play (install ffplay or mpg123)", file=sys.stderr)
        return output
    except Exception as e:
        print(f"[tts] error: {e}", file=sys.stderr)
        return None


def cmd_voice(duration=5, device="default", model=None, no_rag=False, voice="en-US-AriaNeural"):
    """Method 3: voice in, voice out — full dual brain via speech."""
    print("=" * 70)
    print("VOICE MODE: speak to ask, listen to answer")
    print("=" * 70)
    print(f"\n[1/5] Recording {duration}s of audio...")
    audio = record_audio(duration=duration, device=device)
    if not audio:
        print("Recording failed.")
        return

    print(f"\n[2/5] Transcribing with faster-whisper (small)...")
    question = transcribe_audio(audio)
    if not question:
        print("Transcription failed.")
        return
    print(f"\n📝 You said: \"{question}\"")

    # Now run the dual brain on this question
    print(f"\n[3/5] Running dual brain on the question...")
    thinking, summary, cpu_time = cpu_think(question)
    print(f"  CPU think: {cpu_time:.2f}s")

    print(f"\n[4/5] GPU executing...")
    answer, gpu_time, sid = gpu_execute(question, summary, model=model, use_rag=not no_rag)
    print(f"  GPU execute: {gpu_time:.2f}s")
    print(f"\n💬 Answer:\n{answer}")

    # Speak the answer
    print(f"\n[5/5] Speaking the answer (voice: {voice})...")
    # Truncate for TTS (max ~10K chars for edge-tts)
    text_to_speak = answer[:5000] if len(answer) > 5000 else answer
    audio_out = speak_text(text_to_speak, voice=voice)
    if audio_out:
        print(f"  Saved to: {audio_out}")
    else:
        print("  TTS failed.")

    print(f"\n{'='*70}")
    print(f"Total: {cpu_time + gpu_time:.2f}s (CPU: {cpu_time:.2f}s + GPU: {gpu_time:.2f}s)")
    print(f"{'='*70}")


def cmd_speak(question, voice="en-US-AriaNeural", play=True):
    """Method 3b: text in, voice out."""
    print(f"\n[TEXT → VOICE]: {question}")
    answer, elapsed, sid = gpu_execute(question, cpu_summary=None)
    print(f"\n⏱ {elapsed:.2f}s")
    print(f"\nAnswer:\n{answer}")

    print(f"\n[TTS] speaking with voice {voice}...")
    speak_text(answer[:5000], voice=voice, play=play)


def cmd_listen(duration=5, device="default", language="en"):
    """Method 3c: voice in, text out (no TTS)."""
    print(f"\n[LISTEN] recording {duration}s...")
    audio = record_audio(duration=duration, device=device)
    if not audio:
        return
    text = transcribe_audio(audio, language=language)
    if text:
        print(f"\n📝 Transcribed: \"{text}\"")


def cmd_voices():
    """List available edge-tts voices."""
    try:
        import edge_tts
        import asyncio

        async def _list():
            voices = await edge_tts.list_voices()
            return voices

        voices = asyncio.run(_list())
        # Filter to a useful set
        en_voices = [v for v in voices if v["Locale"].startswith("en-")]
        es_voices = [v for v in voices if v["Locale"].startswith("es-")]
        print("English voices:")
        for v in en_voices[:15]:
            print(f"  {v['ShortName']:35} {v['Gender']:6} ({v['Locale']})")
        print(f"\nSpanish voices:")
        for v in es_voices[:10]:
            print(f"  {v['ShortName']:35} {v['Gender']:6} ({v['Locale']})")
        print(f"\nTotal: {len(voices)} voices (en={len(en_voices)}, es={len(es_voices)})")
    except Exception as e:
        print(f"Error listing voices: {e}")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_dual = sub.add_parser("dual")
    p_dual.add_argument("question")
    p_dual.add_argument("--model", help="override GPU model")
    p_dual.add_argument("--no-rag", action="store_true")

    p_think = sub.add_parser("think")
    p_think.add_argument("question")

    p_exec = sub.add_parser("execute")
    p_exec.add_argument("question")
    p_exec.add_argument("--model")

    sub.add_parser("info")

    # Voice commands (Method 3)
    p_voice = sub.add_parser("voice", help="Voice in, voice out — speak to ask, listen to answer")
    p_voice.add_argument("--duration", "-d", type=int, default=5, help="Recording duration in seconds")
    p_voice.add_argument("--device", default="default", help="ALSA device (default, plughw:1,0, etc)")
    p_voice.add_argument("--voice", default="en-US-AriaNeural", help="Edge TTS voice name")
    p_voice.add_argument("--model", help="Override GPU executor model")
    p_voice.add_argument("--no-rag", action="store_true", help="Disable RAG for GPU executor")

    p_speak = sub.add_parser("speak", help="Text in, voice out (no microphone needed)")
    p_speak.add_argument("question", help="Text to ask")
    p_speak.add_argument("--voice", default="en-US-AriaNeural", help="Edge TTS voice name")
    p_speak.add_argument("--no-play", action="store_true", help="Just generate the audio file, don't play it")

    p_listen = sub.add_parser("listen", help="Voice in, text out (no TTS)")
    p_listen.add_argument("--duration", "-d", type=int, default=5, help="Recording duration in seconds")
    p_listen.add_argument("--device", default="default", help="ALSA device")
    p_listen.add_argument("--language", default="en", help="Language code (en, es, etc)")

    sub.add_parser("voices", help="List available edge-tts voices")

    args = parser.parse_args()

    if args.cmd == "dual":
        cmd_dual(args.question)
    elif args.cmd == "think":
        cmd_think(args.question)
    elif args.cmd == "execute":
        cmd_execute(args.question)
    elif args.cmd == "info":
        cmd_info()
    elif args.cmd == "voice":
        cmd_voice(duration=args.duration, device=args.device,
                  model=args.model, no_rag=args.no_rag, voice=args.voice)
    elif args.cmd == "speak":
        cmd_speak(args.question, voice=args.voice, play=not args.no_play)
    elif args.cmd == "listen":
        cmd_listen(duration=args.duration, device=args.device, language=args.language)
    elif args.cmd == "voices":
        cmd_voices()


if __name__ == "__main__":
    main()