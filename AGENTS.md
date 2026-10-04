# Development contract

Build a Windows 11 / Python 3.12 observation-only Master Duel advisor. Read `.agent/PLANS.md` before implementation and update progress, evidence, and decisions after meaningful changes.

- Never send mouse/keyboard input to the game; never read game memory, inject DLLs, inspect packets, or bypass anti-cheat.
- Capture only visible pixels. Never infer hidden opponent cards. Unknown observations remain unknown with provenance and confidence.
- Separate capture, perception, state, rules, decisions, and presentation. Executor is an interface only; no Master Duel executor implementation.
- Prefer deterministic CV/OCR; do not call a vision API for every frame. External model use requires explicit opt-in and a budget.
- Test offline with deterministic fixtures and replay. Synthetic accuracy is not real-game accuracy. Do not mark Windows performance or real-game recognition complete without measured evidence.
- Rules only recommend actions backed by calibrated visible action UI. Partial state does not prove complete Yu-Gi-Oh legality.
- Keep documents consistent with implementation. Run `python -m pytest` and the documented demo/evaluation before reporting verified capabilities.
- Use the existing isolated checkout; do not create worktrees unless requested.

The user's development request authorizes creating source, tests, dependency files, and documentation. This is application development, distinct from the earlier onboarding-only scope.
