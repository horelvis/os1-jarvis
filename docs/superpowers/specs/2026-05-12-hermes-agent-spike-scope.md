# Hermes-Agent spike — scope (NOT YET EXECUTED)

**Date scoped:** 2026-05-12
**Status:** Pending. To be run in parallel with v2 UI redesign implementation.
**Repo to evaluate:** https://github.com/nousresearch/hermes-agent

---

## Why this spike

The Samantha of the film is not just a presence — she manages emails, edits Theodore's book, schedules things, takes initiatives. CLAUDE.md §1's "not an agent" framing was a v1 scope restriction, not a permanent identity claim.

Hermes-Agent (NousResearch, MIT, 147 K stars, v0.13.0 May 2026) is a mature agentic runtime that already implements the things v3 would need: tools, multi-platform messaging, cron, MCP integration, voice transcription, persistent multi-tier memory, "skills" (self-improving procedural memory), and personalities.

Before designing v3 from scratch, we evaluate whether Samantha could be **built on top of Hermes-Agent** rather than alongside it.

## What we already know (no spike needed)

From the README and project overview (already read 2026-05-12):

- LLM-agnostic via OpenAI-compatible config — our llama-server fits.
- 40+ tools, 7 terminal backends, MCP integration.
- Memory: FTS5 session search + Honcho-based user profiles + agent-curated nudges + cross-session LLM-summarized recall.
- Personalities: reusable persona configs.
- Multi-platform gateways: Telegram / Discord / Slack / WhatsApp / Signal / Email.
- Cron scheduler with built-in task automation.
- Subagents with RPC-based tool calls.
- Dependencies: Python 3.11 + Node.js + ripgrep + ffmpeg + Git. Installed via Astral's `uv`.
- Hot deploy targets: local, Docker, SSH, Modal, Daytona, Vercel Sandbox.

## What the spike must answer

### A. Conceptual fit (1 day)

1. **Personality as Samantha** — can the Hermes "personality" config carry SYSTEM_PROMPT v2 + the v3 agentic extensions? Is the resulting Samantha-on-Hermes recognizably Samantha?
2. **Single-user kiosk model** — Hermes is designed for cross-platform use. How clean is "kiosk-only" deployment? Can we strip the messaging gateways entirely without breaking the runtime?
3. **Memory compatibility** — can we point Hermes at our existing `~/.samantha/memory/` (ChromaDB), or does it want its own format? If it wants its own, what's the migration path?
4. **"Samantha nunca olvida"** — Hermes has memory but unclear if it's append-only. Read source / test for deletion semantics. Same evaluation criterion as the Mem0 spike.

### B. Practical fit (1 day)

5. **Local-only runtime** — Hermes claims "no lock-in, pure Python". Test that we can run it 100% offline against our llama-server. No phoning home, no cloud calls.
6. **Footprint on a kiosk** — Python 3.11 + Node.js + ripgrep + ffmpeg + Git. Acceptable for a mini-PC? Compare with our current backend ~50 MB venv.
7. **Tool subset** — can we limit Hermes to only the tools Samantha v3 actually needs (email read, calendar read, no shell, no code exec)? Whitelist-only mode?
8. **Performance** — Hermes' agent loop on top of Qwen3-8B-Q8 at 25-30 tok/s. Per-turn latency. Whether the loop's tool reasoning adds 2-3 LLM round-trips before responding (would feel slow).

### C. Spike deliverable

A markdown report at `docs/superpowers/specs/hermes-agent-spike/REPORT.md` following the Mem0 spike pattern:
- TL;DR with verdict
- Setup that worked
- Test results with measurements
- The good, the bad, the deferrable
- Concrete recommendation: adopt for v3 / partial adoption / build our own

## What the spike is NOT

- **Not a v2 dependency.** v2 ships with the architecture in the main spec, regardless of this evaluation's outcome.
- **Not a feature spec.** It does not define "Samantha v3 capabilities" — it evaluates a foundation. The capability list (what Samantha can DO in v3) is a separate brainstorm.
- **Not a port.** No code changes to Samantha during the spike. Hermes is evaluated in isolation in a separate workspace.

## Pre-conditions for executing the spike

- v2 implementation in progress or complete (so the spike doesn't compete for attention with active impl work).
- llama-server still available at 192.168.100.58 (or a local equivalent).
- A free 1-2 day block.

## Reference

- `docs/superpowers/specs/2026-05-12-ui-redesign-design.md` — current v2 spec.
- `docs/superpowers/specs/mem0-spike/REPORT.md` — methodology to mimic.
- https://github.com/nousresearch/hermes-agent — the target.
