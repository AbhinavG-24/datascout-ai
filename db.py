import os, sqlite3, threading
from datetime import datetime, timezone
DB = os.environ.get("DB", "datascout2.db")
now = lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
_lk = threading.Lock()

def conn():
    c = sqlite3.connect(DB, timeout=30); c.row_factory = sqlite3.Row; return c

def run(sql, args=()):
    with _lk:
        c = conn(); cur = c.execute(sql, args); c.commit(); i = cur.lastrowid; c.close(); return i

def all(sql, args=()):
    c = conn(); r = [dict(x) for x in c.execute(sql, args).fetchall()]; c.close(); return r

def one(sql, args=()):
    r = all(sql, args); return r[0] if r else None

def init():
    c = conn(); c.executescript("""
    CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY, prompt TEXT, title TEXT, status TEXT, plan TEXT, opts TEXT,
      stats TEXT, error TEXT, runs INT DEFAULT 0, interval INT DEFAULT 0, next_run TEXT, created TEXT, updated TEXT);
    CREATE TABLE IF NOT EXISTS records(id INTEGER PRIMARY KEY, task_id INT, key TEXT, data TEXT, source_url TEXT, evidence TEXT,
      flags TEXT, conf REAL, method TEXT, fetched_at TEXT, status TEXT, hash TEXT, prev TEXT, seen INT DEFAULT 1,
      starred INT DEFAULT 0, first_seen TEXT, last_seen TEXT);
    CREATE INDEX IF NOT EXISTS rk ON records(task_id,key);
    CREATE TABLE IF NOT EXISTS sources(id INTEGER PRIMARY KEY, task_id INT, url TEXT, host TEXT, status TEXT, http INT,
      records INT DEFAULT 0, note TEXT, depth INT, fetched_at TEXT);
    CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY, task_id INT, ts TEXT, level TEXT, msg TEXT);""")
    c.commit(); c.close()
init()
