#!/usr/bin/env python3
import requests, json, time, os

APP_ID = "wx7673bf714bb43454"
ENV_ID = "personnel-api-d0gsohasr28067fae"

def _get_secret():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".secret")
    with open(p) as f:
        return f.read().strip()

_token_cache = {"t": None, "e": 0}

def get_access_token():
    now = time.time()
    if _token_cache["t"] and now < _token_cache["e"]:
        return _token_cache["t"]
    secret = _get_secret()
    r = requests.get("https://api.weixin.qq.com/cgi-bin/token", params={"grant_type":"client_credential","appid":APP_ID,"secret":secret}, timeout=10)
    d = r.json()
    if "access_token" in d:
        _token_cache["t"] = d["access_token"]
        _token_cache["e"] = now + d["expires_in"] - 300
        return d["access_token"]
    raise Exception("token fail: " + str(d))

def _post(api, query):
    t = get_access_token()
    r = requests.post("https://api.weixin.qq.com/tcb/"+api, params={"access_token":t}, json={"env":ENV_ID,"query":query}, timeout=15)
    return r.json()

def tcb_query(collection, where=None, limit=1000, offset=0):
    q = 'db.collection("'+collection+'")'
    if where:
        q += ".where("+json.dumps(where, ensure_ascii=False)+")"
    q += ".skip("+str(offset)+").limit("+str(limit)+").get()"
    d = _post("databasequery", q)
    if "data" in d:
        return json.loads(d["data"]) if isinstance(d["data"], str) else d["data"]
    return []

def tcb_count(collection, where=None):
    q = 'db.collection("'+collection+'")'
    if where:
        q += ".where("+json.dumps(where, ensure_ascii=False)+")"
    q += ".count()"
    return _post("databasecount", q).get("count", 0)

def tcb_add(collection, data_dict):
    q = 'db.collection("'+collection+'").add({data:'+json.dumps(data_dict, ensure_ascii=False)+'})'
    return _post("databaseadd", q)

def tcb_update(collection, where, data_dict):
    w = json.dumps(where, ensure_ascii=False)
    d = json.dumps(data_dict, ensure_ascii=False)
    q = 'db.collection("'+collection+'").where('+w+').update({data:'+d+'})'
    return _post("databaseupdate", q)

def tcb_delete(collection, where):
    w = json.dumps(where, ensure_ascii=False)
    q = 'db.collection("'+collection+'").where('+w+').remove()'
    return _post("databasedelete", q)

def tcb_batch_add(collection, data_list):
    ok, fail = 0, 0
    for item in data_list:
        r = tcb_add(collection, item)
        if r.get("errcode", 0) == 0:
            ok += 1
        else:
            fail += 1
    return {"success": ok, "fail": fail}
