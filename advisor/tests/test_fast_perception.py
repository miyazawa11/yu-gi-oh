from dataclasses import replace

import numpy as np
import pytest

from master_duel_advisor.capture import Frame


def test_unchanged_regions_reuse_recognition_with_current_timestamps(pipeline, assets):
    from master_duel_advisor.image_io import read_image
    from master_duel_advisor.perception import TemplateMatcher
    from unittest.mock import patch
    import json
    dataset = json.loads(assets["dataset"].read_text(encoding="utf-8"))
    image = read_image(str(assets["dataset"].parent / dataset["samples"][0]["image"]))
    first = Frame(image, 10, 0)
    pipeline.perception.process(first)
    with patch.object(TemplateMatcher, "match", side_effect=AssertionError("再認識は不要")):
        current = pipeline.perception.process(replace(first, captured_at=11, sequence=1))
    assert pipeline.perception.cache_hits == len(pipeline.perception.calibration.regions)
    assert current.phase.observed_at == 11
    assert all(a.observed_at == 11 for a in current.visible_actions)
    pipeline.perception.process(Frame(np.zeros_like(image), 12, 2))
    assert pipeline.perception.recognized_regions > 0


def test_verified_frame_skips_recognition_but_runs_decision(pipeline, assets):
    import json
    import time
    from unittest.mock import patch
    from master_duel_advisor.image_io import read_image
    dataset = json.loads(assets["dataset"].read_text(encoding="utf-8"))
    pixels = read_image(assets["dataset"].parent / dataset["samples"][0]["image"])
    frame = Frame(pixels, time.monotonic(), 1)
    state = pipeline.perception.process(frame)
    with patch.object(pipeline.perception, "process", side_effect=AssertionError("二重認識")):
        result = pipeline.process(frame, observed_state=state)
    assert result["state"] == state.model_dump(mode="json")
    assert result["metrics"]["perception_reused"]
    assert result["metrics"]["perception_ms"] == 0
    assert result["recommendation"]["action"] is not None
    with pytest.raises(ValueError, match="一致"):
        pipeline.process(replace(frame, sequence=2), observed_state=state)
    with pytest.raises(ValueError, match="一致"):
        pipeline.process(replace(frame, captured_at=frame.captured_at+1), observed_state=state)
