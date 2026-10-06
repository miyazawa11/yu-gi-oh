"""ChatGPTプラン枠でJSON Schema応答を1回検証。ゲーム入力はしません。"""
import argparse
from pathlib import Path
import time

from master_duel_advisor.chatgpt_strategy import ChatGPTStrategy
from master_duel_advisor.llm_fallback import StrategyChoice
from master_duel_advisor.models import Action,GameState
from master_duel_advisor.pipeline import save_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model",required=True)
    args=parser.parse_args()
    at=time.monotonic()
    action=Action(type="CONFIRM",source_region="action.connection_test",confidence=1,observed_at=at)
    state=GameState(sequence=0,captured_at=at,visible_actions=[action])
    provider=ChatGPTStrategy(model=args.model)
    started=time.perf_counter()
    try:
        choice=StrategyChoice.model_validate(provider(state.model_dump(mode="json"),StrategyChoice.model_json_schema()))
    except Exception:
        print(provider.auth.transport.last_response_metadata)
        raise
    if (choice.type,choice.source_region,choice.card_id,choice.target)!=(action.type,action.source_region,None,None):
        raise ValueError("接続テストの候補と応答が一致しません")
    report={"model":args.model,"oauth_plan_inference_verified":True,"schema_valid":True,
            "request_ms":(time.perf_counter()-started)*1000,"game_input":False,"api_key_used":False}
    save_json(Path("artifacts/chatgpt-inference-validation.json"),report)
    print(report)


if __name__=="__main__": main()
