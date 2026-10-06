import io
import json
from types import SimpleNamespace

import pytest

from master_duel_advisor.local_strategy import LocalStrategy
from master_duel_advisor.llm_fallback import StrategyChoice
from master_duel_advisor.cli import parser, enable_chatgpt


@pytest.mark.parametrize("url", ["https://127.0.0.1", "http://example.com", "http://localhost@evil.com", "http://localhost/path"])
def test_remote_endpoint_rejected(url):
    with pytest.raises(ValueError):
        LocalStrategy("test", url)


def test_structured_request_and_completion():
    provider = LocalStrategy("test")
    choice = {"type": "CONFIRM", "source_region": "action.ok", "card_id": None,
              "target": None, "confidence": .99, "reason": "確認"}
    requests = []
    def open_request(request, timeout):
        requests.append(json.loads(request.data))
        return io.BytesIO(json.dumps({"done": True, "done_reason": "stop",
            "message": {"content": json.dumps({"index": 0, "confidence": .99})}}).encode())
    provider.opener = SimpleNamespace(open=open_request)
    result = provider({"visible_actions": [choice]}, StrategyChoice.model_json_schema())
    assert result["source_region"] == choice["source_region"]
    assert requests[0]["think"] is False
    assert requests[0]["format"]["required"] == ["index", "confidence"]
    provider.opener = SimpleNamespace(open=lambda *a, **k: io.BytesIO(b'{"done":true,"done_reason":"length"}'))
    with pytest.raises(ValueError, match="未完了"):
        provider({"visible_actions": [choice]}, {})


def test_cli_local_provider_and_exclusive_selection():
    args = parser().parse_args(["run", "--rect=0,0,1280,720", "--calibration", "a", "--database", "b", "--local-model", "test"])
    pipeline = SimpleNamespace(strategy_fallback=None)
    enable_chatgpt(pipeline, args)
    assert isinstance(pipeline.strategy_fallback.provider, LocalStrategy)
    pipeline.strategy_fallback.close()
    args.chatgpt = True
    with pytest.raises(ValueError, match="同時"):
        enable_chatgpt(pipeline, args)


@pytest.mark.parametrize("index", [-1, 1, True, "0"])
def test_invalid_index_is_rejected(index):
    provider = LocalStrategy("test")
    provider.opener = SimpleNamespace(open=lambda *a, **k: io.BytesIO(json.dumps({
        "done": True, "done_reason": "stop", "message": {"content": json.dumps({
            "index": index, "confidence": 1})}}).encode()))
    with pytest.raises(ValueError, match="候補番号"):
        provider({"visible_actions": [{}]}, {})
