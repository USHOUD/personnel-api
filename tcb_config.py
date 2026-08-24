#!/usr/bin/env python3
import requests, json

ENV_ID = "personnel-api-d0gsohasr28067fae"

# 从环境变量或文件读取API Key
import os
API_KEY = os.environ.get("TCB_API_KEY", "")
if not API_KEY:
    key_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".apikey")
    if os.path.exists(key_file):
        with open(key_file) as f:
            API_KEY = f.read().strip()

BASE_URL = "https://api.weixin.qq.com/tcb"

def _post(action, query):
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + API_KEY
    }
    payload = {
        "env": ENV_ID,
        "query": query
    }
    r = requests.post(BASE_URL + "/" + action, headers=headers, json=payload, timeout=15)
    return r.json()

def tcb_query(collection, where=None, limit=1000, offset=0):
    q = 'db.collection("' + collection + '")'
    if where:
        q += ".where(" + json.dumps(where, ensure_ascii=False) + ")"
    q += ".skip(" + str(offset) + ").limit(" + str(limit) + ").get()"
    d = _post("databasequery", q)
    if "data" in d:
        return json.loads(d["data"]) if isinstance(d["data"], str) else d["data"]
    return []

def tcb_count(collection, where=None):
    q = 'db.collection("' + collection + '")'
    if where:
        q += ".where(" + json.dumps(where, ensure_ascii=False) + ")"
    q += ".count()"
    return _post("databasecount", q).get("count", 0)

def tcb_add(collection, data_dict):
    q = 'db.collection("' + collection + '").add({data:' + json.dumps(data_dict, ensure_ascii=False) + '})'
    return _post("databaseadd", q)

def tcb_update(collection, where, data_dict):
    w = json.dumps(where, ensure_ascii=False)
    d = json.dumps(data_dict, ensure_ascii=False)
    q = 'db.collection("' + collection + '").where(' + w + ').update({data:' + d + '})'
    return _post("databaseupdate", q)

def tcb_delete(collection, where):
    w = json.dumps(where, ensure_ascii=False)
    q = 'db.collection("' + collection + '").where(' + w + ').remove()'
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
