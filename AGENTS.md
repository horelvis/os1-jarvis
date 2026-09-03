# AGENTS.md

**Read [`CLAUDE.md`](CLAUDE.md).** It is this project's single source of
truth, for every agent, whatever the harness.

This file used to hold a full specification of its own — "Samantha
Project Specification (v3)" — and by 2026-09-03 it described a system
that had not existed for months: a Chromium kiosk, a FastAPI backend
and a React frontend, all of them retired in August and deleted on
2026-09-03. A second source of truth is only useful while it is true,
and this one had stopped being so without anyone noticing, which is the
strongest argument against keeping two.

What runs now is a GTK4 strip on the desktop talking to a Hermes Agent
gateway, and he is called JARVIS. CLAUDE.md §0 is the shortest true
description of it.

The old contents are in the history: `git log --follow -- AGENTS.md`.
