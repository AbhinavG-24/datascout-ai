"""Workflow engine: plan -> discover -> crawl (robots-aware, parallel) -> extract -> validate -> dedupe -> upsert."""
import os, re, json, hashlib, difflib, threading, time
from urllib.parse import urlparse, urljoin, unquote, parse_qs, urlencode, urlunparse
from urllib import robotparser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import httpx
from bs4 import BeautifulSoup
import db

KEY = os.environ.get("ANTHROPIC_API_KEY")
MODEL = os.environ.get("MODEL", "claude-sonnet-5-5")
UA = "DataScoutBot/0.2 (research prototype; respects robots.txt)"
http = httpx.Client(headers={"User-Agent": UA}, timeout=20, follow_redirects=True, trust_env=False)
norm = lambda s: re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?:\+\d{1,3}[\s.-]?)?(?:\(?\d{2,5}\)?[\s.-]){1,4}\d{3,5}")
SKIP_T = {"WebSite", "WebPage", "BreadcrumbList", "ListItem", "SearchAction", "ImageObject", "SiteNavigationElement", "ItemList", "CollectionPage"}
SYN = {"name": ["title", "headline", "company", "organization"], "title": ["name", "headline", "position", "role"],
       "description": ["summary", "about", "abstract"], "url": ["link", "website", "sameas", "href"],
       "phone": ["telephone", "tel", "mobile"], "email": ["mail"], "location": ["address", "city", "locality", "region"],
       "company": ["hiringorganization", "organization", "employer"], "date": ["dateposted", "published", "deadline", "validthrough"],
       "salary": ["basesalary", "pay", "compensation"]}

def setstate(tid, **kw):
    kw["updated"] = db.now(); db.run(f"UPDATE tasks SET {','.join(k+'=?' for k in kw)} WHERE id=?", (*kw.values(), tid))
def log(tid, msg, lvl="info"): db.run("INSERT INTO logs(task_id,ts,level,msg) VALUES(?,?,?,?)", (tid, db.now(), lvl, msg))
def status(tid):
    r = db.one("SELECT status FROM tasks WHERE id=?", (tid,)); return r["status"] if r else "deleted"

# ---------- LLM / planning ----------
def llm(system, user, n=4000):
    r = http.post("https://api.anthropic.com/v1/messages", timeout=90, headers={"x-api-key": KEY, "anthropic-version": "2023-06-01"},
                  json={"model": MODEL, "max_tokens": n, "system": system, "messages": [{"role": "user", "content": user}]})
    r.raise_for_status(); return "".join(b.get("text", "") for b in r.json()["content"])
def pj(t):
    m = re.search(r"\{.*\}", t, re.S); return json.loads(m.group(0)) if m else {}

def make_plan(prompt, fields):
    seeds = re.findall(r"https?://[^\s,)\]]+", prompt); q = re.sub(r"https?://\S+", "", prompt).strip()
    custom = [{"key": re.sub(r"\W+", "_", f.lower()).strip("_"), "label": f.strip().title()} for f in fields if f.strip()]
    if KEY:
        try:
            p = pj(llm("You plan web data-collection workflows. JSON only.", f'''Request: "{prompt}"
Required fields (if any): {[f["key"] for f in custom]}
Return {{"title":"short title","schema":[{{"key":"snake_case","label":"Label"}}] (3-7 fields, first = entity name; use required fields if given),
"queries":["2-4 web search queries"],"keywords":["5-8 words that indicate a relevant page/link"],"seed_urls":[]}}'''))
            p["seed_urls"] = list(dict.fromkeys(seeds + p.get("seed_urls", []))); p["mode"] = "AI"; return p
        except Exception: pass
    words = [w for w in norm(q).split() if len(w) > 3][:8]
    return {"title": (q or prompt)[:60], "schema": custom or [{"key": k, "label": k.title()} for k in ("name", "description", "url", "email", "phone")],
            "queries": [q] if q else [], "keywords": words, "seed_urls": seeds, "mode": "heuristic"}

# ---------- Discovery / fetching ----------
def clean_url(u):
    p = urlparse(u.strip()); qs = [(k, v) for k, v in [x.split("=", 1) if "=" in x else (x, "") for x in p.query.split("&") if x]
                                   if not k.startswith("utm_") and k not in ("fbclid", "gclid")]
    return urlunparse((p.scheme, p.netloc.lower(), p.path.rstrip("/") or "/", "", urlencode(qs), ""))

def search(q, n=8):
    try:
        r = http.post("https://html.duckduckgo.com/html/", data={"q": q}, headers={"User-Agent": "Mozilla/5.0"})
        out = []
        for a in BeautifulSoup(r.text, "html.parser").select("a.result__a"):
            h = a.get("href", "")
            if "uddg=" in h: h = unquote(parse_qs(urlparse(h).query).get("uddg", [""])[0])
            if h.startswith("http"): out.append(clean_url(h))
        return out[:n]
    except Exception: return []

_rob, _last, _lk = {}, {}, threading.Lock()
def allowed(url):
    u = urlparse(url); base = f"{u.scheme}://{u.netloc}"
    if base not in _rob:
        rp = robotparser.RobotFileParser()
        try:
            r = http.get(base + "/robots.txt", timeout=10)
            if r.status_code in (401, 403): rp.disallow_all = True
            elif r.status_code == 200: rp.parse(r.text.splitlines())
            else: rp.allow_all = True
        except Exception: rp.allow_all = True
        _rob[base] = rp
    return _rob[base].can_fetch(UA, url)

def polite(host, delay):
    with _lk:
        w = max(0, _last.get(host, 0) + delay - time.time()); _last[host] = time.time() + w
    if w: time.sleep(w)

# ---------- Extraction ----------
def flat(d, pre=""):
    o = {}
    if isinstance(d, dict):
        for k, v in d.items():
            if k.startswith("@"): continue
            o.update(flat(v, pre + k))
    elif isinstance(d, list):
        for v in d[:3]:
            for k, x in flat(v, pre).items(): o.setdefault(k, x)
    elif d not in (None, ""): o[pre] = str(d)
    return o

def pick(c, key):
    kn = norm(key).replace(" ", ""); best, bs = "", 0
    for ck, v in c.items():
        cn = norm(ck).replace(" ", "")
        if not v: continue
        s = 2 if (cn == "url" and any(w in kn for w in ("url", "link", "website", "site"))) else 3 if cn == kn else 2 if (cn.endswith(kn) or cn.startswith(kn)) else 1 if (len(kn) > 2 and kn in cn) or any(y in cn for y in SYN.get(kn, [])) else 0
        if s > bs or (s == bs and s and len(cn) < len(norm(best))): best, bs = v, s
    return best

def candidates(soup, url, text):
    out = []
    for s in soup.find_all("script", type="application/ld+json"):
        try: d = json.loads(s.string or "")
        except Exception: continue
        for it in (d.get("@graph", [d]) if isinstance(d, dict) else d):
            if isinstance(it, dict) and str(it.get("@type", "")) not in SKIP_T:
                c = flat(it); c.setdefault("url", url); out.append((c, "jsonld"))
    for t in soup.find_all("table"):
        rows = t.find_all("tr")
        if len(rows) < 3: continue
        hs = [h.get_text(" ", strip=True) for h in rows[0].find_all(["th", "td"])]
        for tr in rows[1:80]:
            cells = tr.find_all(["td", "th"])
            if len(cells) == len(hs):
                c = {h: x.get_text(" ", strip=True) for h, x in zip(hs, cells)}; a = tr.find("a", href=True)
                if a: c["url"] = urljoin(url, a["href"])
                out.append((c, "table"))
    if not out:
        md = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
        c = {"title": (soup.title.string or "").strip() if soup.title and soup.title.string else url,
             "description": (md.get("content", "") if md else "") or text[:200], "url": url,
             "email": ", ".join(sorted(set(EMAIL.findall(text)))[:3]),
             "phone": ", ".join(sorted({p.strip() for p in PHONE.findall(text) if 9 <= len(re.sub(r"\D", "", p)) <= 13})[:2])}
        for dt in soup.find_all("dt")[:30]:
            dd = dt.find_next_sibling("dd")
            if dd: c[dt.get_text(strip=True)] = dd.get_text(" ", strip=True)
        out.append((c, "page"))
    return out

def extract(html, url, plan, prompt):
    soup = BeautifulSoup(html, "html.parser"); keys = [f["key"] for f in plan["schema"]]
    links = [(a.get_text(" ", strip=True)[:60], urljoin(url, a["href"])) for a in soup.find_all("a", href=True)
             if a["href"].startswith(("http", "/")) and a.get_text(strip=True)][:400]
    cands = candidates(soup, url, "")
    for t in soup(["script", "style", "nav", "footer", "noscript"]): t.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()
    if not any(m == "jsonld" for _, m in cands):
        cands = [(c, m) for c, m in candidates(BeautifulSoup(html, "html.parser"), url, text)]
    recs = []
    if KEY and not any(m in ("jsonld", "table") for _, m in cands):
        try:
            out = pj(llm("You extract structured records from web page text. Use ONLY facts present in the text. JSON only.",
                f'''Request: "{prompt}"\nFields: {keys}\nURL: {url}\nLinks: {links[:40]}\nText:\n{text[:9000]}
Return {{"records":[{{<fields>,"evidence":"short verbatim snippet from the text"}}]}}. "" for unknown. {{"records":[]}} if nothing relevant.'''))
            recs = [({k: r.get(k, "") for k in keys}, str(r.get("evidence", "")), "llm") for r in out.get("records", [])]
        except Exception: pass
    if not recs:
        for c, m in cands:
            r = {k: pick(c, k) for k in keys}
            recs.append((r, " | ".join(f"{k}: {v}" for k, v in list(c.items())[:3])[:200], m))
    return recs, text, links

# ---------- Validation ----------
def clean(rec, ev, text, keys, method):
    d, fl = {}, []
    for k in keys:
        v = re.sub(r"\s+", " ", str(rec.get(k, "") or "")).strip()
        if "email" in k and v:
            m = EMAIL.findall(v); v = ", ".join(dict.fromkeys(m)); 
            if not m: fl.append("invalid email"); v = ""
        if k in ("url", "website", "link") and v:
            try: v = clean_url(v) if urlparse(v).scheme in ("http", "https") else (fl.append("invalid url") or "")
            except Exception: fl.append("invalid url"); v = ""
        d[k] = v
    if not d[keys[0]]: fl.append("missing name")
    empty = [k for k in keys[1:] if not d[k]]
    if len(empty) > len(keys) // 2: fl.append("mostly empty")
    if method == "llm":
        if not ev: fl.append("no evidence")
        elif norm(ev)[:50] not in norm(text): fl.append("evidence not on page")
    base = {"jsonld": .92, "table": .85, "llm": .88, "page": .6}.get(method, .5)
    return d, fl, round(max(.1, base - .18 * len(fl)), 2)

# ---------- Workflow ----------
def run(tid):
    try:
        t = db.one("SELECT * FROM tasks WHERE id=?", (tid,)); o = json.loads(t["opts"] or "{}")
        maxp, depth, delay = int(o.get("max_pages", 10)), int(o.get("depth", 0)), float(o.get("delay", 1))
        runno = (t["runs"] or 0) + 1; setstate(tid, status="planning", runs=runno, error=None)
        db.run("DELETE FROM sources WHERE task_id=?", (tid,)); db.run("UPDATE records SET seen=0 WHERE task_id=?", (tid,))
        plan = json.loads(t["plan"]) if t["plan"] else make_plan(t["prompt"], o.get("fields", []))
        keys = [f["key"] for f in plan["schema"]]; setstate(tid, title=plan["title"], plan=json.dumps(plan))
        log(tid, f"Run #{runno} · planner={plan['mode']} · fields={keys}")
        setstate(tid, status="discovering"); urls = [clean_url(u) for u in plan["seed_urls"]]
        for q in plan["queries"]:
            f = search(q); log(tid, f"Search '{q}' → {len(f)} results", "info" if f else "warn"); urls += f
        urls = list(dict.fromkeys(urls))
        if not urls: raise RuntimeError("No source URLs. Add URLs to the prompt or check internet access.")
        st = {"pages": 0, "blocked": 0, "failed": 0, "raw": 0, "duplicates": 0, "kept": 0, "new": 0, "changed": 0}
        seen, lk, visited, frontier = [], threading.Lock(), set(), urls[:maxp * 2]
        kw = [w.lower() for w in plan.get("keywords", [])]
        setstate(tid, status="collecting")

        def process(u, d):
            if status(tid) != "collecting": return []
            host = urlparse(u).netloc
            sid = db.run("INSERT INTO sources(task_id,url,host,status,depth) VALUES(?,?,?,?,?)", (tid, u, host, "pending", d))
            try:
                if not allowed(u):
                    st["blocked"] += 1; db.run("UPDATE sources SET status='blocked',note='robots.txt disallows' WHERE id=?", (sid,)); log(tid, f"BLOCKED by robots.txt: {u}", "warn"); return []
                polite(host, delay)
                r = http.get(u)
                if r.status_code >= 400 or "html" not in r.headers.get("content-type", ""): raise ValueError(f"HTTP {r.status_code} / {r.headers.get('content-type','?')[:30]}")
                recs, text, links = extract(r.text[:1_500_000], u, plan, t["prompt"]); n = 0
                with lk:
                    st["pages"] += 1
                    for rec, ev, m in recs:
                        st["raw"] += 1; data, fl, conf = clean(rec, ev, text, keys, m); k = norm(data[keys[0]]) or norm(u)
                        if any(k == s or difflib.SequenceMatcher(None, k, s).ratio() > .93 for s in seen): st["duplicates"] += 1; continue
                        seen.append(k); h = hashlib.md5(json.dumps(data, sort_keys=True).encode()).hexdigest(); ts = db.now()
                        old = db.one("SELECT id,hash,data FROM records WHERE task_id=? AND key=?", (tid, k))
                        if old:
                            s2 = "unchanged" if old["hash"] == h else "changed"; st["changed"] += s2 == "changed"
                            db.run("UPDATE records SET data=?,source_url=?,evidence=?,flags=?,conf=?,method=?,fetched_at=?,status=?,hash=?,prev=?,seen=1,last_seen=? WHERE id=?",
                                   (json.dumps(data), u, ev, json.dumps(fl), conf, m, ts, s2, h, old["data"] if s2 == "changed" else None, ts, old["id"]))
                        else:
                            s2 = "new" if runno > 1 else "active"; st["new"] += s2 == "new"
                            db.run("INSERT INTO records(task_id,key,data,source_url,evidence,flags,conf,method,fetched_at,status,hash,first_seen,last_seen) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                   (tid, k, json.dumps(data), u, ev, json.dumps(fl), conf, m, ts, s2, h, ts, ts))
                        st["kept"] += 1; n += 1
                db.run("UPDATE sources SET status='ok',http=?,records=?,fetched_at=? WHERE id=?", (r.status_code, n, db.now(), sid))
                log(tid, f"Fetched {u} → {n} records")
                setstate(tid, stats=json.dumps(st))
                if d < depth and kw:
                    sc = [(sum(w in (t_ + l).lower() for w in kw), l) for t_, l in links if urlparse(l).netloc == host]
                    return [l for s, l in sorted(sc, reverse=True) if s > 0][:8]
            except Exception as e:
                st["failed"] += 1; db.run("UPDATE sources SET status='failed',note=? WHERE id=?", (str(e)[:150], sid)); log(tid, f"FAILED {u}: {e}", "error")
            return []

        d = 0
        while frontier and len(visited) < maxp and d <= depth:
            batch = [clean_url(u) for u in frontier if clean_url(u) not in visited][:maxp - len(visited)]; visited |= set(batch)
            with ThreadPoolExecutor(4) as ex: nxt = list(ex.map(lambda u: process(u, d), batch))
            frontier = [l for x in nxt for l in x]; d += 1
        if status(tid) != "collecting": log(tid, "Cancelled by user.", "warn"); return
        setstate(tid, status="validating")
        removed = db.run("UPDATE records SET status='removed' WHERE task_id=? AND seen=0 AND status!='removed'", (tid,))
        nxt_run = (datetime.now(timezone.utc) + timedelta(minutes=t["interval"])).isoformat(timespec="seconds") if t["interval"] else None
        setstate(tid, status="done", stats=json.dumps(st), next_run=nxt_run); log(tid, f"Done · {st}")
    except Exception as e:
        setstate(tid, status="failed", error=str(e)); log(tid, f"ERROR: {e}", "error")

def launch(tid): threading.Thread(target=run, args=(tid,), daemon=True).start()

def scheduler():
    while True:
        time.sleep(20)
        try:
            for t in db.all("SELECT id,next_run FROM tasks WHERE interval>0 AND status IN ('done','failed') AND next_run IS NOT NULL"):
                if t["next_run"] <= db.now(): setstate(t["id"], status="queued", next_run=None); launch(t["id"])
        except Exception: pass
