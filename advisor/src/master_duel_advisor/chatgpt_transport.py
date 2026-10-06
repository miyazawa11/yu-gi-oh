"""公式OAuth/Responses向けの有限時間HTTP通信。認証情報をエラーに含めません。"""
import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler


class ChatGPTError(RuntimeError):
    def __init__(self, code, status=None):
        self.code = code if isinstance(code,str) and re.fullmatch(r"[a-zA-Z0-9_.-]{1,100}",code) else "request_failed"
        self.status = status
        super().__init__(f"ChatGPT接続: {self.code}" + (f" (HTTP {status})" if status else ""))


def official_url(url, host):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != host or parsed.port not in {None,443}
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ChatGPTError("invalid_official_endpoint")
    return url


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ChatGPTError("unexpected_redirect")


class Transport:
    def __init__(self, timeout=10):
        if not 0 < timeout <= 60:
            raise ValueError("通信期限は0〜60秒で指定してください")
        self.timeout = timeout
        self.opener = build_opener(NoRedirect())
        self.last_response_metadata = None

    def _open(self, url, data=None, token=None, content_type=None):
        host = urlsplit(url).hostname
        if host not in {"auth.openai.com","api.openai.com"}:
            raise ChatGPTError("invalid_official_endpoint")
        official_url(url,host)
        headers = {"Accept":"application/json", "User-Agent":"master-duel-advisor/0.1"}
        if token: headers["Authorization"] = "Bearer " + token
        if content_type: headers["Content-Type"] = content_type
        try:
            return self.opener.open(Request(url,data=data,headers=headers),timeout=self.timeout)
        except HTTPError as exc:
            try:
                error = json.loads(exc.read(65536)).get("error",{})
                code = error.get("code", "http_error") if isinstance(error,dict) else error
            except Exception:
                code = "http_error"
            raise ChatGPTError(code,exc.code) from None
        except (URLError,TimeoutError,OSError):
            raise ChatGPTError("network_or_timeout") from None

    def json(self,url,form=None,token=None):
        payload = urlencode(form).encode() if form is not None else None
        with self._open(url,payload,token,"application/x-www-form-urlencoded" if form is not None else None) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ChatGPTError("response_too_large")
        if not raw:
            return {}
        try: return json.loads(raw)
        except (ValueError,UnicodeError): raise ChatGPTError("invalid_json") from None

    def responses(self,token,payload):
        started = time.monotonic()
        chunks,lines,size = [],[],0
        completed = False
        with self._open("https://api.openai.com/v1/responses",json.dumps(payload,ensure_ascii=False,allow_nan=False).encode(),
                        token,"application/json") as response:
            self.last_response_metadata = {"status":getattr(response,"status",None),"content_type":response.headers.get("Content-Type","")}
            content_type=response.headers.get("Content-Type","")
            # 実環境でContent-Typeが省略されたSSEを確認。本文はイベントとして厳格に検査します。
            if content_type and "text/event-stream" not in content_type:
                raise ChatGPTError("expected_event_stream")
            while True:
                if time.monotonic()-started > self.timeout:
                    raise ChatGPTError("inference_timeout")
                line = response.readline(65537)
                size += len(line)
                if len(line)>65536 or size>2_000_000:
                    raise ChatGPTError("response_too_large")
                if not line:
                    break
                if line.strip():
                    if line.startswith(b"data:"):
                        lines.append(line[5:].strip())
                    elif not line.startswith((b"event:",b":",b"id:",b"retry:")):
                        raise ChatGPTError("invalid_stream_framing")
                    continue
                if not lines: continue
                try: event = json.loads(b"\n".join(lines))
                except ValueError: raise ChatGPTError("invalid_stream_event") from None
                lines.clear()
                kind = event.get("type")
                if kind == "response.output_text.delta": chunks.append(event["delta"])
                elif kind in {"response.failed","error"}:
                    error = event.get("response",{}).get("error") or event.get("error") or event
                    raise ChatGPTError(error.get("code","response_failed"))
                elif kind == "response.incomplete": raise ChatGPTError("response_incomplete")
                elif kind == "response.refusal.delta": raise ChatGPTError("response_refused")
                elif kind == "response.completed":
                    if event.get("response",{}).get("status") != "completed":
                        raise ChatGPTError("response_not_completed")
                    completed = True
                    break
        if not completed: raise ChatGPTError("stream_interrupted")
        try: return json.loads("".join(chunks))
        except ValueError: raise ChatGPTError("invalid_strategy_json") from None
