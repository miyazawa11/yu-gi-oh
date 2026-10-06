"""既知保存画像でUI bank追加コストを計測。キャプチャ/UI入力/E2E速度の証明ではありません。"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import time

from master_duel_advisor.action_evidence import ActionEvidenceDetector, CaptureContext
from master_duel_advisor.capture import Frame
from master_duel_advisor.image_io import read_image
from master_duel_advisor.ui_evidence_bank import UiEvidenceBank

ROOT = Path(__file__).resolve().parents[1]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, default=ROOT/'artifacts/baseline-tester/ASH_INSPECT_PREFLIGHT_v3_20261006/frame.png')
    parser.add_argument('--iterations', type=int, default=20)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--profile-base', type=Path, default=ROOT/'artifacts/ash-normal-inspect-calibration-v4')
    args = parser.parse_args()
    if args.iterations < 10: raise ValueError('microbenchは10回以上必要です')
    bank = UiEvidenceBank(args.profile_base/'ui-bank.json')
    legacy = ActionEvidenceDetector(ROOT/'artifacts/ash-normal-inspect-calibration-v3/readonly-detector-support/detector.json')
    frame = Frame(read_image(args.image),0,0,capture_source='saved_image')
    context = CaptureContext(mode='offline_saved_image',capture_source='saved_image',
        captured_at_clock='unspecified_zero_not_capture_time',frame_seq_semantics='manifest_index_not_capture_sequence')
    bank.recognize(frame,context,'solar-menu-v2'); legacy.recognize(frame,context,'solar-menu-v2')
    rows = []
    for index in range(args.iterations):
        row = {'index': index}
        for name, detector in ([('legacy',legacy),('bank',bank)] if index%2 == 0 else [('bank',bank),('legacy',legacy)]):
            start = time.perf_counter(); evidence = detector.recognize(frame,context,'solar-menu-v2')
            row[name+'_button_ms'] = (time.perf_counter()-start)*1000
            row[name+'_detected'] = evidence.candidate_type is not None
            if name == 'bank': box = evidence.evidence_bbox
        start = time.perf_counter(); hand = bank.match_hand(frame.pixels,box)
        row['bank_hand_ms'] = (time.perf_counter()-start)*1000
        row['bank_hand_detected'] = hand[0] == 'true'
        if bank.last_hand_diagnostic is not None:
            row['hand_diagnostic'] = bank.last_hand_diagnostic
        rows.append(row)
    summary = {key: {'average_ms': statistics.mean(r[key] for r in rows),
        'p50_ms': statistics.median(r[key] for r in rows), 'max_ms': max(r[key] for r in rows)}
        for key in ['legacy_button_ms','bank_button_ms','bank_hand_ms']}
    report = {'schema':'inspect-ui-bank-microbench-v4','input_count':0,'e2e_count':0,'offline_clock':0,
        'image':str(args.image),'image_sha256':hashlib.sha256(args.image.read_bytes()).hexdigest(),
        'iterations':args.iterations,'legacy_detector_sha256':legacy.sha256,'bank_sha256':bank.sha256,
        'notice':'既知画像の追加認識コスト。手札探索/2表示参照により正確性coverageを回復、速度改善主張無し',
        'summary':summary,'rows':rows}
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False))
