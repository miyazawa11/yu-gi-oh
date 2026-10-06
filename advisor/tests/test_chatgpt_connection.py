import io
import json
from pathlib import Path
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
import pytest

from master_duel_advisor.chatgpt_auth import (ChatGPTAuth, ConnectionStore, ISSUER, PLAN_SCOPE,
    discovery, token_record, validate_identity)
from master_duel_advisor.chatgpt_strategy import ChatGPTStrategy
from master_duel_advisor.chatgpt_transport import ChatGPTError, Transport, official_url
from master_duel_advisor.llm_fallback import StrategyChoice

META={"issuer":ISSUER,"authorization_endpoint":ISSUER+"/api/accounts/authorize",
      "token_endpoint":ISSUER+"/api/accounts/oauth/token","jwks_uri":ISSUER+"/.well-known/jwks.json",
      "revocation_endpoint":ISSUER+"/oauth/revoke"}


@pytest.fixture
def signing():
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    public=json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    public.update(kid="fixture",use="sig",alg="RS256")
    def make(**updates):
        claims=dict(iss=ISSUER,aud="oaiapp_test",sub="subject",exp=int(time.time())+300,
                    iat=int(time.time()),nonce="nonce",email="test@example.invalid")
        claims.update(updates)
        return jwt.encode(claims,key,algorithm="RS256",headers={"kid":"fixture"})
    return public,make


def test_real_signature_and_all_identity_claims(signing):
    public,make=signing
    transport=SimpleNamespace(json=lambda _: {"keys":[public]})
    assert validate_identity(make(),"oaiapp_test","nonce",META,transport)["sub"]=="subject"
    for changed in [dict(iss="https://evil.invalid"),dict(aud="oaiapp_other"),dict(nonce="other"),
                    dict(exp=1),dict(sub=""),dict(azp="oaiapp_other")]:
        with pytest.raises(ChatGPTError): validate_identity(make(**changed),"oaiapp_test","nonce",META,transport)
    damaged=make().split("."); damaged[2]="AAAA"
    with pytest.raises(ChatGPTError): validate_identity(".".join(damaged),"oaiapp_test","nonce",META,transport)


def test_storage_is_atomic_and_windows_encrypted(tmp_path):
    store=ConnectionStore(tmp_path/"auth")
    with store.locked():
        data=store.read();data["secret"]="TOKEN_NEVER_PLAINTEXT";store.write(data)
    assert store.read()==data
    import os
    if os.name=="nt":
        assert b"TOKEN_NEVER_PLAINTEXT" not in (store.path/"connections.bin").read_bytes()
    else:
        assert (store.path/"connections.bin").stat().st_mode & 0o777 == 0o600
    assert not list(store.path.glob(".credentials-*"))


def profile(store,expired=False,scopes=None):
    record=token_record(dict(access_token="old-access",refresh_token="old-refresh",token_type="Bearer",
                      expires_in=3600,scope=PLAN_SCOPE if scopes is None else scopes),"oaiapp_test",
                      dict(iss=ISSUER,sub="subject",email="test@example.invalid"))
    if expired: record["expires_at"]=1
    with store.locked():
        data=store.read();data["active"]="oaiapp_test";data["profiles"]["oaiapp_test"]=record;store.write(data)
    return record


def test_refresh_rotation_status_no_tokens_and_revocation(tmp_path):
    store=ConnectionStore(tmp_path);profile(store,True)
    requests=[]
    def request(url,form=None,**kwargs):
        requests.append((url,form))
        if url.endswith("openid-configuration"): return META
        if url.endswith("token"):
            assert form["refresh_token"]=="old-refresh" and "scope" not in form
            return dict(access_token="new-access",refresh_token="new-refresh",token_type="Bearer",expires_in=3600,scope=PLAN_SCOPE)
        assert form["token"]=="new-refresh"; return {}
    auth=ChatGPTAuth(store,SimpleNamespace(json=request))
    assert auth.access_token()=="new-access"
    assert auth.access_token()=="new-access"
    assert len([f for _,f in requests if f and f.get("grant_type")=="refresh_token"])==1
    assert "access" not in json.dumps(auth.status()) and "refresh" not in json.dumps(auth.status())
    assert auth.logout()["remote_revocation_confirmed"]
    assert not auth.status()["profiles"][0]["signed_in"]
    assert auth.store.read()["profiles"]["oaiapp_test"]["subject"]=="subject"
    with pytest.raises(ChatGPTError,match="login_required"): auth.access_token()


def test_permission_missing_and_remote_revoke_failure(tmp_path):
    store=ConnectionStore(tmp_path);profile(store,scopes="openid")
    def denied(*a,**kw): raise ChatGPTError("network_or_timeout")
    auth=ChatGPTAuth(store,SimpleNamespace(json=denied))
    with pytest.raises(ChatGPTError,match="plan_permission_required"): auth.access_token()
    assert not auth.logout()["remote_revocation_confirmed"]
    assert not auth.status()["profiles"][0]["signed_in"]


@pytest.mark.parametrize("url",["http://auth.openai.com/x","https://auth.openai.com.evil.invalid/x",
    "https://evil.invalid/x","https://name:secret@auth.openai.com/x","https://auth.openai.com:444/x"])
def test_discovery_cannot_redirect_tokens(url):
    with pytest.raises(ChatGPTError): official_url(url,"auth.openai.com")
    modified={**META,"token_endpoint":url}
    with pytest.raises(ChatGPTError): discovery(SimpleNamespace(json=lambda _:modified))


@pytest.mark.parametrize("outcome",["success","deny","wrong_state","missing_client","swapped_client","wrong_identity"])
def test_login_pkce_one_time_callback_and_identity(monkeypatch,tmp_path,signing,outcome):
    public,make=signing
    captured={}
    class Server:
        server_port=1455
        def __init__(self,address,handler):
            assert address==("127.0.0.1",0)
            self.handler=handler;self.count=0
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def handle_request(self):
            if self.count: raise AssertionError("認証コールバックを待つはずがありません")
            self.count+=1
            launch=parse_qs(urlsplit(captured["start"]).query)["ticket"][0]
            handler=object.__new__(self.handler);handler.path="/start?ticket="+launch;handler.wfile=io.BytesIO()
            handler.send_response=lambda *a:None;handler.end_headers=lambda:None
            handler.send_header=lambda k,v: captured.update(authorize=v) if k=="Location" else None
            handler.send_error=lambda *a: captured.update(rejected=True)
            handler.do_GET()
            params=parse_qs(urlsplit(captured["authorize"]).query);captured["params"]=params
            callback={"state":params["state"][0],"code":"fixture-code","client_id":"oaiapp_test"}
            if outcome=="deny": callback["error"]="access_denied"
            if outcome=="wrong_state":
                handler.path="/auth/callback?state=bad&code=fixture-code";handler.do_GET()
                assert captured["rejected"]
            if outcome=="missing_client": callback.pop("client_id")
            if outcome=="swapped_client": callback["client_id"]="oaiapp_other"
            from urllib.parse import urlencode
            handler.path="/auth/callback?"+urlencode(callback);handler.do_GET()
            handler.do_GET();assert captured["rejected"]  # 一度受信したcodeを再利用しない
    monkeypatch.setattr("master_duel_advisor.chatgpt_auth.HTTPServer",Server)
    store=ConnectionStore(tmp_path)
    if outcome in {"swapped_client","wrong_identity"}: profile(store)
    def request(url,form=None):
        if url.endswith("openid-configuration"): return META
        if url==META["jwks_uri"]: return {"keys":[public]}
        assert form["redirect_uri"]==captured["params"]["redirect_uri"][0]
        assert form["client_id"]=="oaiapp_test" and "client_secret" not in form
        import base64,hashlib
        assert base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest()).rstrip(b"=").decode()==captured["params"]["code_challenge"][0]
        return dict(access_token="fixture-access",refresh_token="fixture-refresh",token_type="Bearer",expires_in=3600,
            scope=PLAN_SCOPE,id_token=make(nonce=captured["params"]["nonce"][0],sub="another" if outcome=="wrong_identity" else "subject"))
    auth=ChatGPTAuth(store,SimpleNamespace(json=request))
    def announce(text): captured["start"]=text.split(": ",1)[1]
    if outcome in {"deny","missing_client","swapped_client","wrong_identity"}:
        with pytest.raises(ChatGPTError): auth.login(open_browser=False,announce=announce)
        assert "fixture-access" not in str(auth.store.read())
    else:
        assert auth.login(open_browser=False,announce=announce)["plan_enabled"]
    params=captured["params"]
    assert params["scope"][0].split()[-1]==PLAN_SCOPE
    assert params["resource"]==["https://api.openai.com/v1"]


def test_strategy_uses_account_catalog_no_key_and_supported_payload():
    seen=[]
    class FakeTransport:
        def json(self,url,token):
            assert token=="oauth-token"
            return {"models":[{"slug":"allowed","visibility":"list","display_name":"Allowed"},
                              {"slug":"hidden","visibility":"hidden"}]}
        def responses(self,token,payload):
            assert token=="oauth-token";seen.append(payload);return {"fixture":True}
    auth=SimpleNamespace(transport=FakeTransport(),access_token=lambda:"oauth-token")
    strategy=ChatGPTStrategy(auth,"allowed")
    assert strategy({"visible_actions":[]},StrategyChoice.model_json_schema())=={"fixture":True}
    payload=seen[0]
    assert payload["store"] is False and payload["stream"] is True
    assert payload["input"][0]["role"]=="user" and payload["text"]["format"]["strict"] is True
    assert not {"max_output_tokens","temperature","previous_response_id","api_key"}&payload.keys()
    strategy.model="hidden"
    with pytest.raises(ChatGPTError,match="choose_available_model"): strategy({}, {})


@pytest.mark.parametrize("terminal",["completed","failed","incomplete","missing","refused"])
@pytest.mark.parametrize("content_type",["text/event-stream",""])
def test_stream_must_complete_and_discard_partial_output(terminal,content_type):
    events=[{"type":"response.output_text.delta","delta":'{"action":"CONFIRM"}'}]
    if terminal=="completed": events.append({"type":"response.completed","response":{"status":"completed"}})
    if terminal=="failed": events.append({"type":"response.failed","response":{"error":{"code":"subscription_sharing_usage_limit_exceeded"}}})
    if terminal=="incomplete": events.append({"type":"response.incomplete"})
    if terminal=="refused": events.append({"type":"response.refusal.delta"})
    response=io.BytesIO(b"".join(b"data: "+json.dumps(e).encode()+b"\n\n" for e in events))
    response.headers={"Content-Type":content_type}
    transport=Transport();transport._open=lambda *a:response
    if terminal=="completed": assert transport.responses("oauth",{})=={"action":"CONFIRM"}
    else:
        with pytest.raises(ChatGPTError): transport.responses("oauth",{})


def test_missing_content_type_cannot_accept_non_sse_body():
    response=io.BytesIO(b'{"output": "do not accept"}\n')
    response.headers={}
    transport=Transport();transport._open=lambda *a:response
    with pytest.raises(ChatGPTError,match="invalid_stream_framing"): transport.responses("oauth",{})


def test_cli_has_explicit_opt_in_and_no_login_required_for_normal_run():
    from master_duel_advisor.cli import parser,enable_chatgpt
    args=parser().parse_args(["run","--video","v.mp4","--calibration","c.json","--database","d.db"])
    pipeline=SimpleNamespace(strategy_fallback=None)
    enable_chatgpt(pipeline,args)
    assert pipeline.strategy_fallback is None
    args.chatgpt=True
    with pytest.raises(ValueError,match="chatgpt-models"): enable_chatgpt(pipeline,args)


def test_pipeline_awaits_strategy_for_ambiguous_baseline_without_blocking():
    from master_duel_advisor.models import Action,GameState,Observation
    from master_duel_advisor.pipeline import Pipeline
    at=time.monotonic()
    actions=[Action(type="ACTIVATE",source_region=f"action.{i}",confidence=1,observed_at=at) for i in range(2)]
    state=GameState(sequence=0,captured_at=at,prompt=Observation(value="none",confidence=1,observed_at=at),visible_actions=actions)
    requested=[]
    fallback=SimpleNamespace(calls=0,poll=lambda *_:None,request=lambda s,r:requested.append(r))
    perception=SimpleNamespace(process=lambda _:state,cards=SimpleNamespace(get=lambda _:None),cache_hits=0,recognized_regions=0)
    pipeline=Pipeline(perception,rules=SimpleNamespace(generate=lambda *_:actions),strategy_fallback=fallback)
    result=pipeline.process(None)
    assert result["recommendation"]["action"] is None
    assert requested==["ambiguous_routes"]
