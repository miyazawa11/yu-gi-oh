"""画面を目視確認した操作候補で実ルールを評価する補助テスト。入力は行わない。"""
import argparse
import json
import time
from pathlib import Path
from master_duel_advisor.models import Action, GameState, Observation
from master_duel_advisor.strategy_rules import load_planner

parser = argparse.ArgumentParser()
parser.add_argument("rule")
parser.add_argument("--turn", type=int, required=True)
parser.add_argument("--player", choices=["self", "opponent"], required=True)
parser.add_argument("--phase", required=True)
parser.add_argument("--prompt", default="none")
args = parser.parse_args()
p = load_planner(Path("data/decks/thunder-dragon-review/strategy-book.json"))
r = next(r for r in p.book.rules if r.id == args.rule)
at = time.monotonic()
def obs(value):
    return Observation(value=value, confidence=1, observed_at=at, source="assistant_visual_review_not_automatic_perception")
a = Action(type=r.type, card_id=r.card_id, target=r.target, source_region=r.source_region, observed_at=at, confidence=1)
s = GameState(sequence=0, captured_at=at, turn=obs(args.turn), turn_player=obs(args.player),
              phase=obs(args.phase), prompt=obs(args.prompt), terminal=obs(False), animation=obs(False), visible_actions=[a])
p.observe(s)
started = time.perf_counter()
decision = p.decide(s, [a])
record = {"mode":"visual_assisted_rule_test", "automatic_perception":False, "input_sent_by_script":False,
          "decision_ms":(time.perf_counter()-started)*1000, "state":s.model_dump(mode="json"),
          "recommendation":decision.model_dump(mode="json"), "plan":p.snapshot()}
path = Path("evaluation/free-duel-visual-assisted.jsonl")
path.parent.mkdir(parents=True, exist_ok=True)
with path.open("a", encoding="utf-8") as f:
    f.write(json.dumps(record, ensure_ascii=False)+"\n")
print(json.dumps(record, ensure_ascii=False))
