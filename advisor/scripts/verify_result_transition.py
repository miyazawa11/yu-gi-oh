"""入力後の別画面で誤った再クリック候補が消えることを検証。"""
import time
from pathlib import Path
from master_duel_advisor.capture import Frame
from master_duel_advisor.cli import build_pipeline
from master_duel_advisor.image_io import read_image, write_image
from master_duel_advisor.pipeline import save_json

out = Path("artifacts/result-ui-validation")
pixels = read_image("artifacts/live-validation-001.png")
if pixels is None or pixels.mean() < 1:
    raise ValueError("入力後の実画面がありません")
write_image(out/"after.png", pixels)
pipeline = build_pipeline(out/"calibration.json",out/"cards.sqlite3",ui_rules=out/"ui-rules.json")
try:
    result = pipeline.process(Frame(pixels=pixels,sequence=1,captured_at=time.monotonic()))
    assert result["recommendation"]["action"] is None
    save_json(out/"after-recognition.json",result)
    save_json(out/"validation.json",{
        "kind":"limited_real_ui_validation","before":"source.png","after":"after.png",
        "local_recognition":"CONFIRM action.result_ok confidence=1.0",
        "input_transport":"computer-use @oai/sky", "input_point_window":[640,679],
        "observed_transition":"duel_result -> free_match_menu",
        "old_candidate_absent_after":True,"native_agent_loop_live_verified":False,
        "accuracy_holdout_completed":False,
        "limitations":"同一画面から校正したOKの1操作。一般精度・常駐ループ・実ホットキーの受入試験ではない"})
    print("別画面で終了OK候補が消えることを確認しました")
finally: pipeline.perception.cards.close()
