import json,time
from pathlib import Path
from master_duel_advisor.cli import build_pipeline
from master_duel_advisor.capture import Frame
from master_duel_advisor.image_io import read_image,write_image
out=Path('artifacts/live-screen-test-20261005')
window=read_image(out/'window.png')
pixels=window[31:751,1:1281]
write_image(out/'game.png',pixels)
p=build_pipeline(Path('artifacts/live-validation/calibration.json'),Path('artifacts/live-validation/cards.sqlite3'),Path('artifacts/live-validation/plan-book.json'))
report={'mode':'actual_screen_existing_calibration','automatic_perception':True,'input_count':0,'image_shape':list(pixels.shape),'expected_visual':{'turn':1,'phase':'MAIN1','turn_player':'self','self_lp':8000,'opponent_lp':8000,'hand_count':4,'field':['ワイバースター','超雷龍']},'real_accuracy_gate':False}
try:
 result=p.process(Frame(pixels,time.monotonic(),0))
 report['result']=result
 report['status']='rejected' if result.get('error') else 'processed'
except Exception as e:
 report['status']='rejected'
 report['error']=str(e)
finally:
 p.perception.cards.close()
(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))

