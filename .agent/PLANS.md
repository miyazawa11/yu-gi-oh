# ExecPlan — observation-only Master Duel advisor

## Goal and boundaries

Observe → understand → decide → recommend while a human operates Master Duel. Definition of Done requires Windows live capture, actual game LP/turn/phase/field/card recognition, replay through the same pipeline, event history, supported legal actions, structured decisions, UI, passing tests and measured evaluation. Do not claim completion from synthetic fixtures.

## Inspection (2026-10-04)

`/workspace/yu-gi-oh` is an unborn Git checkout with no project files, commits, manifests, CI or instructions. Read-only origin access previously returned no refs; requested `main` does not exist. Host is Linux, Python 3.12; Tesseract and FFmpeg exist. Windows desktop/game and labeled game recordings are unavailable. No API integration is required for the deterministic first implementation.

## Tasks

| Task | Purpose | Dependencies | Acceptance | Validation | Status |
| --- | --- | --- | --- | --- | --- |
| 0 | Architecture and decisions | inspection | required design docs before code | document review | complete |
| 1 | Live/replay capture and benchmark | Python, Windows for live | bounded capture interface, frame times, 10 FPS target | replay tests; Windows benchmark for dxcam/MSS | replay/polling implemented; live acceptance blocked |
| 2–3 | Regions and typed state | 0 | aspect-aware regions, explicit unknown/confidence/provenance | geometry/schema tests | complete for configured observations |
| 4 | LP/turn/phase extraction | calibrated UI templates/OCR | labeled real-game accuracy >=95% per supported field | fixture evaluator; real-game gate | calibrated framework and synthetic tests complete; real accuracy blocked |
| 5 | Scoped card recognition | consented 20–50 card reference crops | similarity, unknown/rejection, per-card precision/recall | synthetic algorithm tests then real game holdout | blocked on data |
| 6–7 | Tracking and card database | typed state | conservative events, SQLite metadata abstraction | transition/database tests | complete for observable changes; causal event types deferred |
| 8–9 | Actions and deterministic decision | observed selectable UI | no unsupported action, structured recommendation | positive/negative rule tests | UI-supported baseline complete; bindings/effect rules/strategy incomplete |
| 10–12 | Advisor, replay, instrumentation | core pipeline | separate local UI, bounded frame processing, saved metrics | HTTP demo and replay evaluation | synthetic integration complete; real game acceptance blocked |
| Real deployment | End-to-end live game | Windows 11, Master Duel, calibrated labeled frames | DoD and capture/FPS/CPU/GPU/drop measurements | Windows acceptance run | blocked on hardware/data |

## Decision log

- D001: Python 3.12 package with OpenCV/numpy and Pydantic; standard-library HTTP UI and SQLite avoid web frameworks. Tesseract is optional local OCR, never a network dependency.
- D002: dxcam (Desktop Duplication) primary Windows candidate; MSS (GDI) comparison baseline. WGC/OBS remain candidates if exclusive fullscreen or protected capture fails. Selection is provisional until real measurements; report unmeasured GPU/latency as null.
- D003: Calibration is explicit normalized viewport-relative geometry plus crop templates. No invented Master Duel coordinates ship as validated defaults. Aspect ratio uses content viewport/letterboxing. Unknown layout is a blocker to perception, not a guessed board.
- D004: Initial rules expose calibrated visible selectable buttons only; do not claim an exhaustive rules engine or infer summon legality from phase alone. Fail closed on unknown turn/phase and stale observations.
- D005: Synthetic fixtures test integration and algorithms only. Real recognition gate blocks Phase 5 deployment, but independent capture, database, replay, UI and rule infrastructure proceed.
- D006: No LLM initially: zero API calls/cost, deterministic ranking with confidence. Executor protocol stays unimplemented.
- D007: Save calibration, frames and replay artifacts outside source/ignored directories; never download arbitrary copyrighted card art automatically.
- D008: Tesseract forced 3× upscaling misread synthetic 5200 as9200. Preserve larger crops and require grayscale/binary agreement >=0.90. Regression fixtures cover this failure; this is not evidence of real-game OCR accuracy.
- D009: dxcam latest-frame wait can block indefinitely on unchanged desktop according to pinned package source. Use synchronous grab polling with caller scheduling; mock tests cover no-frame behavior. Windows verification still required.
- D010: Use Windows opencv-python and Linux opencv-python-headless with OS markers, since dxcam depends on the former and two cv2 distributions conflict. Lock conditional capture dependencies too.
- D011: Per-region frame gating prioritizes small LP/action UI changes. MPEG compression noise can cause extra processing; count actual work rather than require exactly one processing pass per scene.
- D012: User wants Windows checks on their local PC. This session has no local PC connection tool; provide a source ZIP and local Codex handoff instructions rather than claim access or install remote control.

## Execution evidence and remaining work

Python3.12 virtual environment installed via scripts/setup.sh and repeated successfully; pip check passed. Tesseract5.5.0 available locally. Synthetic evaluator:4 independently specified scenarios, all labeled state/action/decision outputs correct, real_perception_gate_passed=false. MP4 replay:12 frames,5 processed with per-region gating; all4 scenes recognized, events persisted. Synthetic mean pipeline compute latency approximately1ms on this host, not live screen latency. API calls/cost:0.

Separate loopback HTTP service was started and functionally requested: HTML contained Advisor UI, state contained8000 LP, recommendation contained NORMAL_SUMMON. Tests exercise stale advice removal, replay looping/reset, ambiguous templates, unknown cards, stale observations, wrong ground truth, schema/geometry, SQLite, OCR and mocked Windows polling. Final test count/evidence is recorded in evaluation/development-validation.json.

Windows capture comparisons, exclusive fullscreen/HDR/multi-monitor behavior, real-game ground truth, scoped actual card recognition, card/target binding, effect legality, and strategic choices remain unresolved. No final Goal completion claim. Code is in the workspace; no GitHub push has been performed. See docs/windows-handoff.md for the next executable path.

Source ZIP was extracted to /tmp/master-duel-advisor-handoff-check. A new virtual environment was installed through the included script, pip check passed, all64 tests passed and the synthetic demo passed. This validates Linux portability, not Windows installation. install_script/start_skill saved to the environment draft; publication is not performed or verified.
