"""Ash補助MSS40枚のみから限定3操作の校正を生成します。実機KPIではありません。"""
import argparse
import hashlib
import json
from pathlib import Path

from build_normal_calibration import pixel_rect
from master_duel_advisor.capture import Frame
from master_duel_advisor.cards import CardDatabase
from master_duel_advisor.image_io import read_image, write_image
from master_duel_advisor.perception import Perception
from master_duel_advisor.regions import Calibration, CompositeEvidence, Exemplar, RecognitionResource, Region
from master_duel_advisor.strategy_rules import LogicalInspectConfirmation, StrategyBook, StrategyRule

ROOT = Path(__file__).resolve().parents[1]
TRAIN = ROOT / 'artifacts/baseline-tester/ASH_NORMAL_INSPECT_TRAIN_v1_20261006'
CID = '12950'
STAGES = ['menu', 'placement', 'post-unselected', 'post-inspected']


def build(output):
    batches, sources = {}, []
    for stage in STAGES:
        folder = TRAIN / stage
        manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
        rows = manifest['frames']
        if len(rows) != 10 or not all(row['eligible'] for row in rows):
            raise ValueError('段階ごとに適合MSS10枚が必要です')
        batches[stage] = []
        for row in rows:
            path = folder / row['file']
            if hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
                raise ValueError('元画像hash不一致')
            pixels = read_image(path)
            if pixels.shape != (720, 1280, 3):
                raise ValueError('native client画像が必要です')
            batches[stage].append(pixels)
            sources.append(dict(path=str(path), sha256=row['sha256'], stage=stage,
                                original_capture_manifest=str(folder / 'manifest.json')))
    output.mkdir(parents=True, exist_ok=True)
    regions = {}

    def add(name, roi, kind, labels, target=None):
        examples = []
        rect = pixel_rect(roi)
        for label, stages in labels.items():
            for stage in stages:
                for index, image in enumerate(batches[stage]):
                    filename = name.replace('.', '_') + f'-{label}-{stage}-{index:02d}.png'
                    write_image(output / filename, rect.crop(image))
                    examples.append(Exemplar(label=label, image=filename))
        regions[name] = Region(rect=rect, kind=kind, threshold=.98, feature='stable_rgb',
                               exemplars=examples, card_id=CID if kind == 'action' else None, target=target)

    add('fact.inspect_context.main1', (947,317,87,38), 'template', {'true': STAGES})
    add('fact.inspect_context.clear_center', (480,371,320,18), 'template', {'true': ['menu','post-unselected','post-inspected']})
    add('fact.inspect_context.hand_selected', (407,579,18,112), 'template', {'true':['menu']})
    add('fact.inspect_context.summon_enabled', (380,497,74,79), 'template', {'true':['menu']})
    add('fact.inspect_context.placement', (465,157,346,31), 'template', {'true':['placement']})
    add('fact.inspect_context.placement_target', (582,382,116,122), 'template', {'true':['placement']})
    add('fact.zone.self.monster_2.occupancy', (603,398,74,108), 'template', {'empty':['menu'], 'occupied':['post-unselected','post-inspected']})
    add('fact.inspect_context.detail_blank', (20,140,245,300), 'template', {'true':['post-unselected']})
    add('fact.inspect_context.detail_panel', (263,219,12,40), 'template', {'true':['menu','post-inspected']})
    add('action.inspect_normal', (380,497,74,79), 'action', {'NORMAL_SUMMON':['menu']})
    add('action.inspect_place', (582,382,116,122), 'action', {'CONFIRM':['placement']}, 'self.monster_2')
    add('action.inspect_zone', (603,398,74,108), 'action', {'SELECT_CARD':['post-unselected']}, 'self.monster_2')
    common = {'phase':'MAIN1','turn_player':'self','game.terminal':'active','ui.animation':'idle'}
    main = {'fact.inspect_context.main1':'true'}
    center = {**main, 'fact.inspect_context.clear_center':'true'}
    occupancy = 'fact.zone.self.monster_2.occupancy'
    contexts = [
        ('menu', {**center, 'fact.inspect_context.hand_selected':'true', 'fact.inspect_context.summon_enabled':'true', occupancy:'empty','fact.inspect_context.detail_panel':'true'}, 'card.menu'),
        ('placement', {**main, 'fact.inspect_context.placement':'true','fact.inspect_context.placement_target':'true'}, 'placement.select'),
        ('post_unselected', {**center, occupancy:'occupied','fact.inspect_context.detail_blank':'true'}, 'none'),
        ('post_inspected', {**center, occupancy:'occupied','fact.inspect_context.detail_panel':'true'}, 'field.inspect')]
    import os
    assets = {}
    for key, path in [('detail_name_registry',ROOT/'artifacts/detail-name-registry-v1/registry.json'),
                      ('action_evidence_detector',ROOT/'evaluation/action-evidence-detector-v1.json')]:
        assets[key] = RecognitionResource(path=os.path.relpath(path,output), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    layout = Calibration(name='Ash-normal-inspect-MSS-v1', regions=regions, recognition_assets=assets,
        composites=[CompositeEvidence(id=key, when=facts, emit={**common,'ui.prompt':prompt}) for key,facts,prompt in contexts])
    goal = LogicalInspectConfirmation(zone='monster_2',card_id=CID,summon_region='action.inspect_normal',placement_region='action.inspect_place',inspect_region='action.inspect_zone')
    base = dict(card_id=CID,priority=1000,phases=['MAIN1'],logical_action='normal_ash_inspect_center',logical_category='NORMAL_SUMMON',logical_inspect_confirmation=goal)
    rules = [
        StrategyRule(id='inspect_normal',description='有効Ash通常召喚UIを選択',type='NORMAL_SUMMON',source_region=goal.summon_region,prompt='card.menu',logical_start=True,expected_prompts=['placement.select'],observed_facts={'detail.card_id':CID,'inspect_context.hand_selected':'true','inspect_context.summon_enabled':'true','zone.self.monster_2.occupancy':'empty'},**base),
        StrategyRule(id='inspect_place',description='中央へ実配置し明示detail空を確認',type='CONFIRM',source_region=goal.placement_region,target='self.monster_2',prompt='placement.select',follows=['inspect_normal'],expected_prompts=['none'],observed_facts={'inspect_context.placement':'true','inspect_context.placement_target':'true'},expected_facts={'zone.self.monster_2.occupancy':'occupied','inspect_context.detail_blank':'true'},**base),
        StrategyRule(id='inspect_zone',description='実配置先を選択し新Ash詳細を確認',type='SELECT_CARD',source_region=goal.inspect_region,target='self.monster_2',prompt='none',follows=['inspect_place'],logical_end=True,observed_facts={'zone.self.monster_2.occupancy':'occupied','inspect_context.detail_blank':'true'},expected_facts={'detail.card_id':CID,'zone.self.monster_2.occupancy':'occupied'},**base)]
    book = StrategyBook(format='deck-strategy-v1',name='Ash中央通常召喚と実zoneinspect',source='補助MSS40枚。独立試験・実入力証明・E2Eから除外',rules=rules,audit_profile='normal_inspect_confirmation')
    for filename, obj in [('calibration.json',layout),('normal-route.json',book)]:
        (output/filename).write_text(obj.model_dump_json(indent=2)+'\n',encoding='utf-8')
    (output/'trials.json').write_text(json.dumps(['normal_ash_inspect_center'])+'\n',encoding='utf-8')
    manifest = dict(training=sources,independent=False,kpi_action_count=0,receipt_mode='assisted_sky_not_runtime_sent_verified',excluded_stages=['post-transition'],calibration_sha256=hashlib.sha256((output/'calibration.json').read_bytes()).hexdigest(),route_sha256=hashlib.sha256((output/'normal-route.json').read_bytes()).hexdigest())
    (output/'training-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return layout, book, batches


def evaluate(output, database):
    layout, book, batches = build(output)
    perception = Perception(layout,output,CardDatabase(database))
    perception.configure_inspect(book.rules[0].logical_inspect_confirmation,output)
    rows = []
    expected = dict(zip(STAGES,['card.menu','placement.select','none','field.inspect']))
    for stage, images in batches.items():
        for index,image in enumerate(images):
            state = perception.process(Frame(image,0,index,capture_source='saved_image'))
            actions = state.visible_actions
            detail = state.facts['detail.card_id'].value
            passed = state.prompt.value == expected[stage]
            if stage in ['menu','post-inspected']:
                passed = passed and detail == CID
            if stage == 'post-unselected':
                passed = passed and detail is None and state.facts['inspect_context.detail_blank'].value == 'true'
            rows.append(dict(stage=stage,index=index,passed=passed,prompt=state.prompt.value,detail_cid=detail,
                actions=[a.type.value for a in actions],facts={k:v.value for k,v in state.facts.items()}))
    return dict(passed=all(r['passed'] for r in rows),cases=len(rows),training_only=True,input_count=0,e2e_count=0,rows=rows)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/ash-normal-inspect-calibration-v1')
    parser.add_argument('--database',type=Path,default=ROOT/'data/decks/thunder-dragon-review/cards.sqlite3')
    parser.add_argument('--report',type=Path,default=ROOT/'evaluation/ash-normal-inspect-training-v1.json')
    args = parser.parse_args()
    report = evaluate(args.output,args.database)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='rows'},ensure_ascii=False))
    raise SystemExit(0 if report['passed'] else 1)
