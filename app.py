from flask import Flask, request, jsonify, render_template
from flask_socketio import SocketIO, join_room
from threading import Lock
import os, time

app=Flask(__name__)
socketio=SocketIO(app, cors_allowed_origins="*", async_mode="threading",
                  ping_interval=10, ping_timeout=20)
LOCK=Lock()
ROOMS={}
ONLINE_SECONDS=20

def clean_login(v):
    return "".join(ch for ch in str(v or "").strip().lower()
                   if ch.isalnum() or ch in "_-")[:40]

def room(login):
    return ROOMS.setdefault(login,{"next_id":0,"devices":{},"remotes":{}})

def online_devices(r):
    now=time.time()
    return {k:v for k,v in r["devices"].items()
            if now-float(v.get("seen",0))<=ONLINE_SECONDS}

@app.get("/")
def remote():
    return render_template("remote.html")

@app.get("/health")
def health():
    return jsonify(ok=True)

def touch(login,dev,sid=None):
    r=room(login)
    d=r["devices"].setdefault(dev,{"seen":0,"queue":[],"sid":None})
    d["seen"]=time.time()
    if sid is not None:d["sid"]=sid
    return d

@app.post("/api/register")
def register():
    x=request.json or {}; login=clean_login(x.get("login")); dev=str(x.get("device_id",""))[:100]
    if len(login)<2 or not dev:return jsonify(ok=False),400
    with LOCK:touch(login,dev)
    return jsonify(ok=True)

@app.post("/api/heartbeat")
def heartbeat():
    x=request.json or {}; login=clean_login(x.get("login")); dev=str(x.get("device_id",""))[:100]
    if len(login)<2 or not dev:return jsonify(ok=False),400
    with LOCK:touch(login,dev)
    return jsonify(ok=True)

@app.get("/api/poll")
def poll():
    login=clean_login(request.args.get("login")); dev=str(request.args.get("device_id",""))[:100]
    if len(login)<2 or not dev:return jsonify(ok=False),400
    with LOCK:
        d=touch(login,dev)
        if d["queue"]:
            c=d["queue"][0]
            return jsonify(ok=True,id=c["id"],command=c["command"])
    return jsonify(ok=True,id=0,command="")

@app.post("/api/ack")
def ack():
    x=request.json or {}; login=clean_login(x.get("login")); dev=str(x.get("device_id",""))[:100]; cid=int(x.get("id",0) or 0)
    if len(login)<2 or not dev or cid<=0:return jsonify(ok=False),400
    with LOCK:
        d=touch(login,dev)
        d["queue"]=[c for c in d["queue"] if int(c["id"])!=cid]
    return jsonify(ok=True)

def issue_command(login,cmd):
    with LOCK:
        r=room(login); targets=online_devices(r)
        r["next_id"]+=1; cid=r["next_id"]
        deliveries=[]
        for dev,d in targets.items():
            c={"id":cid,"command":cmd}
            d["queue"].append(c)
            if d.get("sid"):deliveries.append((d["sid"],c))
    for sid,c in deliveries:
        socketio.emit("command",c,to=sid)
    return cid

@app.post("/api/command")
def command():
    x=request.json or {}; login=clean_login(x.get("login")); cmd=str(x.get("command",""))
    if len(login)<2 or cmd not in ("next","prev"):return jsonify(ok=False),400
    return jsonify(ok=True,id=issue_command(login,cmd))

@app.post("/api/remote-heartbeat")
def remote_heartbeat():
    x=request.json or {}
    login=clean_login(x.get("login"))
    rid=str(x.get("remote_id",""))[:100]
    if len(login)<2 or not rid:return jsonify(ok=False),400
    with LOCK:
        room(login)["remotes"][rid]=time.time()
    return jsonify(ok=True)

@app.get("/api/remote-status")
def remote_status():
    login=clean_login(request.args.get("login"))
    if len(login)<2:return jsonify(ok=True,online=0)
    now=time.time()
    with LOCK:
        r=room(login)
        r["remotes"]={k:v for k,v in r.get("remotes",{}).items() if now-float(v)<=60}
        n=sum(1 for v in r["remotes"].values() if now-float(v)<=12)
    return jsonify(ok=True,online=n)

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
        items=[{"id":dev[-6:].upper(),"online":now-float(d.get("seen",0))<=ONLINE_SECONDS,
                "realtime":bool(d.get("sid"))}
               for dev,d in room(login)["devices"].items()
               if now-float(d.get("seen",0))<=60]
    return jsonify(ok=True,devices=items)

@socketio.on("register")
def ws_register(data):
    login=clean_login((data or {}).get("login")); dev=str((data or {}).get("device_id",""))[:100]
    if len(login)<2 or not dev:return {"ok":False}
    join_room("login:"+login)
    with LOCK:
        d=touch(login,dev,request.sid)
        queued=list(d["queue"])
    for c in queued:socketio.emit("command",c,to=request.sid)
    return {"ok":True}

@socketio.on("heartbeat")
def ws_heartbeat(data):
    login=clean_login((data or {}).get("login")); dev=str((data or {}).get("device_id",""))[:100]
    if len(login)>=2 and dev:
        with LOCK:touch(login,dev,request.sid)

@socketio.on("ack")
def ws_ack(data):
    login=clean_login((data or {}).get("login")); dev=str((data or {}).get("device_id",""))[:100]; cid=int((data or {}).get("id",0) or 0)
    if len(login)>=2 and dev and cid:
        with LOCK:
            d=touch(login,dev,request.sid)
            d["queue"]=[c for c in d["queue"] if int(c["id"])!=cid]

if __name__=="__main__":
    socketio.run(app,host="0.0.0.0",port=int(os.environ.get("PORT",10000)))
