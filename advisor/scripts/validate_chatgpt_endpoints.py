"""認証情報なしで公式discovery/JWKSの互換性を確認します。"""
from pathlib import Path
from master_duel_advisor.chatgpt_auth import discovery
from master_duel_advisor.chatgpt_transport import Transport
from master_duel_advisor.pipeline import save_json


def main():
    transport=Transport()
    metadata=discovery(transport)
    keys=transport.json(metadata["jwks_uri"])
    report={"issuer":metadata["issuer"],"authorization_endpoint":metadata["authorization_endpoint"],
            "token_endpoint":metadata["token_endpoint"],"jwks_uri":metadata["jwks_uri"],
            "jwks_algorithms":sorted({key.get("alg",key.get("kty","unknown")) for key in keys["keys"]}),
            "key_count":len(keys["keys"]),"login_verified":False,"inference_verified":False}
    save_json(Path("artifacts/chatgpt-endpoint-validation.json"),report)
    print(report)


if __name__=="__main__": main()
