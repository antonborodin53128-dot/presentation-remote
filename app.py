from flask import Flask, request, jsonify, render_template
from threading import Lock
import os, time

app=Flask(__name__)
LOCK=Lock()
ROOMS={}
ONLINE_SECONDS=12

def clean_login(v):
    return "".join(ch for ch in str(v or "").strip().lower() if ch.isalnum() or ch in "_-")[:40]

def room(login):
    return ROOMS.setdefault(login,{"next_id":0,"devices":{}})

def online_devices(r):
    now=time.time()
    return {k:v for k,v in r["devices"].items() if now-float(v.get("seen",0))<=ONLINE_SECONDS}

@app.get("/")
def remote():
    return render_template("remote.html")

@app.get("/health")
def health():
    return jsonify(ok=True)

@app.post("/api/register")
def register():
    x=request.json or {}; login=clean_login(x.get("login")); dev=str(x.get("device_id",""))[:100]
    if len(login)<2 or not dev:return jsonify(ok=False),400
    with LOCK:
        d=room(login)["devices"].setdefault(dev,{"seen":0,"queue":[]})
        d["seen"]=time.time()
    return jsonify(ok=True)

@app.post("/api/heartbeat")
def heartbeat():
    x=request.json or {}; login=clean_login(x.get("login")); dev=str(x.get("device_id",""))[:100]
    if len(login)<2 or not dev:return jsonify(ok=False),400
    with LOCK:
        room(login)["devices"].setdefault(dev,{"seen":0,"queue":[]})["seen"]=time.time()
    return jsonify(ok=True)

@app.get("/api/poll")
def poll():
    login=clean_login(request.args.get("login")); dev=str(request.args.get("device_id",""))[:100]
    if len(login)<2 or not dev:return jsonify(ok=False),400
    with LOCK:
        d=room(login)["devices"].setdefault(dev,{"seen":0,"queue":[]})
        d["seen"]=time.time()
        if d["queue"]:
            c=d["queue"][0]
            return jsonify(ok=True,id=c["id"],command=c["command"])
    return jsonify(ok=True,id=0,command="")

@app.post("/api/ack")
def ack():
    x=request.json or {}; login=clean_login(x.get("login")); dev=str(x.get("device_id",""))[:100]; cid=int(x.get("id",0) or 0)
    if len(login)<2 or not dev or cid<=0:return jsonify(ok=False),400
    with LOCK:
        d=room(login)["devices"].setdefault(dev,{"seen":0,"queue":[]})
        d["seen"]=time.time()
        d["queue"]=[c for c in d["queue"] if int(c["id"])!=cid]
    return jsonify(ok=True)

@app.post("/api/command")
def command():
    x=request.json or {}; login=clean_login(x.get("login")); cmd=str(x.get("command",""))
    if len(login)<2 or cmd not in ("next","prev"):return jsonify(ok=False),400
    with LOCK:
        r=room(login); targets=online_devices(r)
        r["next_id"]+=1; cid=r["next_id"]
        for d in targets.values():
            d["queue"].append({"id":cid,"command":cmd})
    return jsonify(ok=True,id=cid)

@app.get("/api/status")
def status():
    login=clean_login(request.args.get("login"))
    if len(login)<2:return jsonify(ok=True,online=0)
    with LOCK:n=len(online_devices(room(login)))
    return jsonify(ok=True,online=n)
 
@app.get("/api/devices")
def devices():
    login=clean_login(request.args.get("login"))
    if len(login)<2:return jsonify(ok=True,devices=[])
    now=time.time()
    with LOCK:
        items=[{"id":dev[-6:].upper(),"online":now-float(d.get("seen",0))<=ONLINE_SECONDS}
               for dev,d in room(login)["devices"].items()
               if now-float(d.get("seen",0))<=60]
    return jsonify(ok=True,devices=items)

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT",10000)))
