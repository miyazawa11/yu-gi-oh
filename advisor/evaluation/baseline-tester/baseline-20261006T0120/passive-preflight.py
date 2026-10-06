from pathlib import Path
import hashlib,json,time,zipfile
from master_duel_advisor.capture import LiveCaptureSource
from master_duel_advisor.cli import build_pipeline,close_pipeline
from master_duel_advisor.image_io import write_image
from master_duel_advisor.safety import WindowsDesktop
out=Path('evaluation/baseline-tester/baseline-20261006T0120');out.mkdir(parents=True,exist_ok=True)
src=Path('src/master_duel_advisor');digest=hashlib.sha256()
files=sorted(src.glob('*.py'))
with zipfile.ZipFile(out/'source-fixed.zip','w',zipfile.ZIP_DEFLATED) as archive:
 for p in files:
  digest.update(p.name.encode());digest.update(p.read_bytes());archive.write(p,p.as_posix())
configs=['artifacts/phase-mss-complete-calibration/calibration.json','artifacts/phase-only-calibration/phase-route.json','artifacts/normal-maxxc-calibration-v1/calibration.json','artifacts/normal-maxxc-calibration-v1/normal-route.json']
meta={'created_utc':time.time(),'mode':'passive_preflight','source_sha256':digest.hexdigest(),'config_sha256':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in configs},'inputs':0}
(out/'fixed-metadata.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
d=WindowsDesktop();h=d.find('masterduel');rect=d.client_rect(h)
source=LiveCaptureSource('mss',rect)
pipes={name:build_pipeline(Path(cal),Path('data/decks/thunder-dragon-review/cards.sqlite3'),Path(route)) for name,cal,route in [('phase',configs[0],configs[1]),('normal',configs[2],configs[3])]}
rows=[]
for i in range(3):
 before={'rect':d.client_rect(h),'foreground':d.foreground()};start=time.perf_counter();f=source.read();elapsed=(time.perf_counter()-start)*1000
 write_image(out/f'passive-{i:02d}.png',f.pixels)
 row={'i':i,'capture_ms':elapsed,'before':before,'after':{'rect':d.client_rect(h),'foreground':d.foreground()},'std':float(f.pixels.std()),'models':{}}
 for name,p in pipes.items():
  s=p.process(f,elapsed);row['models'][name]=s
 rows.append(row)
source.close()
for p in pipes.values():close_pipeline(p)
(out/'passive-preflight.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'source':meta['source_sha256'],'rows':[{'i':r['i'],'capture_ms':r['capture_ms'],'std':r['std'],'models':{k:{'phase':s['state']['phase'],'turn_player':s['state']['turn_player'],'recommendation':s['recommendation'],'metrics':s['metrics']} for k,s in r['models'].items()}} for r in rows]},ensure_ascii=False))
