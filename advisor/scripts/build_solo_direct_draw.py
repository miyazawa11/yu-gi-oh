"""既存Draw陽性を直接typed goalへ結合。画像assetや閾値は変更しません。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

from master_duel_advisor.strategy_rules import StrategyBook

ROOT=Path(__file__).resolve().parents[1]


def build(output):
    source=ROOT/"artifacts/solo-basic-calibration-v4";output=Path(output).resolve()
    if (output.exists() or not output.is_relative_to(ROOT.resolve()) or output.is_relative_to(source.resolve())
            or output.is_relative_to((ROOT/"artifacts/baseline-tester").resolve())):
        raise ValueError("新規workspace校正先/入力非重複のみです")
    fixed=json.loads((ROOT/"evaluation/solo-basic-fixed-v3.json").read_text(encoding="utf-8"))
    for name,sha in {**fixed["files"],**fixed["recognition_components"]["files"]}.items():
        path=Path(name).resolve()
        if path.is_relative_to(source.resolve()) and hashlib.sha256(path.read_bytes()).hexdigest()!=sha:
            raise ValueError("旧校正asset hash不一致")
    book=json.loads((source/"solo-route.json").read_text(encoding="utf-8"))
    for rule in book["rules"]:
        goal=rule.get("logical_response_decline")
        if goal and goal["kind"]=="opponent_turn_end":
            goal["evidence_mode"]="observed_self_draw"
            rule["expected_prompts"]=[];rule["expected_facts"]={"response.outcome.self_draw":"true"}
    StrategyBook.model_validate(book)
    shutil.copytree(source,output)
    (output/"solo-route.json").write_text(json.dumps(book,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    # 既存trialsは目的IDのlist。load_trialsが新bookから明示goal/modeを取得します。
    return book


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args();build(args.output);print(args.output)
