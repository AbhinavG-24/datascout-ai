import os, io, csv, json, threading
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
import db, engine

app = FastAPI(title="DataScout")
HERE = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
threading.Thread(target=engine.scheduler, daemon=True).start()
for t in db.all("SELECT id FROM tasks WHERE status NOT IN ('done','failed','cancelled')"): db.run("UPDATE tasks SET status='failed',error='Interrupted by restart' WHERE id=?", (t["id"],))

class New(BaseModel):
    prompt: str; fields: list[str] = []; max_pages: int = 10; depth: int = 0; interval: int = 0; delay: float = 1.0
class Patch(BaseModel):
    title: Optional[str] = None; interval: Optional[int] = None
class RecPatch(BaseModel):
    data: Optional[dict] = None; starred: Optional[bool] = None

def T(r):
    r["plan"] = json.loads(r["plan"] or "{}"); r["stats"] = json.loads(r["stats"] or "{}"); r["opts"] = json.loads(r["opts"] or "{}"); return r
def R(x):
    x["data"] = json.loads(x["data"]); x["flags"] = json.loads(x["flags"] or "[]"); x["prev"] = json.loads(x["prev"]) if x["prev"] else None; return x

@app.get("/")
def index(): return FileResponse(os.path.join(HERE, "static", "index.html"))

@app.get("/api/health")
def health(): return {"ai": bool(engine.KEY), "model": engine.MODEL if engine.KEY else None}

@app.post("/api/tasks")
def create(b: New):
    if not b.prompt.strip(): raise HTTPException(400, "prompt required")
    o = {"fields": b.fields, "max_pages": min(max(b.max_pages, 1), 100), "depth": min(max(b.depth, 0), 2), "delay": max(b.delay, .3)}
    tid = db.run("INSERT INTO tasks(prompt,title,status,opts,interval,created,updated) VALUES(?,?,?,?,?,?,?)",
                 (b.prompt.strip(), b.prompt[:60], "queued", json.dumps(o), max(b.interval, 0), db.now(), db.now()))
    engine.launch(tid); return {"id": tid}

@app.get("/api/tasks")
def tasks():
    rows = [T(r) for r in db.all("SELECT * FROM tasks ORDER BY id DESC")]
    for r in rows: r["counts"] = db.one("SELECT COUNT(*) n, SUM(status='new') new, SUM(status='changed') changed FROM records WHERE task_id=? AND status!='removed'", (r["id"],))
    return rows

@app.get("/api/summary")
def summary():
    return {"tasks": db.one("SELECT COUNT(*) n FROM tasks")["n"], "records": db.one("SELECT COUNT(*) n FROM records WHERE status!='removed'")["n"],
            "sources": db.one("SELECT COUNT(DISTINCT host) n FROM sources WHERE status='ok'")["n"]}

@app.get("/api/tasks/{tid}")
def task(tid: int):
    r = db.one("SELECT * FROM tasks WHERE id=?", (tid,))
    if not r: raise HTTPException(404)
    r = T(r); r["records"] = [R(x) for x in db.all("SELECT * FROM records WHERE task_id=?", (tid,))]
    r["sources"] = db.all("SELECT * FROM sources WHERE task_id=? ORDER BY id", (tid,)); r["logs"] = db.all("SELECT ts,level,msg FROM logs WHERE task_id=? ORDER BY id", (tid,))
    return r

@app.patch("/api/tasks/{tid}")
def patch(tid: int, p: Patch):
    if p.title is not None: db.run("UPDATE tasks SET title=? WHERE id=?", (p.title[:100], tid))
    if p.interval is not None:
        nr = (datetime.now(timezone.utc) + timedelta(minutes=p.interval)).isoformat(timespec="seconds") if p.interval > 0 else None
        db.run("UPDATE tasks SET interval=?,next_run=? WHERE id=?", (max(p.interval, 0), nr, tid))
    return {"ok": True}

@app.post("/api/tasks/{tid}/rerun")
def rerun(tid: int):
    db.run("UPDATE tasks SET status='queued' WHERE id=?", (tid,)); engine.launch(tid); return {"ok": True}

@app.post("/api/tasks/{tid}/clone")
def clone(tid: int):
    t = db.one("SELECT * FROM tasks WHERE id=?", (tid,)); 
    n = db.run("INSERT INTO tasks(prompt,title,status,plan,opts,interval,created,updated) VALUES(?,?,?,?,?,?,?,?)",
               (t["prompt"], t["title"] + " (copy)", "queued", t["plan"], t["opts"], 0, db.now(), db.now()))
    engine.launch(n); return {"id": n}

@app.post("/api/tasks/{tid}/cancel")
def cancel(tid: int):
    if engine.status(tid) in ("planning", "discovering", "collecting"): engine.setstate(tid, status="cancelled")
    return {"ok": True}

@app.delete("/api/tasks/{tid}")
def delete(tid: int):
    for t in ("records", "sources", "logs"): db.run(f"DELETE FROM {t} WHERE task_id=?", (tid,))
    db.run("DELETE FROM tasks WHERE id=?", (tid,)); return {"ok": True}

@app.patch("/api/records/{rid}")
def rpatch(rid: int, p: RecPatch):
    if p.starred is not None: db.run("UPDATE records SET starred=? WHERE id=?", (int(p.starred), rid))
    if p.data is not None: db.run("UPDATE records SET data=?,flags='[]',conf=1.0,method='manual' WHERE id=?", (json.dumps(p.data), rid))
    return {"ok": True}

@app.delete("/api/records/{rid}")
def rdel(rid: int): db.run("DELETE FROM records WHERE id=?", (rid,)); return {"ok": True}

@app.post("/api/records/bulk")
def bulk(b: dict):
    ids = [int(i) for i in b.get("ids", [])]; ph = ",".join("?" * len(ids))
    if ids and b.get("action") == "delete": db.run(f"DELETE FROM records WHERE id IN ({ph})", ids)
    if ids and b.get("action") in ("star", "unstar"): db.run(f"UPDATE records SET starred=? WHERE id IN ({ph})", [int(b["action"] == "star"), *ids])
    return {"ok": True}

@app.get("/api/tasks/{tid}/export")
def export(tid: int, fmt: str = "csv", ids: str = Query("")):
    t = task(tid); keys = [f["key"] for f in t["plan"].get("schema", [])]; sel = {int(i) for i in ids.split(",") if i}
    rows = [{**r["data"], "source_url": r["source_url"], "evidence": r["evidence"], "confidence": r["conf"], "status": r["status"],
             "flags": "; ".join(r["flags"]), "fetched_at": r["fetched_at"]} for r in t["records"] if (not sel or r["id"] in sel)]
    fn = f"datascout_task{tid}.{fmt}"
    if fmt == "json": return Response(json.dumps({"prompt": t["prompt"], "exported": db.now(), "records": rows}, indent=2), media_type="application/json", headers={"Content-Disposition": f"attachment; filename={fn}"})
    if fmt == "ndjson": return Response("\n".join(json.dumps(r) for r in rows), media_type="application/x-ndjson", headers={"Content-Disposition": f"attachment; filename={fn}"})
    b = io.StringIO(); w = csv.DictWriter(b, fieldnames=keys + ["source_url", "evidence", "confidence", "status", "flags", "fetched_at"]); w.writeheader(); w.writerows(rows)
    return Response(b.getvalue(), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={fn}"})
