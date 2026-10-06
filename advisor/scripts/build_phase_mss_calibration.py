"""実ランタイムと同じMSS client画像だけで通常盤面の限定校正を作る。入力なし。"""
from pathlib import Path
import argparse
import hashlib
import json

from master_duel_advisor.image_io import read_image, write_image
from master_duel_advisor.regions import Calibration, Exemplar

ROOT=Path(__file__).resolve().parents[1]
NORMAL={'fact.phase_context.self_main1','fact.phase_context.clear_center',
        'fact.phase_context.clear_card_menu','action.phase_open'}
MENU={'fact.phase_context.menu_title','fact.phase_context.menu_end','fact.phase_context.menu_main1','action.phase_end'}


def build(training_folder, output, menu_folder=None, end_folder=None):
    base=Calibration.model_validate_json((ROOT/'artifacts/phase-only-calibration/calibration.json').read_text(encoding='utf-8'))
    def read_batch(folder, minimum):
        paths=sorted(folder.glob('*.png')) if folder else []
        if len(paths)<minimum:
            raise ValueError(f'MSS訓練画像が{minimum}枚以上必要です: {folder}')
        images=[]
        for path in paths:
            pixels=read_image(path)
            if pixels is None or pixels.shape!=(720,1280,3):
                raise ValueError(f'client1280x720 BGR画像ではありません: {path}')
            if float(pixels.std())==0:
                raise ValueError(f'一様な取得不能画像を訓練に使えません: {path}')
            images.append(pixels)
        return paths,images
    paths,images=read_batch(training_folder,10)
    menu_paths,menu_images=read_batch(menu_folder,1) if menu_folder else ([],[])
    end_paths,end_images=read_batch(end_folder,1) if end_folder else ([],[])
    output.mkdir(parents=True,exist_ok=True)
    regions={}
    names=NORMAL | (MENU if menu_folder else set()) | ({"phase"} if end_folder else set())
    for name in sorted(names):
        original=base.regions[name]
        label={'action.phase_open':'CHANGE_PHASE','action.phase_end':'CONFIRM','phase':'END'}.get(name,'true')
        batch=menu_images if name in MENU else end_images if name=='phase' else images
        exemplars=[]
        for index,pixels in enumerate(batch):
            filename=name.replace('.','_')+f'-mss-{index:03d}.png'
            # 既にclient画像なのでタイトルバー除去を二度実行しない。
            write_image(output/filename,original.rect.crop(pixels))
            exemplars.append(Exemplar(label=label,image=filename))
        regions[name]=original.model_copy(update={'exemplars':exemplars})
    layout=base.model_copy(update={'name':'phase-MSS-complete' if end_folder and menu_folder else 'phase-MSS-menu' if menu_folder else 'phase-MSS-normal-only-v4','regions':regions,
        'composites':[context for context in base.composites if context.id=='known_main1_clear' or menu_folder]})
    (output/'calibration.json').write_text(layout.model_dump_json(indent=2)+'\n',encoding='utf-8')
    manifest={'source':'MSS client BGR 1280x720','scope':'full_phase_route' if end_folder and menu_folder else 'normal_and_menu_partial' if menu_folder else 'normal_Main1_only_not_full_phase_route',
        'training':[{'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()} for path in [*paths,*menu_paths,*end_paths]],
        'sky_templates_used':False,'menu_banner_ready':bool(menu_folder and end_folder),
        'calibration_sha256':hashlib.sha256((output/'calibration.json').read_bytes()).hexdigest(),
        'source_manifests':{str(path):json.loads(path.read_text(encoding='utf-8')) for folder in [training_folder,menu_folder,end_folder] if folder for path in folder.glob('*.json')}}
    (output/'training-manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    return layout,manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--training-folder',type=Path,required=True)
    parser.add_argument('--menu-folder',type=Path)
    parser.add_argument('--end-folder',type=Path,help='Endバナーを目視確認済みのフレームだけを含むフォルダー')
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/phase-mss-calibration')
    args=parser.parse_args()
    _,manifest=build(args.training_folder,args.output,args.menu_folder,args.end_folder)
    print(json.dumps({k:v for k,v in manifest.items() if k not in ('training','source_manifests')},ensure_ascii=False))
