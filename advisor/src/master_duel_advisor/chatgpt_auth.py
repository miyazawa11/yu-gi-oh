"""Sign in with ChatGPT: PKCE、検証済みID、保護されたローカル接続。"""
import base64
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import tempfile
import time
from urllib.parse import parse_qs, urlencode, urlsplit
import uuid
import webbrowser

from .chatgpt_transport import ChatGPTError, Transport, official_url

ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
PLAN_SCOPE = "chatgpt.tokens.use.direct"
DEFAULT_STORAGE = Path(".chatgpt")


def dpapi(data, encrypt):
    """WindowsログインユーザーのDPAPI。トークンは平文ファイルにしません。"""
    class Blob(ctypes.Structure):
        _fields_ = [("size",wintypes.DWORD),("data",ctypes.POINTER(ctypes.c_ubyte))]
    source_buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data),ctypes.cast(source_buffer,ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    api = ctypes.WinDLL("crypt32",use_last_error=True)
    fn = api.CryptProtectData if encrypt else api.CryptUnprotectData
    fn.argtypes = [ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(source),None,None,None,None,1,ctypes.byref(result)):
        raise ChatGPTError("credential_protection_failed")
    try: return ctypes.string_at(result.data,result.size)
    finally:
        kernel = ctypes.WinDLL("kernel32")
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        kernel.LocalFree(result.data)


class ConnectionStore:
    def __init__(self,path=DEFAULT_STORAGE):
        self.path = Path(path)

    def _prepare(self):
        self.path.mkdir(parents=True,exist_ok=True,mode=0o700)
        if os.name != "nt": self.path.chmod(0o700)

    @contextmanager
    def locked(self):
        self._prepare()
        with (self.path/"session.lock").open("a+b") as handle:
            handle.seek(0)
            if not handle.read(1): handle.write(b"0"); handle.flush()
            deadline = time.monotonic()+10
            while True:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
                    else:
                        import fcntl
                        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline: raise ChatGPTError("session_busy") from None
                    time.sleep(.05)
            try: yield
            finally:
                handle.seek(0)
                if os.name == "nt": msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
                else: fcntl.flock(handle,fcntl.LOCK_UN)

    def read(self):
        file = self.path/"connections.bin"
        if not file.exists(): return {"host_id":"urn:uuid:"+str(uuid.uuid4()),"active":None,"profiles":{}}
        raw = file.read_bytes()
        if raw.startswith(b"DPAPI1\n") and os.name == "nt": raw = dpapi(raw[7:],False)
        elif raw.startswith(b"POSIX1\n") and os.name != "nt": raw = raw[7:]
        else: raise ChatGPTError("credential_storage_incompatible")
        try: return json.loads(raw)
        except ValueError: raise ChatGPTError("credential_storage_invalid") from None

    def write(self,value):
        self._prepare()
        raw = json.dumps(value,ensure_ascii=False,allow_nan=False).encode()
        raw = b"DPAPI1\n"+dpapi(raw,True) if os.name=="nt" else b"POSIX1\n"+raw
        fd,temporary = tempfile.mkstemp(dir=self.path,prefix=".credentials-")
        try:
            with os.fdopen(fd,"wb") as stream:
                if os.name != "nt": os.fchmod(stream.fileno(),0o600)
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary,self.path/"connections.bin")
        finally:
            if os.path.exists(temporary): os.unlink(temporary)


def discovery(transport):
    data = transport.json(ISSUER+"/.well-known/openid-configuration")
    if data.get("issuer") != ISSUER: raise ChatGPTError("invalid_issuer")
    for key in ["authorization_endpoint","token_endpoint","jwks_uri"]:
        official_url(data[key],"auth.openai.com")
    return data


def validate_identity(token,client_id,nonce,metadata,transport):
    import jwt
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256": raise ChatGPTError("unsupported_id_signature")
        keys = transport.json(metadata["jwks_uri"])["keys"]
        matches = [key for key in keys if key.get("kid")==header.get("kid") and key.get("kty")=="RSA"
                   and key.get("use","sig")=="sig" and key.get("alg","RS256")=="RS256"]
        if len(matches)!=1: raise ChatGPTError("id_key_not_found")
        key = jwt.PyJWK.from_dict(matches[0]).key
        claims = jwt.decode(token,key,algorithms=["RS256"],audience=client_id,issuer=ISSUER,
                            options={"require":["iss","aud","sub","exp","iat","nonce"]})
        if not isinstance(claims["sub"],str) or not claims["sub"] or claims.get("nonce")!=nonce:
            raise ChatGPTError("id_identity_or_nonce_mismatch")
        if claims.get("azp",client_id)!=client_id: raise ChatGPTError("id_audience_mismatch")
        return claims
    except ChatGPTError: raise
    except Exception: raise ChatGPTError("invalid_id_token") from None


def token_record(reply,client_id,claims,previous=None):
    if not isinstance(reply.get("access_token"),str) or not reply["access_token"] or reply.get("token_type","").lower()!="bearer":
        raise ChatGPTError("invalid_token_response")
    seconds = reply.get("expires_in")
    if not isinstance(seconds,(int,float)) or not 0 < seconds <= 86400: raise ChatGPTError("invalid_token_expiry")
    refresh = reply.get("refresh_token")
    if not isinstance(refresh,str) or not refresh: raise ChatGPTError("missing_refresh_token")
    record = dict(previous or {})
    record.update(client_id=client_id,issuer=claims["iss"],subject=claims["sub"],email=claims.get("email"),
                  access_token=reply["access_token"],refresh_token=refresh,expires_at=time.time()+seconds,
                  scopes=str(reply.get("scope","")).split())
    if "id_token" in reply: record["id_token"] = reply["id_token"]
    return record


class ChatGPTAuth:
    def __init__(self,store=None,transport=None):
        self.store = store or ConnectionStore()
        self.transport = transport or Transport()

    def status(self):
        with self.store.locked(): data = self.store.read()
        return {"active":data["active"],"profiles":[{"id":pid,"email":p.get("email"),
                "signed_in":bool(p.get("access_token")),"plan_enabled":PLAN_SCOPE in p.get("scopes",[])}
                for pid,p in data["profiles"].items()]}

    def select(self,profile):
        with self.store.locked():
            data=self.store.read()
            if profile not in data["profiles"]: raise ChatGPTError("profile_not_found")
            data["active"]=profile; self.store.write(data)

    def login(self,profile=None,new=False,timeout=300,open_browser=True,announce=print):
        if not 1<=timeout<=600: raise ValueError("ログイン待機は1〜600秒です")
        metadata = discovery(self.transport)
        with self.store.locked():
            data=self.store.read()
            selected = None if new else (profile or data["active"])
            prior=data["profiles"].get(selected) if selected else None
            if selected and prior is None: raise ChatGPTError("profile_not_found")
            self.store.write(data)  # 初回host IDを認証前に永続化
        verifier,nonce,state = secrets.token_urlsafe(48),secrets.token_urlsafe(32),secrets.token_urlsafe(32)
        result = {}
        launch = secrets.token_urlsafe(32)
        class Callback(BaseHTTPRequestHandler):
            def log_message(self,*args): pass  # code/token/URLを記録しない
            def do_GET(self):
                parsed=urlsplit(self.path)
                query=parse_qs(parsed.query)
                if parsed.path=="/start" and query.get("ticket")==[launch] and not result:
                    self.send_response(302);self.send_header("Location",authorize);self.send_header("Cache-Control","no-store");self.end_headers();return
                if parsed.path!="/auth/callback" or query.get("state")!=[state] or result:
                    self.send_error(400,"Invalid callback");return
                result.update(query)
                message="認証結果を受け取りました。ターミナルで接続状態を確認してください。".encode()
                self.send_response(200);self.send_header("Content-Type","text/plain; charset=utf-8")
                self.send_header("Cache-Control","no-store");self.send_header("Content-Length",str(len(message)));self.end_headers();self.wfile.write(message)
        with HTTPServer(("127.0.0.1",0),Callback) as server:
            server.timeout=.25
            redirect=f"http://127.0.0.1:{server.server_port}/auth/callback"
            params={"client_id":prior["client_id"] if prior else "dynamic_agent_client","ext_agent_host_id":data["host_id"],
                    "response_type":"code","redirect_uri":redirect,"scope":SCOPES,"resource":RESOURCE,"state":state,"nonce":nonce,
                    "code_challenge_method":"S256","code_challenge":base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()}
            if not prior: params["agent_name_hint"]="Master Duel Local Advisor"
            authorize=metadata["authorization_endpoint"]+"?"+urlencode(params)
            start_url=f"http://127.0.0.1:{server.server_port}/start?"+urlencode({"ticket":launch})
            announce("Continue with ChatGPT: "+start_url)
            if open_browser: webbrowser.open(start_url)
            deadline=time.monotonic()+timeout
            while not result and time.monotonic()<deadline: server.handle_request()
        if not result: raise ChatGPTError("login_timeout")
        if "error" in result: raise ChatGPTError("authorization_denied")
        if result.get("code") is None or len(result["code"])!=1: raise ChatGPTError("invalid_callback")
        ids=result.get("client_id",[prior["client_id"]] if prior else [])
        if len(ids)!=1 or not ids[0].startswith("oaiapp_"): raise ChatGPTError("missing_issued_client")
        client_id=ids[0]
        if prior and client_id!=prior["client_id"]: raise ChatGPTError("client_identity_mismatch")
        reply=self.transport.json(metadata["token_endpoint"],form={"grant_type":"authorization_code","client_id":client_id,
            "code":result["code"][0],"code_verifier":verifier,"redirect_uri":redirect,"resource":RESOURCE})
        claims=validate_identity(reply.get("id_token"),client_id,nonce,metadata,self.transport)
        if prior and (claims["iss"],claims["sub"])!=(prior["issuer"],prior["subject"]): raise ChatGPTError("account_identity_mismatch")
        record=token_record(reply,client_id,claims,prior)
        with self.store.locked():
            current=self.store.read()
            current["profiles"][client_id]=record;current["active"]=client_id;self.store.write(current)
        return {"profile":client_id,"plan_enabled":PLAN_SCOPE in record["scopes"]}

    def access_token(self):
        with self.store.locked():
            data=self.store.read();profile=data["profiles"].get(data["active"])
            if not profile or not profile.get("access_token"): raise ChatGPTError("login_required")
            if PLAN_SCOPE not in profile.get("scopes",[]): raise ChatGPTError("plan_permission_required")
            if time.time()+30 >= profile["expires_at"]:
                metadata=discovery(self.transport)
                reply=self.transport.json(metadata["token_endpoint"],form={"grant_type":"refresh_token","client_id":profile["client_id"],
                    "refresh_token":profile["refresh_token"],"resource":RESOURCE})
                # 更新レスポンスのIDトークンはログインに使わず、検証済み登録のidentityを維持。
                updated=token_record(reply,profile["client_id"],{"iss":profile["issuer"],"sub":profile["subject"],"email":profile.get("email")},profile)
                if "id_token" in reply: updated["id_token"]=profile.get("id_token")
                data["profiles"][data["active"]]=updated;self.store.write(data);profile=updated
                if PLAN_SCOPE not in profile["scopes"]: raise ChatGPTError("plan_permission_required")
            return profile["access_token"]

    def logout(self):
        revoked=True
        with self.store.locked():
            data=self.store.read();profile=data["profiles"].get(data["active"])
            if not profile: return {"signed_out":True,"remote_revocation_confirmed":True}
            if profile.get("refresh_token"):
                try:
                    metadata=discovery(self.transport)
                    endpoint=official_url(metadata["revocation_endpoint"],"auth.openai.com")
                    self.transport.json(endpoint,form={"token":profile["refresh_token"],"token_type_hint":"refresh_token","client_id":profile["client_id"]})
                except (ChatGPTError,KeyError): revoked=False
            for key in ["access_token","refresh_token","id_token","expires_at","scopes"]: profile.pop(key,None)
            self.store.write(data)
        return {"signed_out":True,"remote_revocation_confirmed":revoked}
