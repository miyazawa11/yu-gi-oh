"""MSS実画像から明示profileの通常召喚3操作の限定校正を生成。"""
from pathlib import Path
import argparse
import hashlib
import json

from master_duel_advisor.image_io import read_image,write_image
from master_duel_advisor.regions import Calibration,Region,Rect,Exemplar,CompositeEvidence
from master_duel_advisor.strategy_rules import StrategyBook,StrategyRule,LogicalZoneTransition

ROOT=Path(__file__).resolve().parents[1]
FOLDERS={'initial':'MAXXC_INITIAL_TRAIN_v1_foreground','menu':'MAXXC_MENU_TRAIN_v1_full','placement':'MAXXC_PLACEMENT_TRAIN_v1','post':'MAXXC_POST_TRAIN_v1_foreground'}
CID='9455'
PROFILES={
    'maxxc':dict(folders=FOLDERS,cid=CID,card_name='増殖するG',layout_name='MaxxC-same-slot-normal-summon-MSS-v1',
                 book_name='同位置MaxxC中央通常召喚',logical_action='normal_maxxc_center',
                 hand_meaning='MaxxC局所slot輪郭、汎用hand_countを生成しない',
                 rois=dict(hand=(433,650,60,62),outline=(409,615,22,105),name=(20,97,118,31),summon=(434,496,73,98),
                           prompt=(480,155,328,39),target=(582,382,116,122),occupancy=(601,396,78,108),field=(609,413,61,58))),
    'solar-slot2':dict(folders={key:'MAXXC_CURRENT_HAND_TRAIN_20261006/'+folder for key,folder in
                               [('initial','initial'),('menu','solar-menu'),('placement','solar-placement'),('post','solar-post')]},
                       cid='13581',card_name='太陽電池メン',layout_name='Solar-slot2-normal-summon-MSS-v1',
                       book_name='同位置Solar中央通常召喚',logical_action='normal_solar_center',
                       hand_meaning='Solar局所slot2輪郭、初期は隣slot3hover。汎用7枚hand_countを生成しない',
                       rois=dict(hand=(432,650,48,62),outline=(412,618,18,98),name=(21,99,153,29),summon=(380,497,74,79),
                                 prompt=(465,157,346,31),target=(584,385,111,114),occupancy=(603,398,74,53),field=(609,404,61,45))),
}
PROFILES['solar-slot2-v2']={**PROFILES['solar-slot2'],
    'folders':{**PROFILES['solar-slot2']['folders'],'post':'SOLAR_POST_TEMPORAL_DIAGNOSTIC_20261006'},
    'expected_counts':{'post':11},'layout_name':'Solar-slot2-normal-summon-MSS-v2'}


def pixel_rect(roi):
    x,y,w,h=roi;e=.0001
    return Rect(x=(x+e)/1280,y=(y+e)/720,width=(w-2*e)/1280,height=(h-2*e)/720)


def build(output,profile='maxxc'):
    if profile not in PROFILES:raise ValueError('未登録の限定profileです')
    selected=PROFILES[profile];cid=selected['cid']
    batches={};sources=[]
    for key,folder in selected['folders'].items():
        base=ROOT/'artifacts/baseline-tester'/folder
        manifest=json.loads((base/'manifest.json').read_text(encoding='utf-8'))
        rows=manifest['frames']
        expected=selected.get('expected_counts',{}).get(key,20)
        if len(rows)!=expected or not all(row['eligible'] for row in rows):raise ValueError('事前指定した訓練枚数/適合条件が不一致です')
        batches[key]=[]
        for row in rows:
            path=base/row['file'];sha=hashlib.sha256(path.read_bytes()).hexdigest()
            if sha!=row['sha256']:raise ValueError('訓練画像hash不一致')
            pixels=read_image(path)
            if pixels is None or pixels.shape!=(720,1280,3) or pixels.std()==0:raise ValueError('実client画像が必要です')
            batches[key].append(pixels);sources.append({'path':str(path),'sha256':sha,'label':key})
    output.mkdir(parents=True,exist_ok=True);regions={}
    def add(name,roi,kind,label_batches,card_id=None,target=None):
        examples=[];rect=pixel_rect(roi)
        for label,keys in label_batches.items():
            for key in keys:
                for i,pixels in enumerate(batches[key]):
                    filename=name.replace('.','_')+f'-{label}-{key}-{i:02d}.png'
                    write_image(output/filename,rect.crop(pixels));examples.append(Exemplar(label=label,image=filename))
        regions[name]=Region(rect=rect,kind=kind,threshold=.98,feature='stable_rgb',exemplars=examples,card_id=card_id,target=target)
    rois=selected['rois']
    hand,outline,name,summon,prompt,target,occupancy,field=(rois[key] for key in
        ('hand','outline','name','summon','prompt','target','occupancy','field'))
    for key,roi in {'hand_layout':outline,'main1':(937,281,101,95),'clear_center':(479,371,320,40),'clear_card_menu':(267,219,12,40)}.items():
        add('fact.normal_context.'+key,roi,'template',{'true':['initial']})
    add('fact.normal_context.hand_card',hand,'template',{cid:['initial']})
    add('fact.selection.card_id',name,'template',{cid:['menu','placement']})
    add('fact.normal_context.summon_enabled',summon,'template',{'true':['menu']})
    add('fact.normal_context.placement',prompt,'template',{'true':['placement']})
    add('fact.normal_context.placement_target',target,'template',{'true':['placement']})
    add('fact.zone.self.monster_2.occupancy',occupancy,'template',{'empty':['initial'],'occupied':['post']})
    add('self.zones.monster_2',field,'card',{cid:['post']})
    add('action.normal_hand',hand,'action',{'SELECT_CARD':['initial']},cid)
    add('action.normal_summon',summon,'action',{'NORMAL_SUMMON':['menu']},cid)
    add('action.normal_place',target,'action',{'CONFIRM':['placement']},cid,'self.monster_2')
    normal={f'fact.normal_context.{key}':'true' for key in ('hand_layout','main1','clear_center','clear_card_menu')}
    normal.update({'fact.normal_context.hand_card':cid,'fact.zone.self.monster_2.occupancy':'empty'})
    menu={'fact.selection.card_id':cid,'fact.normal_context.summon_enabled':'true'}
    placement={'fact.selection.card_id':cid,'fact.normal_context.placement':'true','fact.normal_context.placement_target':'true'}
    common={'phase':'MAIN1','turn_player':'self','game.terminal':'active','ui.animation':'idle'}
    layout=Calibration(name=selected['layout_name'],regions=regions,composites=[CompositeEvidence(id=key,when=facts,emit={**common,'ui.prompt':p}) for key,facts,p in [('normal_initial',normal,'none'),('normal_menu',menu,'card.menu'),('normal_place',placement,'placement.select')]])
    goal=LogicalZoneTransition(zone='monster_2',card_id=cid,selected_card_fact='selection.card_id',placement_region='action.normal_place')
    common_rule=dict(card_id=cid,priority=1000,phases=['MAIN1'],logical_action=selected['logical_action'],logical_category='NORMAL_SUMMON',logical_zone_transition=goal)
    rules=[StrategyRule(id='normal_open',description=f"同位置の{selected['card_name']}を選択",type='SELECT_CARD',source_region='action.normal_hand',logical_start=True,expected_prompts=['card.menu'],observed_facts={k.removeprefix('fact.'):v for k,v in normal.items()},**common_rule),
           StrategyRule(id='normal_summon',description='有効な通常召喚UIを選択',type='NORMAL_SUMMON',source_region='action.normal_summon',prompt='card.menu',follows=['normal_open'],expected_prompts=['placement.select'],observed_facts={k.removeprefix('fact.'):v for k,v in menu.items()},**common_rule),
           StrategyRule(id='normal_place',description='中央へ配置し指定カード成立を確認',type='CONFIRM',source_region='action.normal_place',target='self.monster_2',prompt='placement.select',follows=['normal_summon'],logical_end=True,observed_facts={k.removeprefix('fact.'):v for k,v in placement.items()},**common_rule)]
    book=StrategyBook(format='deck-strategy-v1',name=selected['book_name'],source=f'MSS訓練{len(sources)}枚、補助収集はKPI除外',rules=rules,audit_profile='normal_summon')
    for filename,obj in [('calibration.json',layout),('normal-route.json',book)]:
        (output/filename).write_text(obj.model_dump_json(indent=2)+'\n',encoding='utf-8')
    (output/'trials.json').write_text(json.dumps([selected['logical_action']])+'\n',encoding='utf-8')
    manifest={'training':sources,'card_id':cid,'source':'MSS client BGR1280x720','independent':False,'hand_layout_meaning':selected['hand_meaning'],'calibration_sha256':hashlib.sha256((output/'calibration.json').read_bytes()).hexdigest(),'route_sha256':hashlib.sha256((output/'normal-route.json').read_bytes()).hexdigest()}
    if profile=='solar-slot2-v2':
        manifest['post_training_policy']='時間分散11枚の実field表示。旧青白post20枚は未対応の過渡表示として確認待ち。未成立/誤操作とは扱わない'
    (output/'training-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return layout,book,manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--profile',choices=list(PROFILES),default='maxxc');parser.add_argument('--output',type=Path);args=parser.parse_args()
    defaults={'maxxc':'artifacts/normal-maxxc-calibration-v1','solar-slot2':'artifacts/solar-normal-calibration-v1','solar-slot2-v2':'artifacts/solar-normal-calibration-v2'}
    output=args.output or ROOT/defaults[args.profile]
    _,_,manifest=build(output,args.profile);print(json.dumps({k:v for k,v in manifest.items() if k!='training'},ensure_ascii=False))
