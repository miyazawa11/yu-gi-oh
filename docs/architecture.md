# Architecture

`CaptureSource → FrameGate → calibrated Perception → GameState → Tracker → Rules → Decision → local Advisor UI`

Capture sources share frame pixels, monotonic receipt time and optional media timestamp. dxcam and MSS capture a user-selected desktop rectangle on Windows; replay uses OpenCV VideoCapture. No game handles, input control, process access or networking to the game is used. A bounded synchronous loop samples current live frames rather than queueing stale work. Global and per-region visual change detection plus periodic refresh reduce perception frequency. Every processed state replaces the previous observation: failed recognition cannot retain a stale known value. dxcam uses synchronous grab polling because its latest-frame wait can block indefinitely on a static desktop.

Perception uses a calibration manifest with normalized regions, template exemplars, LP OCR and scoped card reference crops. Templates can represent turn, phase and action UI. Unmatched or ambiguous templates return unknown. Zone crops can identify known visible face-up cards; unmatched crops cannot establish emptiness. The local SQLite database provides metadata, not rules extracted automatically from effect prose.

Only explicitly recognized action buttons enter rule filtering. Unknown turn/phase, insufficient confidence and stale observations suppress recommendations. Decisions choose among supported observed candidates and always return JSON with action, target, confidence, reason and recognition status. This is a conservative subset, not a complete simulator. An Executor protocol permits future authorized integrations; no executor is implemented.

Separate loopback HTTP UI polls the latest snapshot. Capture should exclude the advisor window to avoid feedback. API cost is zero in the initial implementation. Timing measures compute and frame receipt; it does not measure physical display-to-photon latency. See evaluation docs for data and deployment gates.
