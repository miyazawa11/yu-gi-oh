# Perception and calibration

Calibration manifest selects a viewport rectangle in normalized frame coordinates. Each region is normalized within that viewport, making scaling and letterboxing explicit; do not stretch a 16:9 layout across another aspect ratio. Use actual captures for each UI/language/theme mode.

Supported regions: self/opponent LP, turn player/number, phase, hand count, self/opponent monster and spell/trap zones, extra-monster zones, graveyard, banished, extra deck and action/selection UI. Region names describe semantic observations, not measured default coordinates. Save screenshots through capture then inspect them and define calibrated crops. A validate-calibration command checks geometry and exemplar assets.

Numeric fields use local Tesseract CLI with a digits-only whitelist, parse the entire recognized token and enforce bounds. Original grayscale and thresholded renderings must agree with confidence >=0.90; only crops shorter than40 pixels are enlarged. Missing OCR or ambiguous output produces unknown. This consensus reduces observed synthetic errors but does not guarantee real-game correctness. Template classification uses resized normalized pixel similarity, absolute threshold and runner-up margin. Multiple exemplars may share a label. High visual similarity is a heuristic confidence, not a calibrated probability. Visible action templates must include a selectable appearance and distinguish disabled buttons; stale/ambiguous/nonactive UI must be rejected through dataset evaluation.

The initial implementation is a calibrated framework, not a trained universal Master Duel detector. Real-game fixture evaluation >=95% field accuracy and negative-action cases is required before reliable live advice. Synthetic templates cannot satisfy this gate.
