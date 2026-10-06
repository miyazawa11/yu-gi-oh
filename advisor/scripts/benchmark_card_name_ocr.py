"""選択UIの名前ROIだけをローカルOCRする実験。入力・runtime統合なし。"""
from pathlib import Path
import argparse
import csv
import hashlib
import io
import json
import sqlite3
import subprocess
import time
import unicodedata

import cv2
import numpy as np

from master_duel_advisor.image_io import read_image


def normalize_name(text):
    # OCRの語分割空白と全半角だけを正規化。文字補正・部分一致・fuzzyは禁止。
    return ''.join(unicodedata.normalize('NFKC', text).split())


def load_aliases(database):
    aliases = {}
    with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as connection:
        for cid, raw in connection.execute('SELECT card_id,data FROM cards'):
            name = json.loads(raw)['name']
            aliases.setdefault(normalize_name(name), set()).add(cid)
    return aliases


def resolve_name(text, confidence, aliases, minimum=.90):
    name = normalize_name(text)
    ids = aliases.get(name, set())
    if not name: return None, 'blank_ocr'
    if not ids: return None, 'unknown_exact_alias'
    if len(ids) != 1: return None, 'ambiguous_exact_alias'
    if confidence < minimum: return None, 'low_ocr_confidence'
    return next(iter(ids)), None


def render_roi(pixels, roi, variant, scale):
    x, y, width, height = roi
    if min(x, y) < 0 or min(width, height) <= 0 or x+width > pixels.shape[1] or y+height > pixels.shape[0]:
        raise ValueError('名前ROIが画像内にありません')
    crop = pixels[y:y+height, x:x+width]
    crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    if variant != 'raw':
        crop = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        if variant == 'otsu': _, crop = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        crop = 255-crop  # 白い名前文字を白背景の黒文字へ。
    return cv2.copyMakeBorder(crop, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255 if variant != 'raw' else (255,255,255))


def parse_tsv(raw):
    words, confidence = [], []
    for row in csv.DictReader(io.StringIO(raw), delimiter='\t'):
        if row.get('level') == '5' and row.get('text', '').strip():
            words.append(row['text'])
            confidence.append(max(0, float(row['conf']))/100)
    return ''.join(words), min(confidence, default=0)


def benchmark(samples, database, binary, tessdata, *, variant='gray', scale=3, psm=7, repeats=3, minimum=.90):
    aliases = load_aliases(database)
    rows = []
    for sample in samples:
        path = Path(sample['path'])
        if hashlib.sha256(path.read_bytes()).hexdigest() != sample['sha256']:
            raise ValueError('名前評価画像hash不一致')
        pixels = read_image(path)
        if pixels is None: raise ValueError('画像を読み込めません')
        for repeat in range(repeats):
            start = time.perf_counter()
            rendering = render_roi(pixels, sample['roi'], variant, scale)
            ok, png = cv2.imencode('.png', rendering)
            if not ok: raise ValueError('名前ROIのPNG変換に失敗しました')
            prepared = time.perf_counter()
            text, confidence, cid, reason, stderr = '', 0, None, None, ''
            try:
                result = subprocess.run([str(binary), 'stdin', 'stdout', '--tessdata-dir', str(tessdata), '-l', 'jpn',
                                         '--oem', '1', '--psm', str(psm), '-c', 'tessedit_create_tsv=1'], input=png.tobytes(),
                                        capture_output=True, timeout=3, check=False)
                engine_end = time.perf_counter()
                stderr = result.stderr.decode('utf-8', errors='replace')
                if result.returncode != 0: reason = 'tesseract_exit_' + str(result.returncode)
                else:
                    text, confidence = parse_tsv(result.stdout.decode('utf-8'))
                    cid, reason = resolve_name(text, confidence, aliases, minimum)
            except (OSError, subprocess.TimeoutExpired) as exc:
                engine_end = time.perf_counter(); reason = type(exc).__name__
            end = time.perf_counter()
            expected = sample['expected_cid']
            raw_aliases = aliases.get(normalize_name(text), set())
            exact_text_cid = next(iter(raw_aliases)) if len(raw_aliases) == 1 else None
            rows.append({'path': str(path), 'sha256': sample['sha256'], 'split': sample['split'], 'roi': sample['roi'],
                         'repeat': repeat, 'text': text, 'normalized_name': normalize_name(text), 'confidence': confidence,
                         'cid': cid, 'expected_cid': expected, 'correct': cid == expected,
                         'exact_text_cid': exact_text_cid, 'exact_text_match': expected is not None and exact_text_cid == expected,
                         'groundtruth': sample.get('groundtruth'),
                         'false_alias': cid is not None and cid != expected, 'failure_reason': reason, 'stderr': stderr,
                         'prepare_ms': (prepared-start)*1000, 'engine_ms': (engine_end-prepared)*1000,
                         'parse_lookup_ms': (end-engine_end)*1000, 'total_ms': (end-start)*1000})
    summaries = {}
    for split in sorted({row['split'] for row in rows}):
        selected = [row for row in rows if row['split'] == split]
        first = [row for row in selected if row['repeat'] == 0]
        positive = [row for row in first if row['expected_cid'] is not None]
        negatives = [row for row in first if row['expected_cid'] is None]
        latencies = [row['total_ms'] for row in selected]
        summaries[split] = {'images': len(first), 'ocr_calls': len(selected), 'success_rate': sum(r['correct'] for r in first)/len(first),
                            'false_alias_count': sum(r['false_alias'] for r in first),
                            'full_name_images': len(positive), 'exact_text_match_rate': sum(r['exact_text_match'] for r in positive)/len(positive) if positive else None,
                            'accepted_full_name_rate': sum(r['correct'] for r in positive)/len(positive) if positive else None,
                            'unknown_expected_images': len(negatives), 'safe_rejection_rate': sum(r['cid'] is None for r in negatives)/len(negatives) if negatives else None,
                            'average_ms': float(np.mean(latencies)), 'p50_ms': float(np.percentile(latencies,50)),
                            'p95_ms': float(np.percentile(latencies,95)), 'max_ms': max(latencies),
                            'repeat_average_ms': float(np.mean([r['total_ms'] for r in selected if r['repeat'] > 0])) if repeats > 1 else None}
    return {'mode': 'local-name-roi-only-experiment', 'input_count': 0, 'runtime_integrated': False,
            'variant': variant, 'scale': scale, 'psm': psm, 'minimum_confidence': minimum, 'repeats': repeats,
            'first_ocr_invocation_ms': rows[0]['total_ms'] if rows else None, 'summaries': summaries, 'rows': rows,
            'database_sha256': hashlib.sha256(database.read_bytes()).hexdigest(),
            'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
            'traineddata_sha256': hashlib.sha256((tessdata/'jpn.traineddata').read_bytes()).hexdigest(),
            'limitations': ['毎回subprocess起動とmodel読込を含む。物理的cold cacheを保証した時間ではない',
                            '同一画像の反復を独立精度標本として数えない。実機E2Eではない',
                            'NFKC/空白除去したDB名前との完全一致のみ。部分名やfuzzyをCID確定に使わない']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--binary', type=Path, default=Path(r'C:\Program Files\Tesseract-OCR\tesseract.exe'))
    parser.add_argument('--tessdata', type=Path, default=Path('data/ocr/tessdata_fast'))
    parser.add_argument('--variant', choices=['raw','gray','otsu'], default='gray')
    parser.add_argument('--scale', type=int, choices=[2,3,4], default=3)
    parser.add_argument('--psm', type=int, choices=[7,13], default=7)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--split', choices=['train','eval'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 10: raise ValueError('反復数は1〜10')
    samples = json.loads(args.manifest.read_text(encoding='utf-8'))['samples']
    selected = [sample for sample in samples if sample['split'] == args.split]
    if not selected: raise ValueError('指定splitに評価画像がありません')
    report = benchmark(selected, args.database, args.binary, args.tessdata, variant=args.variant,
                       scale=args.scale, psm=args.psm, repeats=args.repeats)
    report['manifest_sha256'] = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    args.output.with_suffix('.jsonl').write_text('\n'.join(json.dumps(row,ensure_ascii=False) for row in report['rows'])+'\n',encoding='utf-8')
    print(json.dumps({key: value for key,value in report.items() if key != 'rows'}, ensure_ascii=False))


if __name__ == '__main__': main()
