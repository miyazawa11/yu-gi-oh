from __future__ import annotations

import copy
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HTML = r"""<!doctype html><html lang="ja"><meta charset="utf-8"><title>Master Duel アドバイザー</title>
<style>body{font:16px system-ui;background:#101927;color:#edf4ff;max-width:1100px;margin:30px auto}section{padding:20px;border:1px solid #405472;border-radius:12px;margin:16px 0}pre{white-space:pre-wrap}h1{color:#74ddc1}</style>
<h1>Master Duel アドバイザー</h1><p>観測専用 · 操作はプレイヤーが行います · 部分的なルールによる候補表示</p>
<section><h2>推奨行動</h2><pre id="advice">画面の認識を待っています</pre></section>
<section><h2>現在の状態</h2><pre id="state"></pre></section>
<section><h2>認識状態・計測結果</h2><pre id="status"></pre></section>
<script>
// API のキー・状態コードは保ち、表示用のコピーだけを日本語にします。
const labels={action:'行動',type:'種類',card_id:'カードID',name:'名前',target:'対象',confidence:'信頼度',reason:'理由',recognition_status:'認識状態',state:'状態',sequence:'連番',captured_at:'取得時刻',media_time:'動画内時刻',turn:'ターン番号',turn_player:'ターンプレイヤー',phase:'フェイズ',self:'自分',opponent:'相手',lp:'LP',hand_count:'手札枚数',zones:'ゾーン',value:'値',source:'認識元',source_region:'認識領域',observed_at:'観測時刻',error:'エラー',metrics:'計測結果',events:'観測履歴',timestamp:'時刻',event:'変化の種類',path:'変化した項目',before:'変更前',after:'変更後',capture_read_ms:'取得の読み取り時間（ミリ秒）',perception_ms:'認識時間（ミリ秒）',decision_ms:'判断時間（ミリ秒）',total_compute_ms:'合計処理時間（ミリ秒）',api_calls:'API 呼び出し回数',api_cost_usd:'API 費用（米ドル）',graveyard:'墓地',banished:'除外',extra_deck:'エクストラデッキ'};
const values={unknown:'不明',abstained:'推奨を控えています',partial:'部分的な認識',stale:'情報が古くなっています',self:'自分',opponent:'相手',DRAW:'ドローフェイズ',STANDBY:'スタンバイフェイズ',MAIN1:'メインフェイズ1',BATTLE:'バトルフェイズ',MAIN2:'メインフェイズ2',END:'エンドフェイズ',NORMAL_SUMMON:'通常召喚',SPECIAL_SUMMON:'特殊召喚',ACTIVATE:'発動',SET:'セット',ATTACK:'攻撃',CHANGE_PHASE:'フェイズ変更',SELECT_CARD:'カード選択',SELECT_TARGET:'対象選択',CONFIRM:'確定',CANCEL:'取消',OBSERVED_CHANGE:'観測した値の変化',number:'数値認識',template:'テンプレート認識',card:'カード認識',action:'操作UI認識',unobserved:'未観測'};
function labelKey(key){if(Object.hasOwn(labels,key))return labels[key];const zone=key.match(/^(monster|spell_trap|extra_monster|hand)_([0-9]+)$/);if(zone)return {monster:'モンスターゾーン',spell_trap:'魔法・罠ゾーン',extra_monster:'エクストラモンスターゾーン',hand:'手札'}[zone[1]]+' '+zone[2];return key;}
function labelValue(value){if(Object.hasOwn(values,value))return values[value];const source=value.match(/^(number|template|card|action|unobserved):(.+)$/);if(source)return values[source[1]]+'：'+source[2].split('.').map(labelKey).join('・');if(/^(self|opponent)\./.test(value))return value.split('.').map(labelKey).join('・');return value;}
function localize(value){if(value===null)return '不明・未指定';if(Array.isArray(value))return value.map(localize);if(typeof value==='object')return Object.fromEntries(Object.entries(value).map(([key,item])=>[labelKey(key),localize(item)]));return typeof value==='string'?labelValue(value):value;}
async function refresh(){try{let s=await (await fetch('/state',{cache:'no-store'})).json();document.getElementById('advice').textContent=JSON.stringify(localize(s.recommendation),null,2);document.getElementById('state').textContent=JSON.stringify(localize(s.state),null,2);document.getElementById('status').textContent=JSON.stringify(localize({error:s.error,metrics:s.metrics,events:s.events}),null,2)}catch(e){document.getElementById('status').textContent='接続できません。取得処理とサービスの起動状態を確認してください。'}}setInterval(refresh,400);refresh()</script></html>"""


class SnapshotStore:
    def __init__(self, max_age: float = 1.5):
        self.lock = threading.Lock()
        self.max_age = max_age
        self.updated: float | None = None
        self.snapshot = {"state": None, "events": [], "error": None, "metrics": {}, "recommendation": {"action": None, "target": None, "confidence": 0, "reason": "画面の取得を待っています", "recognition_status": "unknown"}}

    def update(self, snapshot: dict):
        with self.lock:
            self.snapshot = copy.deepcopy(snapshot)
            self.updated = time.monotonic()

    def get(self) -> dict:
        with self.lock:
            result = copy.deepcopy(self.snapshot)
            if self.updated is not None and time.monotonic()-self.updated > self.max_age:
                result["recommendation"] = {"action": None, "target": None, "confidence": 0, "reason": "取得が停止したか情報が古くなっています。新しい画面を待ってください", "recognition_status": "stale"}
            return result


def start_server(store: SnapshotStore, port: int = 8765):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/":
                body, content_type = HTML.encode("utf-8"), "text/html; charset=utf-8"
            elif self.path == "/state":
                body, content_type = json.dumps(store.get(), ensure_ascii=False, allow_nan=False).encode("utf-8"), "application/json; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread
