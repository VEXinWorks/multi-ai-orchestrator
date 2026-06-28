# VEXinWorks Multi-AI Orchestrator

Coordinates 3 cloud AIs (GLM-5.2, minimax-m3, nemotron-3-ultra) with local Ollama
models and a self-improving local agent loop.

## Components

### `vexin_agent.py` (local agent runner)
Talks to Odysseus (memory, skills, RAG) and Ollama (inference). Can teach itself
by adding skills/memories to Odysseus.

### `multi_ai_orchestrator.py` (multi-AI coordinator)
Routes tasks to the right AI:
- Code tasks → nemotron-3-ultra (NVIDIA)
- Research/analysis → GLM-5.2 (Zhipu)
- Default chat → minimax-m3 (MiniMax)

Has a `self-improve` cycle that asks all 3 cloud AIs to review local agent code
and stores proposals in Odysseus memory for manual review (NEVER auto-applies).

## Safety guards

- HTTP retry with exponential backoff (3 attempts, max ~3s total wait)
- VRAM guard: refuses to load local models that would exceed 10 GB used
- Disk guard: refuses operations if <50 GB free at /home
- Cloud calls budgeted: max 3 per turn, 10 per self-improve cycle
- Self-rewrite: NEVER auto-applies AI-suggested code changes; stores diff in memory

## Usage

```bash
# Single AI delegation (auto-routed)
./multi_ai_orchestrator.py delegate "your task here"

# Force local model
./multi_ai_orchestrator.py delegate "your task" --local

# Consensus (all 3 vote)
./multi_ai_orchestrator.py consensus "your question"

# Self-improvement cycle
./multi_ai_orchestrator.py self-improve

# Status
./multi_ai_orchestrator.py status

# Local agent (separate tool)
./vexin_agent.py self-test
./vexin_agent.py chat "your question"
./vexin_agent.py remember -t "fact to remember"
```
