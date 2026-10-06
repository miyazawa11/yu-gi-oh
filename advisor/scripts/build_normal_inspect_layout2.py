"""固定v1を維持し、新規menu10枚の限定layoutを既存stable_rgbで追加します。"""
import hashlib
import json
import shutil
from pathlib import Path

from build_normal_calibration import pixel_rect
from master_duel_advisor.action_evidence import ActionEvidenceDetector, CaptureContext
from master_duel_advisor.capture import Frame
from master_duel_advisor.cli import build_pipeline, close_pipeline
from master_duel_advisor.image_io import read_image,write_image
from master_duel_advisor.perception import TemplateMatcher
from master_duel_advisor.regions import Calibration, Exemplar, RecognitionResource, Region

ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT/'artifacts/ash-normal-inspect-calibration-v1'
OUT=ROOT/'artifacts/ash-normal-inspect-calibration-v2'
TRAIN=ROOT/'artifacts/baseline-tester/ASH_NORMAL_INSPECT_LAYOUT2_TRAIN_v2_20261006/menu'
NORMAL=(338,502,74,79)
HAND=(365,584,18,112)


def build():
    manifest=json.loads((TRAIN/'manifest.json').read_text(encoding='utf-8'))
    if len(manifest['frames'])!=10 or not all(row['eligible'] for row in manifest['frames']):
        raise ValueError('新規menu訓練10枚が必要です')
    images=[];sources=[]
    for row in manifest['frames']:
        path=TRAIN/row['file']
        if hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:
            raise ValueError('新訓練hash不一致')
        image=read_image(path)
        if image.shape!=(720,1280,3):raise ValueError('実client BGR画像が必要です')
        images.append(image);sources.append({'path':str(path),'sha256':row['sha256']})
    OUT.mkdir(parents=True,exist_ok=True)
    for path in OLD.glob('*.png'):
        shutil.copyfile(path,OUT/path.name)
    raw=json.loads((OLD/'calibration.json').read_text(encoding='utf-8'))
    raw['name']='Ash-left-menu-normal-inspect-MSS-v2'
    # 探索の公称anchorは380/497、実訓練crop338/502をテンプレートへ正規化。
    # 手札輪郭も同じ平行移動に対応し、カードIDとしては扱いません。
    rois={'fact.inspect_context.main1':(947,317,87,38),
          'fact.inspect_context.clear_center':(480,371,320,18),
          'fact.inspect_context.hand_selected':HAND,
          'fact.inspect_context.summon_enabled':NORMAL,
          'fact.zone.self.monster_2.occupancy':(603,398,74,108),
          'fact.inspect_context.detail_panel':(263,219,12,40),
          'action.inspect_normal':NORMAL}
    replace={'fact.inspect_context.hand_selected','fact.inspect_context.summon_enabled','action.inspect_normal'}
    for name,roi in rois.items():
        label='empty' if name=='fact.zone.self.monster_2.occupancy' else 'NORMAL_SUMMON' if name=='action.inspect_normal' else 'true'
        entries=[]
        for index,image in enumerate(images):
            filename=name.replace('.','_')+f'-{label}-layout2-{index:02d}.png'
            write_image(OUT/filename,pixel_rect(roi).crop(image))
            entries.append({'label':label,'image':filename})
        if name in replace: raw['regions'][name]['exemplars']=entries
        else: raw['regions'][name]['exemplars'].extend(entries)
    support=OUT/'readonly-detector-support';support.mkdir(exist_ok=True)
    examples=[]
    for index,image in enumerate(images):
        filename=f'normal-layout2-{index:02d}.png'
        write_image(support/filename,pixel_rect(NORMAL).crop(image))
        examples.append(Exemplar(label='NORMAL_SUMMON',image=filename))
    region=Region(rect=pixel_rect((380,497,74,79)),kind='action',feature='stable_rgb',threshold=.98,exemplars=examples)
    layout=Calibration(name='A2-Ash-left-menu-normalized-local-search-v2',regions={'action.normal_summon':region})
    cal_path=support/'calibration.json';cal_path.write_text(layout.model_dump_json(indent=2)+'\n',encoding='utf-8')
    matcher=TemplateMatcher(region,support)
    old_config=ROOT/'evaluation/action-evidence-detector-v1.json'
    config=json.loads(old_config.read_text(encoding='utf-8'))
    import os
    config['profiles']['maxxc-menu-v1']['calibration']=os.path.relpath((old_config.parent/config['profiles']['maxxc-menu-v1']['calibration']).resolve(),support)
    solar=config['profiles']['solar-menu-v2']
    solar.update(calibration='calibration.json',calibration_sha256=hashlib.sha256(cal_path.read_bytes()).hexdigest(),template_assets=matcher.asset_hashes,stable_features=matcher.stable_statistics)
    config_path=support/'detector.json';config_path.write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    # 機械profile名は既存有限探索I/Fの識別子です。カード名や元Solar資産は意味しません。
    raw['recognition_assets']['action_evidence_detector']=RecognitionResource(path='readonly-detector-support/detector.json',sha256=hashlib.sha256(config_path.read_bytes()).hexdigest()).model_dump(mode='json')
    new_cal=Calibration.model_validate(raw)
    (OUT/'calibration.json').write_text(new_cal.model_dump_json(indent=2)+'\n',encoding='utf-8')
    for filename in ['normal-route.json','trials.json']:
        shutil.copyfile(OLD/filename,OUT/filename)
    provenance={'schema':'ash-layout2-training-v2','sources':sources,'source_manifest':str(TRAIN/'manifest.json'),
        'normal_actual_crop':NORMAL,'normal_nominal_search_anchor':(380,497,74,79),'hand_actual_crop':HAND,
        'hand_nominal_relative_anchor':(407,579,18,112),'score_threshold':.98,'position_margin':.03,
        'independent':False,'preflight_failure_used_as_training':False,'input_count':0,'e2e_count':0,
        'profile_id_notice':'solar-menu-v2は既存探索I/F名。A2専用config/hashがAsh-left-layout2参照を明示',
        'old_stage_policy':'既存placement/post訓練を維持、v1旧menuはv1profileで回帰'}
    (OUT/'training-manifest.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2),encoding='utf-8')
    pipeline=build_pipeline(OUT/'calibration.json',ROOT/'data/decks/thunder-dragon-review/cards.sqlite3',OUT/'normal-route.json')
    rows=[]
    batches=[('menu',images)]
    for stage in ['placement','post-unselected','post-inspected']:
        folder=ROOT/'artifacts/baseline-tester/ASH_NORMAL_INSPECT_TRAIN_v1_20261006'/stage
        batches.append((stage,[read_image(folder/f'frame-{i:04d}.png') for i in range(10)]))
    prompts={'menu':'card.menu','placement':'placement.select','post-unselected':'none','post-inspected':'field.inspect'}
    for stage,batch in batches:
        for index,image in enumerate(batch):
            state=pipeline.perception.process(Frame(image,0,index,capture_source='saved_image'))
            rows.append({'stage':stage,'index':index,'passed':state.prompt.value==prompts[stage],
                'prompt':state.prompt.value,'facts':{k:v.value for k,v in state.facts.items()},
                'actions':[a.type.value for a in state.visible_actions]})
    report={'passed':all(r['passed'] for r in rows),'cases':len(rows),'training_only':True,'input_count':0,'e2e_count':0,'rows':rows,
        'stable_features':pipeline.perception.stable_statistics,'detector':pipeline.perception.inspect_detector.provenance()}
    (ROOT/'evaluation/ash-normal-inspect-training-v2.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    close_pipeline(pipeline)
    return report


if __name__=='__main__':
    report=build();print(json.dumps({k:v for k,v in report.items() if k in ['passed','cases','training_only','input_count','e2e_count']}))
    raise SystemExit(0 if report['passed'] else 1)
