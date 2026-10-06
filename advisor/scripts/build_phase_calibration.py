"""限定phase操作の校正を固定した学習資料から再生成します。実機入力なし。"""
from pathlib import Path
import json

from master_duel_advisor.image_io import read_image, write_image
from master_duel_advisor.regions import Calibration, Rect, Region, Exemplar, CompositeEvidence
from master_duel_advisor.strategy_rules import StrategyBook, StrategyRule

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'artifacts/baseline-tester/calibration-20261005'
DEST = ROOT / 'artifacts/phase-only-calibration'
TRAIN = {n: next(SOURCE.glob(f'{n:03d}-*.png')) for n in (*[7,9,11,22,23,45],*range(47,67))}


def pixel_rect(x, y, width, height):
    # floor/ceilの境界誤差を避け、指定した整数画素だけを切り抜く。
    epsilon = 0.0001
    return Rect(x=(x-1+epsilon)/1280, y=(y-31+epsilon)/720,
                width=(width-2*epsilon)/1280, height=(height-2*epsilon)/720)


def build():
    DEST.mkdir(parents=True, exist_ok=True)
    regions = {}
    def add(name, roi, kind, label, samples, feature="rgb"):
        x,y,w,h=roi
        # 訓練資料はウィンドウ画像。実入力元はclient領域1280x720。
        exemplars=[]
        for index in samples:
            image=read_image(TRAIN[index]); crop=image[y:y+h,x:x+w]
            file=name.replace('.','_')+f'-{index}.png'
            write_image(DEST/file,crop)
            exemplars.append(Exemplar(label=label,image=file))
        regions[name]=Region(rect=pixel_rect(x,y,w,h),
                             kind=kind,threshold=.98,exemplars=exemplars,feature=feature)
    circle=(938,312,101,95); center=(480,402,320,40); edge=(268,250,12,40)
    title=(495,402,295,27); end=(952,491,114,120); selected=(510,494,117,119)
    add('fact.phase_context.self_main1',circle,'template','true',range(47,67),'stable_rgb')
    add('fact.phase_context.clear_center',center,'template','true',[7,22,23,45])
    add('fact.phase_context.clear_card_menu',edge,'template','true',range(47,67),'stable_rgb')
    add('fact.phase_context.menu_title',title,'template','true',[9])
    add('fact.phase_context.menu_end',end,'template','true',[9])
    add('fact.phase_context.menu_main1',selected,'template','true',[9])
    add('action.phase_open',circle,'action','CHANGE_PHASE',range(47,67),'stable_rgb')
    add('action.phase_end',end,'action','CONFIRM',[9])
    add('phase',(449,366,403,53),'template','END',[11])
    normal={key:'true' for key in ('fact.phase_context.self_main1','fact.phase_context.clear_center','fact.phase_context.clear_card_menu')}
    menu={key:'true' for key in ('fact.phase_context.menu_title','fact.phase_context.menu_end','fact.phase_context.menu_main1')}
    common={'phase':'MAIN1','turn_player':'self','game.terminal':'active','ui.animation':'idle'}
    layout=Calibration(name='phase-only-1280x720-stable-rgb-v3',regions=regions,composites=[
        CompositeEvidence(id='known_main1_clear',when=normal,emit={**common,'ui.prompt':'none'}),
        CompositeEvidence(id='stable_phase_menu',when=menu,emit={**common,'ui.prompt':'phase.select'})])
    common_rule=dict(priority=1000,phases=['MAIN1'],logical_action='main1_to_end',logical_category='CHANGE_PHASE')
    first=StrategyRule(id='phase_open',description='フェイズ選択を開く',type='CHANGE_PHASE',source_region='action.phase_open',
        prompt='none',expected_prompts=['phase.select'],observed_facts={k.removeprefix('fact.'):v for k,v in normal.items()},logical_start=True,**common_rule)
    last=StrategyRule(id='phase_end',description='Endを選びEndフェイズ到達を確認',type='CONFIRM',source_region='action.phase_end',
        prompt='phase.select',follows=['phase_open'],observed_facts={k.removeprefix('fact.'):v for k,v in menu.items()},logical_end=True,logical_phase='END',**common_rule)
    book=StrategyBook(format='deck-strategy-v1',name='既知盤面限定Main1からEnd',source='実画面train007/009/011/022/023/045+時間変動train047-066',
                      rules=[first,last],audit_profile='phase_transition')
    (DEST/'calibration.json').write_text(layout.model_dump_json(indent=2)+'\n',encoding='utf-8')
    (DEST/'phase-route.json').write_text(book.model_dump_json(indent=2)+'\n',encoding='utf-8')
    (DEST/'trials.json').write_text('["main1_to_end"]\n',encoding='utf-8')
    (DEST/'training-manifest.json').write_text(json.dumps({'training':[str(p) for p in TRAIN.values()],
        'design_negatives':'000-028はROI設計に使用。独立評価として扱わない','roi_frozen':True,'threshold':.98,'stable_rgb':{'max_deviation':.01,'min_pixels':256,'min_samples':10},
        'limitation':'既知盤面のみ。全画面/任意盤面認識の受入ではない'},indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    return layout,book

if __name__=='__main__':
    build()
    print(DEST)
