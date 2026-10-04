# Evaluation contract

Automated tests cover schema, geometry, ambiguity/rejection, database, temporal transitions, action filtering, structured decisions, frame gate, replay and HTTP UI. Synthetic end-to-end fixtures run via `python -m master_duel_advisor demo --output artifacts/demo`; reported dataset kind must remain synthetic.

Ground truth JSON lists image paths and expected observation values, including explicit nulls and action types. Evaluator measures per-field accuracy, known-value precision/recall and state exact accuracy; macro aggregates do not replace per-field thresholds. Missing predictions are failures for known ground truth. Negative/unknown cases measure unsafe false positives. Never evaluate labels copied from predictions. Save current results to evaluation/results.json with run timestamp, data kind and sample counts.

Capture benchmarks report received/unique FPS, read-time mean/p95, CPU usage, estimated missed scheduled samples and elapsed time. GPU use and true screen-to-result latency are null unless independently measured. Replay throughput is not live FPS. Target minimum 10 unique FPS, aim 30 on Windows. Compare dxcam/MSS with same scene, rectangle, duration and fullscreen/windowed conditions; then investigate WGC/OBS if needed. Counters never equate duplicate frames with captured FPS.

Pipeline records capture/read, perception, decision and total compute latency plus zero API calls/cost. Real end-to-end latency requires an external timestamped screen change experiment. Completion requires Windows live validation and held-out real Master Duel samples; neither is available here.
