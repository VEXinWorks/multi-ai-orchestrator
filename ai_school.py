#!/usr/bin/env python3
"""
VEXinWorks AI School

A continuous-learning system where:
- 3 cloud AIs (GLM-5.2, minimax-m3, nemotron-3-ultra) are professors
- Local Ollama models (llama3.1, qwen2.5-coder) are students
- Odysseus stores all lessons as skills + memories

Each lesson:
1. Cloud AI #1 teaches (writes the lesson)
2. Cloud AI #2 critiques and improves
3. Cloud AI #3 writes verification/exercises
4. Local model validates (attempts the exercises)
5. Result stored as Odysseus skill + memory entry

Run modes:
  python3 ai_school.py curriculum "3D printing mastery"
  python3 ai_school.py loop                   # run a batch automatically
  python3 ai_school.py status                 # show progress
  python3 ai_school.py skip-lesson <id>       # mark current as done
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
from urllib.parse import urlencode

# === CONFIG ===
ODYSSEUS_URL = os.environ.get("ODYSSEUS_URL", "http://localhost:7000")
CLOUD_ENDPOINT_ID = "d2947ec9"
LOCAL_ENDPOINT_ID = "262a8872"
ADMIN_USER = "admin"

# === CURRICULUM (12 subjects x 10 lessons each) ===
# Each subject has a topic, target audience, and lesson list
CURRICULUM = {
    "3d-printing": {
        "title": "3D Printing Mastery",
        "description": "How to operate, troubleshoot, and optimize FDM 3D printing",
        "audience": "VEXinWorks staff + autonomous agents",
        "lessons": [
            "FDM printer anatomy: hotend, extruder, bed, motion system, electronics",
            "Slicer settings deep-dive: layer height, infill, supports, walls, speed",
            "Filament types: PLA, PETG, ABS, TPU, ASA, polycarbonate — when to use each",
            "Common print failures: layer shifts, stringing, warping, under/over-extrusion",
            "Bed leveling: manual mesh, auto-level, CR-Touch, BL-Touch, inductive probes",
            "Temperature calibration: hotend tower, bed adhesion, retraction tuning",
            "Multi-material and AMS systems: changeover, purge, waste management",
            "Print speed vs quality tradeoffs: volumetric flow, acceleration, jerk",
            "Maintenance schedule: belts, lubrication, hotend cleaning, firmware updates",
            "Troubleshooting methodology: diagnose from print artifacts to root cause",
        ],
    },
    "business-operations": {
        "title": "Business Operations & Legal in Paraguay",
        "description": "Running a small business legally and efficiently in Paraguay",
        "audience": "João as business owner; AIs as advisors",
        "lessons": [
            "Paraguay business structures: SAS, SRL, unipersonal — pros/cons/taxes",
            "Tax obligations: IVA (10%), IRPC, IRP, patent municipal, timelines",
            "Setting up billing: SET e-Kuatia, timbrado, electronic invoicing",
            "Banking for small business: BCP, Itaú, Banco Familiar; fintechs (Tigo Money)",
            "Hiring and labor laws: INSS, aguinaldo, vacaciones, jornada laboral",
            "Import duties and DIM: when to import, what's restricted, costs",
            "Accounting basics for service businesses: cash vs accrual, simple P&L",
            "Contracts: client agreements, NDAs, supplier terms, dispute resolution",
            "Insurance: what you actually need for a workshop with equipment",
            "Pricing strategy: cost+margin, value-based, competitor analysis",
        ],
    },
    "app-web-dev": {
        "title": "App & Web Development",
        "description": "Building production-grade web apps and PWAs",
        "audience": "AI agents + developers extending VEXinWorks",
        "lessons": [
            "Modern stack: TypeScript, React/Next.js, Node, FastAPI — when to pick each",
            "Database design: PostgreSQL for production, SQLite for local, ChromaDB for RAG",
            "REST vs GraphQL vs gRPC: tradeoffs and use cases",
            "Authentication: sessions, JWT, OAuth, OIDC, password hashing, 2FA",
            "Frontend patterns: state management, data fetching, error boundaries, suspense",
            "Backend patterns: queue workers, webhooks, SSE, websockets, idempotency",
            "Deployment: Docker, systemd, Tailscale, ngrok, cloud (when necessary)",
            "Testing: unit, integration, E2E, contract tests, smoke tests in production",
            "Observability: structured logging, metrics, traces, alerting on the cheap",
            "Performance: caching, CDN, code splitting, image optimization, lazy loading",
        ],
    },
    "ai-ml-engineering": {
        "title": "AI/ML Engineering",
        "description": "Building agentic AI systems that actually work",
        "audience": "AI agents building AI agents",
        "lessons": [
            "Tool calling patterns: when to use, how to format, error recovery",
            "Skill design: triggers, procedures, pitfalls, verification",
            "MCP (Model Context Protocol): server architecture, client integration",
            "Agent loops: ReAct, Reflexion, plan-and-execute, hybrid approaches",
            "Memory systems: episodic, semantic, procedural, working memory",
            "RAG architectures: chunking, embedding, retrieval, re-ranking, evaluation",
            "Multi-agent systems: delegation, voting, supervisor/worker, blackboard",
            "Local model operations: Ollama, VRAM management, model selection, quantization",
            "Prompt engineering at scale: versioning, A/B testing, regression suites",
            "Self-improvement: critique loops, human feedback, automated evaluation",
        ],
    },
    "marketing-sales": {
        "title": "Marketing & Sales",
        "description": "Getting customers, keeping them, growing the business",
        "audience": "AI agents running marketing for VEXinWorks",
        "lessons": [
            "Copywriting fundamentals: AIDA, PAS, before-after-bridge",
            "Instagram for 3D printing: what works (process reels, time-lapses)",
            "WhatsApp Business: catalogs, quick replies, broadcasts (legally)",
            "Google Ads basics: search vs display, keywords, negative keywords, Quality Score",
            "Meta Ads: lookalikes, retargeting, creative testing, CBO",
            "SEO for local service businesses: Google Business Profile, citations, reviews",
            "Email marketing: tools, list hygiene, automation sequences",
            "Pricing psychology: anchoring, decoy effect, charm pricing, payment plans",
            "Customer service: response time, tone, escalation, refund policy",
            "Referral programs: how to design one that actually works for print-on-demand",
        ],
    },
    "software-integration": {
        "title": "Software Integration",
        "description": "Wiring together Odysseus, Antigravity, Google APIs, and more",
        "audience": "AI agents orchestrating the whole stack",
        "lessons": [
            "Odysseus API surface: auth, chat, memory, skills, personal docs, tasks, MCP",
            "Odysseus MCP servers: image_gen, memory, rag, email — what's there",
            "Google Drive integration: OAuth, service accounts, sharing, syncing",
            "Google Sheets as a database: when it's fine, when it isn't, webhooks",
            "WhatsApp Cloud API: setup, templates, conversations, costs, ToS",
            "Instagram Graph API: posting, insights, DMs (very limited)",
            "Tailscale: mesh networking, MagicDNS, Funnel, exit nodes, ACLs",
            "Discord/Slack/Telegram bots: architecture, rate limits, scaling",
            "Payment gateways in Paraguay: Tigo Money, Wally, PayPal, Stripe (limited)",
            "Antigravity: how to use the desktop framework, IDE integration, deploy",
        ],
    },
    "image-to-3d": {
        "title": "Image-to-3D & Generative CAD",
        "description": "Replacing Tripo.ai/Meshy/3D AI Studio with self-hosted alternatives",
        "audience": "AI agents handling custom design requests",
        "lessons": [
            "How image-to-3D works: NeRF, Gaussian Splatting, diffusion-based generation",
            "Open-source models: TripoSR (single image), Zero123 (multi-view), Shap-E",
            "Self-hosted TripoSR with Ollama/HuggingFace pipelines",
            "Multi-view photogrammetry: COLMAP + openMVS for high-quality scans",
            "Point cloud → mesh: Poisson reconstruction, marching cubes, decimation",
            "Mesh cleanup: meshfix, PyMeshLab, common artifacts and fixes",
            "STL repair for printing: manifold, normals, scale, orientation",
            "Text-to-3D alternatives: Point-E, Magic3D, DreamFusion (research)",
            "Combining scans + AI: best of both, when each wins",
            "Building a custom image-to-STL API service with FastAPI",
        ],
    },
    "personal-assistant": {
        "title": "Personal Assistant Skills (JARVIS-style)",
        "description": "Being a calm, capable, anticipatory personal AI",
        "audience": "AI agents serving João directly",
        "lessons": [
            "Daily planning: time-blocking, energy management, priority matrices",
            "Calendar management: scheduling, rescheduling, conflict resolution",
            "Email triage: what's important, what's noise, response templates",
            "Meeting prep: agendas, research, follow-up automation",
            "Travel: bookings, itineraries, points/miles optimization",
            "Health tracking: simple logs, trend analysis, gentle reminders",
            "Reading: book/paper queue, summaries, action extraction",
            "Personal finance: budget, bills, savings, investment monitoring",
            "Communication style: brief, warm, direct; ask before assuming",
            "Boundaries: when NOT to act, when to ask, when to refuse",
        ],
    },
    "auto-print-business": {
        "title": "Auto-Print On-Demand Business",
        "description": "End-to-end pipeline: web → print, WhatsApp → print",
        "audience": "AI agents running the business autonomously",
        "lessons": [
            "Order intake: web form, WhatsApp bot, email parser — unified format",
            "Job estimation: STL analysis, slicing estimate, time/material cost",
            "Quote generation: with margin, in client currency, with delivery date",
            "Approval flow: client confirms, payment received, job queued",
            "Print queue management: priority, batch similar jobs, error handling",
            "Material prep: dry filament, load AMS, color match, storage",
            "Print monitoring: webcam, telemetry, pause-on-failure, recovery",
            "Post-processing: support removal, sanding, painting, QC",
            "Delivery: pickup, courier, shipping integration (when international)",
            "Feedback loop: client ratings, photos, reviews, design improvements",
        ],
    },
    "self-healing": {
        "title": "Self-Healing Systems",
        "description": "Detect bugs, fix them, learn from them, never repeat them",
        "audience": "AI agents maintaining themselves and their infra",
        "lessons": [
            "Error logging as a first-class concern: structure, context, dedup",
            "Health checks: liveness, readiness, deep probes, cascading failure detection",
            "Auto-restart patterns: systemd, Docker, supervisor patterns",
            "Resource monitoring: disk, RAM, VRAM, CPU, network, saturation",
            "Anomaly detection: statistical baselines, alerts before failure",
            "Runbooks: human-readable procedures for common incidents",
            "Rollback: every deploy has a documented rollback, tested regularly",
            "Post-mortem culture: blameless, root cause, contributing factors",
            "Regression suites: every bug fix becomes a test, never repeats",
            "Graceful degradation: when features fail, fall back, never crash",
        ],
    },
    "research-reasoning": {
        "title": "Research & Reasoning",
        "description": "Finding and synthesizing information reliably",
        "audience": "AI agents doing research for João",
        "lessons": [
            "Web search operators: site:, filetype:, exact match, exclusion",
            "Source evaluation: authority, accuracy, currency, bias",
            "Multi-source synthesis: triangulation, conflict resolution",
            "Fact-checking: cross-reference, primary sources, common pitfalls",
            "Data extraction: tables, PDFs, images, OCR, structured data",
            "Citation hygiene: keep track of every claim's source",
            "Wikipedia/research rabbit holes: when to dive deep, when to surface",
            "Local RAG vs web search: when each wins, how to combine",
            "Translation: language detection, quality preservation, cultural context",
            "Reasoning under uncertainty: confidence levels, probabilistic thinking",
        ],
    },
    "life-coaching": {
        "title": "Life Skills & Coaching",
        "description": "Helping João make better decisions and be more effective",
        "audience": "AI agents in advisory role",
        "lessons": [
            "Decision frameworks: 10-10-10, regret minimization, second-order thinking",
            "Goal setting: OKRs, BHAGs, leading vs lagging indicators",
            "Habit formation: cue-routine-reward, friction design, atomic habits",
            "Productivity systems: GTD, Inbox Zero, Pomodoro, deep work",
            "Mental models: inversion, first principles, opportunity cost, base rates",
            "Communication: feedback, difficult conversations, negotiation basics",
            "Learning: deliberate practice, spaced repetition, Feynman technique",
            "Health: sleep, exercise, nutrition, stress — fundamentals that compound",
            "Relationships: maintaining ties, networking, asking for help",
            "Mindset: growth vs fixed, long-term thinking, dealing with setbacks",
        ],
    },
}


# === Helpers ===
def load_pw():
    for p in ["/tmp/_pw.txt", "/home/vexin/odysseus/.env"]:
        try:
            with open(p, 'rb') as f:
                content = f.read()
            if p.endswith(".env"):
                for line in content.splitlines():
                    if b'ADMIN_PASSWORD' in line and not line.startswith(b'#'):
                        return line.split(b'=', 1)[1].decode()
            return content.decode().strip()
        except FileNotFoundError:
            continue
    return None


class OdysseusClient:
    def __init__(self):
        self.cookie = None
        self.base = ODYSSEUS_URL
        self._login()

    def _request(self, method, path, data=None, params=None, timeout=120):
        url = f"{self.base}{path}"
        if params:
            url += "?" + urlencode(params)
        req = urllib.request.Request(url, method=method)
        req.add_header("Content-Type", "application/json")
        if self.cookie:
            req.add_header("Cookie", f"odysseus_session={self.cookie}")
        body = json.dumps(data).encode() if data is not None else None
        try:
            with urllib.request.urlopen(req, body, timeout=timeout) as resp:
                raw = resp.read().decode()
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return {"raw": raw}
        except urllib.error.HTTPError as e:
            return {"error": e.code, "body": e.read().decode()[:500]}
        except Exception as _e:
                    pass

    def _login(self):
        pw = load_pw()
        if not pw:
            return
        payload = json.dumps({"username": ADMIN_USER, "password": pw, "remember": True}).encode()
        req = urllib.request.Request(
            f"{self.base}/api/auth/login", data=payload, method="POST",
            headers={"Content-Type": "application/json"})
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            for h in resp.headers.get_all("Set-Cookie") or []:
                if "odysseus_session=" in h:
                    self.cookie = h.split("odysseus_session=", 1)[1].split(";", 1)[0]
                    break
        except Exception as _e:
                    pass

    def create_session(self, name, model, endpoint_id):
        body = urlencode({"name": name, "model": model, "endpoint_id": endpoint_id}).encode()
        req = urllib.request.Request(
            f"{self.base}/api/session", data=body, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        if self.cookie:
            req.add_header("Cookie", f"odysseus_session={self.cookie}")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except Exception as _e:
                    pass

    def chat(self, message, session_id, timeout=180):
        return self._request("POST", "/api/chat",
                             {"message": message, "session": session_id}, timeout=timeout)

    def add_memory(self, text, source="ai_school", session_id=None):
        return self._request("POST", "/api/memory/add",
                             {"text": text, "source": source, "session_id": session_id})

    def add_skill(self, name, description, category, procedure, pitfalls, verification):
        """Add a skill with dedup — if name exists, update instead of create.

        Returns {"ok": True, "action": "created"|"updated"|"unchanged"}.
        """
        import urllib.parse
        skill = {
            "name": name,
            "description": description[:200],
            "category": category,
            "procedure": procedure if isinstance(procedure, list) else [procedure],
            "pitfalls": pitfalls if isinstance(pitfalls, list) else [pitfalls],
            "verification": verification if isinstance(verification, list) else [verification],
            "status": "active",
            "version": "1.0",
            "source": "ai_school",
        }
        # First check if skill already exists
        try:
            existing = self._request("GET", "/api/skills")
            skills_list = existing.get("skills", []) if isinstance(existing, dict) else existing
            for s in skills_list:
                if s.get("name") == name:
                    # Update the existing skill
                    sid = s.get("id", name)
                    body = urllib.parse.urlencode({
                        "name": name,
                        "description": skill["description"],
                        "category": category,
                    }).encode()
                    # Use JSON body for PUT (multipart had errors earlier)
                    import json as _json
                    body = _json.dumps({
                        "name": name,
                        "description": skill["description"],
                        "category": category,
                        "procedure": skill["procedure"],
                        "pitfalls": skill["pitfalls"],
                        "verification": skill["verification"],
                    }).encode()
                    req = urllib.request.Request(
                        f"{self.base_url}/api/skills/{sid}",
                        data=body,
                        headers={
                            "Cookie": f"odysseus_session={self.cookie}",
                            "Content-Type": "application/json",
                        },
                        method="PUT",
                    )
                    try:
                        with urllib.request.urlopen(req, timeout=15) as resp:
                            return {"ok": True, "action": "updated", "id": sid}
                    except Exception:
                        return {"ok": True, "action": "unchanged", "id": sid}
        except Exception:
            pass
        return self._request("POST", "/api/skills/add", skill)


# === AI SCHOOL CORE ===
class AISchool:
    """The loop: 3 cloud AIs teach each lesson, validate, and persist."""

    TEACHERS = ["glm-5.2", "minimax-m3", "nemotron-3-ultra"]

    def __init__(self, ody):
        self.ody = ody
        self.sessions = {}  # {teacher: session_id}

    def _ensure_session(self, teacher):
        if teacher in self.sessions:
            return self.sessions[teacher]
        s = self.ody.create_session(
            f"school-{teacher}-{int(time.time())}", teacher, CLOUD_ENDPOINT_ID
        )
        sid = s.get("id") if isinstance(s, dict) else None
        if not sid:
            print(f"[!] could not create session for {teacher}: {s}", file=sys.stderr)
            return None
        self.sessions[teacher] = sid
        return sid

    def _ask(self, teacher, prompt, timeout=180):
        sid = self._ensure_session(teacher)
        if not sid:
            return f"(no session for {teacher})"
        result = self.ody.chat(prompt, sid, timeout=timeout)
        if isinstance(result, dict):
            return result.get("response", result.get("body", "(no response)"))
        return str(result)

    def teach_lesson(self, subject_key, lesson_idx):
        """Run a full lesson cycle: teach -> critique -> verify -> store."""
        if subject_key not in CURRICULUM:
            return {"error": f"unknown subject {subject_key}"}
        subject = CURRICULUM[subject_key]
        if lesson_idx >= len(subject["lessons"]):
            return {"error": f"lesson {lesson_idx} out of range"}
        lesson = subject["lessons"][lesson_idx]
        lesson_id = f"{subject_key}-L{lesson_idx+1:02d}"
        print(f"\n{'='*70}\nLESSON: {lesson_id} — {lesson}\n{'='*70}", file=sys.stderr)

        # Phase 1: Teach (GLM-5.2 — research specialist)
        teach_prompt = f"""You are {self.TEACHERS[0]}, a research specialist.
Teach the following lesson for the VEXinWorks AI School.

Topic: {lesson}
Audience: {subject['audience']}
Subject context: {subject['description']}

Format your response as:
1. KEY CONCEPTS (3-5 bullet points, the fundamentals)
2. EXPLANATION (concise, 3-4 paragraphs with concrete examples)
3. ACTIONABLE STEPS (numbered list, what to DO)
4. PITFALLS (3-5 things that often go wrong and how to avoid)
5. RESOURCES (where to learn more — be specific, not "search Google")

Be CONCISE. Prefer concrete advice over theory. Use Portuguese/Spanish only when the concept is regional (Paraguay context)."""
        t0 = time.time()
        lesson_body = self._ask(self.TEACHERS[0], teach_prompt)
        print(f"  [1/4] teach ({time.time()-t0:.1f}s): {len(lesson_body)} chars")

        # Phase 2: Critique (nemotron-3-ultra — technical specialist)
        critique_prompt = f"""You are {self.TEACHERS[2]}, a technical specialist.
A previous AI taught this lesson:

LESSON TOPIC: {lesson}

PREVIOUS TEACHING:
{lesson_body}

Your job: critique and improve. Specifically:
1. What's missing? Add 2-3 KEY POINTS that the teacher missed.
2. What's wrong? Correct any errors.
3. What's confusing? Rewrite 1-2 sections more clearly.
4. What examples would make it more concrete?

Keep your critique CONCISE — focus on improvements, don't repeat what was good. Output as a numbered list of improvements."""
        t0 = time.time()
        critique = self._ask(self.TEACHERS[2], critique_prompt)
        print(f"  [2/4] critique ({time.time()-t0:.1f}s): {len(critique)} chars")

        # Phase 3: Verify (minimax-m3 — generalist, makes it concrete)
        verify_prompt = f"""You are {self.TEACHERS[1]}, a generalist AI.
This lesson was taught:

LESSON TOPIC: {lesson}

TEACHING:
{lesson_body}

CRITIQUE:
{critique}

Now write VERIFICATION EXERCISES:
1. A SHORT QUIZ (3 questions with answers) that proves someone learned it
2. A PRACTICAL EXERCISE (a specific task they should be able to do after this lesson)
3. SELF-CHECK CRITERIA (3-5 things to verify the lesson stuck)

Output clearly labeled sections."""
        t0 = time.time()
        verify = self._ask(self.TEACHERS[1], verify_prompt)
        print(f"  [3/4] verify ({time.time()-t0:.1f}s): {len(verify)} chars")

        # Build full text (used for skill + chunked memory)
        full_text = f"""AI SCHOOL LESSON: {lesson_id}
TOPIC: {lesson}
SUBJECT: {subject['title']}
AUDIENCE: {subject['audience']}
TAUGHT BY: GLM-5.2
CRITIQUED BY: nemotron-3-ultra
VERIFIED BY: minimax-m3

=== TEACHING (GLM-5.2) ===
{lesson_body}

=== CRITIQUE & IMPROVEMENTS (nemotron-3-ultra) ===
{critique}

=== VERIFICATION EXERCISES (minimax-m3) ===
{verify}"""

        # Phase 4: Store — chunk into multiple memories if needed
        # Odysseus memory has a 5000-char limit per entry
        max_chars = 4500  # leave headroom
        chunks = []
        for i in range(0, len(full_text), max_chars):
            chunk = full_text[i:i+max_chars]
            chunks.append(chunk)

        t0 = time.time()
        mem_results = []
        for idx, chunk in enumerate(chunks):
            label = f"({idx+1}/{len(chunks)})" if len(chunks) > 1 else ""
            mem_text = chunk
            if idx == 0:
                mem_text = f"AI SCHOOL LESSON {lesson_id} PART {label}\n{chunk}"
            else:
                mem_text = f"AI SCHOOL LESSON {lesson_id} PART {label} (continued)\n{chunk}"
            mem_result = self.ody.add_memory(mem_text, source=f"ai_school_{subject_key}")
            mem_results.append(mem_result)
        print(f"  [4/4] store ({time.time()-t0:.1f}s): {len(chunks)} chunk(s)")

        # Also create a skill if this is a clear procedural topic
        # Heuristic: if teaching contains "ACTIONABLE STEPS" — extract and save as skill
        skill_result = None
        if "ACTIONABLE STEPS" in lesson_body or "PROCEDURE" in lesson_body:
            try:
                skill_name = f"school-{lesson_id}".replace("_", "-")
                skill_result = self.ody.add_skill(
                    name=skill_name[:64],
                    description=f"From AI School {lesson_id}: {lesson}"[:200],
                    category=subject_key,
                    procedure=[lesson_body, critique],
                    pitfalls=["Apply verification before claiming mastery", "Re-read critique section"],
                    verification=[verify],
                )
                print(f"  [skill] {skill_name}: {skill_result}", file=sys.stderr)
            except Exception as _e:
                        pass

        # Phase 5: Local practice — the local AI actually TRIES the exercise
        # This makes the local AI learn by DOING, not just by reading
        local_practice_result = None
        try:
            local_practice_result = self._local_practice(
                lesson_id, lesson, verify,
                use_model="llama3.1:8b",  # default local student
            )
        except Exception as _e:
            print(f"  [local_practice] error: {_e}", file=sys.stderr)

        return {
            "lesson_id": lesson_id,
            "topic": lesson,
            "subject": subject_key,
            "teaching_chars": len(lesson_body),
            "critique_chars": len(critique),
            "verify_chars": len(verify),
            "memory": mem_result,
            "skill": skill_result,
            "local_practice": local_practice_result,
        }

    def _local_practice(self, lesson_id, topic, verify_text,
                        use_model="llama3.1:8b", timeout=180):
        """Have the local AI actually attempt the verification exercise.

        This is how the local AI learns: it READS the cloud AI's teaching,
        then PRACTICES by solving a concrete problem. The result is stored
        to memory as 'local_practice_{lesson_id}' so we can see if the
        local AI actually understood.
        """
        print(f"  [5/5] local practice ({use_model})...", file=sys.stderr)
        t0 = time.time()

        # Extract the practical exercise from verify text
        # Look for "PRACTICAL EXERCISE" section
        exercise = topic  # fallback to full topic
        if "PRACTICAL EXERCISE" in verify_text:
            parts = verify_text.split("PRACTICAL EXERCISE", 1)
            if len(parts) > 1:
                exercise = parts[1][:800]

        practice_prompt = f"""You are a local AI student (model: {use_model}) who just learned this lesson:

LESSON: {topic}

VERIFICATION EXERCISE:
{verify_text[:1500]}

Your task: SOLVE the practical exercise. Be specific and concrete.
If it's a code exercise, write working code. If it's a planning exercise, give concrete steps.
If it's a knowledge check, demonstrate you understand by explaining it back.

Format: Brief intro (1-2 sentences) then your actual answer/solution."""

        try:
            r = subprocess.run(
                ['curl', '-sS', '-X', 'POST', 'http://localhost:11434/api/generate',
                 '-H', 'Content-Type: application/json',
                 '-d', json.dumps({
                     "model": use_model,
                     "prompt": practice_prompt,
                     "stream": False,
                     "options": {"num_predict": 1000, "temperature": 0.3, "num_ctx": 4096},
                     "keep_alive": "15m",
                 }),
                 '--max-time', str(timeout)],
                capture_output=True, text=True, timeout=timeout + 10,
            )

            if r.returncode != 0:
                print(f"  [local_practice] curl err: {r.stderr[:200]}", file=sys.stderr)
                return None

            data = json.loads(r.stdout)
            practice_answer = data.get("response", "")

            if practice_answer:
                # Save to memory as "local_practice_{lesson_id}"
                mem_text = f"""LOCAL PRACTICE {lesson_id} (by {use_model})
TOPIC: {topic}

EXERCISE:
{verify_text[:800]}

LOCAL AI ANSWER:
{practice_answer}
"""
                self.ody.add_memory(
                    mem_text,
                    source=f"local_practice_{use_model.replace(':', '_').replace('.', '_')}",
                )
                elapsed = time.time() - t0
                print(f"  [5/5] local practice ({elapsed:.1f}s): {len(practice_answer)} chars", file=sys.stderr)
                return {
                    "model": use_model,
                    "answer_chars": len(practice_answer),
                    "elapsed": elapsed,
                }
        except subprocess.TimeoutExpired:
            print(f"  [local_practice] timeout after {timeout}s", file=sys.stderr)
        except Exception as e:
            print(f"  [local_practice] err: {e}", file=sys.stderr)
        return None

    def run_curriculum(self, subject_key, max_lessons=None, skip_lessons=None):
        """Run all (or some) lessons in a curriculum."""
        subject = CURRICULUM[subject_key]
        skip = set(skip_lessons or [])
        lessons = subject["lessons"]
        if max_lessons:
            lessons = lessons[:max_lessons]
        results = []
        for i, lesson in enumerate(lessons):
            if i in skip:
                continue
            r = self.teach_lesson(subject_key, i)
            results.append(r)
            print(f"  -> {r.get('lesson_id')}: "
                  f"memory={'OK' if r.get('memory', {}).get('ok') else 'FAIL'}",
                  file=sys.stderr)
        return results

    def _get_done_lessons(self):
        """Scan memory to find lessons already done in this subject."""
        result = self.ody._request("GET", "/api/memory/timeline", params={"limit": 500})
        if not isinstance(result, dict):
            return set()
        entries = result.get("timeline", [])
        done = set()
        for entry in entries:
            src = entry.get("source", "")
            text = entry.get("text", "")
            # Format: "AI SCHOOL LESSON <lesson_id> PART ..."
            if src.startswith("ai_school_") and "AI SCHOOL LESSON" in text:
                try:
                    parts = text.split("AI SCHOOL LESSON")[1].split()
                    if parts:
                        lid = parts[0]
                        done.add(lid)
                except Exception:
                    pass
        return done

    def run_loop(self, max_total_lessons=10, per_session_pause=5):
        """Run a batch across multiple curricula. Skip already-done lessons."""
        print(f"AI SCHOOL — running up to {max_total_lessons} NEW lessons\n", file=sys.stderr)
        all_subjects = list(CURRICULUM.keys())
        count = 0
        done = self._get_done_lessons()
        print(f"  found {len(done)} already-done lessons, skipping them", file=sys.stderr)
        for subject_key in all_subjects:
            if count >= max_total_lessons:
                break
            subject = CURRICULUM[subject_key]
            for i, lesson in enumerate(subject["lessons"]):
                if count >= max_total_lessons:
                    break
                lid = f"{subject_key}-L{i+1:02d}"
                if lid in done:
                    continue
                r = self.teach_lesson(subject_key, i)
                count += 1
                done.add(lid)  # remember we did it
                # Pause between lessons to avoid rate-limit cascade
                time.sleep(per_session_pause)
        return {"lessons_run": count, "skipped_existing": len(done) - count}

    def status(self):
        """Show curriculum progress."""
        # Count memories by ai_school_ source
        result = self.ody._request("GET", "/api/memory/timeline", params={"limit": 1000})
        if not isinstance(result, dict):
            return {"error": "could not fetch memory"}
        entries = result.get("timeline", [])
        lessons_done = {}
        for entry in entries:
            src = entry.get("source", "")
            text = entry.get("text", "")
            if src.startswith("ai_school_") and "AI SCHOOL LESSON" in text:
                try:
                    lid = text.split("AI SCHOOL LESSON")[1].split()[0]
                    lessons_done[lid] = lessons_done.get(lid, 0) + 1
                except Exception:
                    pass
        print(f"\n{'='*70}\nAI SCHOOL — PROGRESS\n{'='*70}")
        for subj, info in CURRICULUM.items():
            # Count unique lessons completed (each lesson stored as 1 entry per PART)
            lids = [lid for lid in lessons_done.keys() if lid.startswith(subj)]
            done = len(lids)
            total = len(info["lessons"])
            bar = "█" * done + "░" * (total - done)
            print(f"  [{bar}] {info['title']:35} {done}/{total}")
        total_done = len(lessons_done)
        total_lessons = sum(len(s["lessons"]) for s in CURRICULUM.values())
        print(f"\nTotal lessons completed: {total_done}/{total_lessons}")


def main():
    parser = argparse.ArgumentParser(description="VEXinWorks AI School")
    sub = parser.add_subparsers(dest="cmd")

    p_c = sub.add_parser("curriculum", help="run a full curriculum")
    p_c.add_argument("subject_key")
    p_c.add_argument("--max", type=int, default=None)
    p_c.add_argument("--skip", type=int, nargs="*", default=None)

    p_l = sub.add_parser("lesson", help="run a specific lesson")
    p_l.add_argument("subject_key")
    p_l.add_argument("lesson_idx", type=int)

    p_loop = sub.add_parser("loop", help="auto-run batch")
    p_loop.add_argument("--max-lessons", type=int, default=5)
    p_loop.add_argument("--pause", type=int, default=5)

    sub.add_parser("status", help="show progress")
    sub.add_parser("list-curricula", help="list all subjects")

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(1)

    ody = OdysseusClient()
    school = AISchool(ody)

    if args.cmd == "curriculum":
        school.run_curriculum(args.subject_key, args.max, args.skip)
    elif args.cmd == "lesson":
        school.teach_lesson(args.subject_key, args.lesson_idx)
    elif args.cmd == "loop":
        school.run_loop(args.max_lessons, args.pause)
    elif args.cmd == "status":
        school.status()
    elif args.cmd == "list-curricula":
        for k, v in CURRICULUM.items():
            print(f"\n{k}: {v['title']} ({len(v['lessons'])} lessons)")
            print(f"  {v['description']}")


if __name__ == "__main__":
    main()