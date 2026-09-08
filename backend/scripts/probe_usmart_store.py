#!/usr/bin/env python3
"""探测盈立客户端 Vuex store 结构，定位持仓数据"""
import json, urllib.request

def discover():
    with urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=5) as r:
        pages = json.loads(r.read().decode())
    for p in pages:
        if "index.html" in p.get("url", ""):
            return p.get("webSocketDebuggerUrl")
    return None

WS = discover()
if not WS:
    print("NO_PAGE"); raise SystemExit

import websocket
ws = websocket.create_connection(WS, timeout=30)

def evl(expr):
    ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                        "params": {"expression": expr, "awaitPromise": True, "returnByValue": True}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") != 1: continue
        r = msg.get("result", {})
        if "exceptionDetails" in r:
            return {"error": r["exceptionDetails"].get("text", "")}
        return r.get("result", {}).get("value")

# 1) store 顶层模块
r = evl("""(function(){
  var app = document.querySelector('#app');
  if (!app || !app.__vue__) return {ok:false, reason:'no-vue'};
  var st = app.__vue__.$store.state;
  var keys = Object.keys(st).filter(function(k){ return !k.startsWith('_'); });
  var shape = {};
  keys.forEach(function(k){
    var v = st[k];
    if (v && typeof v === 'object') {
      shape[k] = Object.keys(v).slice(0, 12);
    } else {
      shape[k] = typeof v;
    }
  });
  return {ok:true, modules: shape};
})()""")
print("STORE_MODULES:", json.dumps(r, ensure_ascii=False)[:3000])

ws.close()
