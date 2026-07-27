#!/usr/bin/env python3
"""
PM Jobs Board — MVP aggregator (v2)
===================================
Pulls live Product Manager roles from the public, no-auth Greenhouse Job Board
API, Lever Postings API, and Ashby Job Postings API for a seed list of
companies, normalizes them into one schema, de-duplicates, and generates a
self-contained job board:

    dist/index.html   <- the board (data embedded; also deployed to GitHub Pages)
    dist/jobs.json    <- the raw normalized data

Run:
    python3 pm_jobs_board.py

v2 features:
  * Star/save jobs (persists in the visitor's browser)
  * Hide/dismiss jobs, with an undo view
  * "New" badges on roles posted since your last visit
  * Priority keywords — matching titles pin to the top (edit PRIORITY_KEYWORDS)
  * Salary extraction from Greenhouse job descriptions (best effort)
  * Live countdown to the next scheduled refresh (7:00 AM Pacific)

No pip installs required (stdlib only). Add/remove companies in SEED_COMPANIES.
Wrong tokens are harmless: the run report shows which boards resolved.
"""

import json
import re
import sys
import time
import html as html_mod
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. CONFIG — edit me.
# ---------------------------------------------------------------------------
# Titles containing any of these pin to the top of the board with a tag.
PRIORITY_KEYWORDS = ["risk", "fraud", "payments", "identity", "platform"]

# Daily refresh time shown in the countdown (matches refresh.yml's schedule).
REFRESH_HOUR_PT = 7  # 7:00 AM America/Los_Angeles

SEED_COMPANIES = {
    "greenhouse": [
        # fintech
        "affirm", "brex", "chime", "gusto", "marqeta", "mercury", "sofi",
        "carta", "checkr", "current", "stripe", "coinbase", "robinhood",
        # consumer / marketplace
        "airbnb", "instacart", "doordashusa", "pinterest", "lyft", "reddit",
        "duolingo", "discord", "roblox",
        # infra / dev / AI
        "figma", "databricks", "scaleai", "anthropic", "cloudflare",
        "dropbox", "airtable", "vercel",
        "gitlab", "datadog", "mongodb", "asana", "intercom", "amplitude",
    ],
    "lever": [
        "netflix", "palantir", "kraken", "voleon",
        "mistral", "spotify", "plaid",
    ],
    "ashby": [
        "socure", "ramp", "openai", "notion", "linear", "deel",
    ],
}

GH_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
LEVER_URL = "https://api.lever.co/v0/postings/{site}?mode=json"
ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/{name}?includeCompensation=true"
TIMEOUT = 15
HEADERS = {"User-Agent": "pm-jobs-board-mvp/0.2 (personal project)"}

# ---------------------------------------------------------------------------
# 2. PM title filter + level classifier
# ---------------------------------------------------------------------------
PM_INCLUDE = re.compile(
    r"product (manager|management|lead|owner)"
    r"|(head|director|vp|vice president|chief)[,]? (of )?product"
    r"|\bapm\b|associate product",
    re.I,
)
PM_EXCLUDE = re.compile(
    r"project manager|production|product market|product design|product analyst"
    r"|product counsel|product support|product specialist|product security",
    re.I,
)

LEVELS = [
    (re.compile(r"\bintern\b", re.I), "Intern"),
    (re.compile(r"associate|\bapm\b", re.I), "APM"),
    (re.compile(r"\bprincipal\b", re.I), "Principal"),
    (re.compile(r"\bstaff\b", re.I), "Staff"),
    (re.compile(r"\bgroup\b|\bgpm\b", re.I), "Group PM"),
    (re.compile(r"director", re.I), "Director"),
    (re.compile(r"\bvp\b|vice president|head of|chief", re.I), "VP / Head"),
    (re.compile(r"senior|\bsr\.?\b|\blead\b", re.I), "Senior PM"),
]


def classify_level(title: str) -> str:
    for pattern, label in LEVELS:
        if pattern.search(title):
            return label
    return "PM"


def is_pm_role(title: str) -> bool:
    return bool(PM_INCLUDE.search(title)) and not PM_EXCLUDE.search(title)


# ---------------------------------------------------------------------------
# 3. Salary extraction from description text (best effort)
# ---------------------------------------------------------------------------
SAL_RANGE_RE = re.compile(
    r"\$\s?([\d,]+(?:\.\d+)?)\s*([kK])?\s*(?:-|–|—|&#8211;|to)\s*\$?\s?"
    r"([\d,]+(?:\.\d+)?)\s*([kK])?"
)


def extract_salary(description_html: str) -> str:
    """Find the first plausible '$X - $Y' annual range in a job description."""
    if not description_html:
        return ""
    text = html_mod.unescape(description_html)
    for m in SAL_RANGE_RE.finditer(text):
        lo_s, lo_k, hi_s, hi_k = m.groups()
        try:
            lo = float(lo_s.replace(",", ""))
            hi = float(hi_s.replace(",", ""))
        except ValueError:
            continue
        if lo_k:
            lo *= 1000
        if hi_k:
            hi *= 1000
        # If only one side had a k marker, scale the other to match.
        if lo_k and not hi_k and hi < 2000:
            hi *= 1000
        if hi_k and not lo_k and lo < 2000:
            lo *= 1000
        # Plausible annual USD range only (skips hourly rates and noise).
        if 40_000 <= lo < hi <= 1_500_000:
            return f"${int(lo):,}\u2013${int(hi):,}"
    return ""


# ---------------------------------------------------------------------------
# 4. Fetchers
# ---------------------------------------------------------------------------
def _get_json(url: str):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_greenhouse(token: str):
    data = _get_json(GH_URL.format(token=token))
    jobs = []
    for j in data.get("jobs", []):
        title = j.get("title", "") or ""
        if not is_pm_role(title):
            continue
        posted = j.get("first_published") or j.get("updated_at") or ""
        loc = ((j.get("location") or {}).get("name") or "").strip()
        jobs.append({
            "title": title.strip(),
            "company": (j.get("company_name") or token).strip(),
            "location": loc,
            "remote": "remote" in loc.lower(),
            "salary": extract_salary(j.get("content") or ""),
            "level": classify_level(title),
            "posted": posted,
            "url": j.get("absolute_url", ""),
            "source": "greenhouse",
        })
    return jobs


def _lever_salary(p: dict) -> str:
    s = p.get("salaryRange") or {}
    if not s or s.get("min") is None:
        return ""
    cur = s.get("currency", "USD")
    lo, hi = s.get("min"), s.get("max")
    try:
        return f"{cur} {int(lo):,}\u2013{int(hi):,}"
    except (TypeError, ValueError):
        return ""


def fetch_lever(site: str):
    data = _get_json(LEVER_URL.format(site=site))
    jobs = []
    for p in data if isinstance(data, list) else []:
        title = p.get("text", "") or ""
        if not is_pm_role(title):
            continue
        cats = p.get("categories") or {}
        created_ms = p.get("createdAt")
        posted = ""
        if created_ms:
            posted = datetime.fromtimestamp(
                created_ms / 1000, tz=timezone.utc
            ).isoformat()
        wt = (p.get("workplaceType") or "").lower()
        loc = (cats.get("location") or "").strip()
        jobs.append({
            "title": title.strip(),
            "company": site.capitalize(),
            "location": loc,
            "remote": wt == "remote" or "remote" in loc.lower(),
            "salary": _lever_salary(p),
            "level": classify_level(title),
            "posted": posted,
            "url": p.get("hostedUrl", ""),
            "source": "lever",
        })
    return jobs


def fetch_ashby(name: str):
    """Ashby public Job Postings API. Field names mapped defensively —
    if Ashby's payload differs, jobs still land with blanks, not crashes."""
    data = _get_json(ASHBY_URL.format(name=name))
    jobs = []
    for j in (data.get("jobs") or []):
        title = j.get("title", "") or ""
        if not is_pm_role(title):
            continue
        loc = (j.get("location") or "").strip()
        comp = ""
        c = j.get("compensation") or {}
        if isinstance(c, dict):
            comp = (c.get("compensationTierSummary") or "").strip()
        jobs.append({
            "title": title.strip(),
            "company": name.capitalize(),
            "location": loc,
            "remote": bool(j.get("isRemote")) or "remote" in loc.lower(),
            "salary": comp,
            "level": classify_level(title),
            "posted": j.get("publishedAt") or "",
            "url": j.get("jobUrl") or j.get("applyUrl") or "",
            "source": "ashby",
        })
    return jobs


# ---------------------------------------------------------------------------
# 5. Pipeline
# ---------------------------------------------------------------------------
def run():
    all_jobs, ok, failed = [], [], []
    plan = [("greenhouse", t, fetch_greenhouse) for t in SEED_COMPANIES["greenhouse"]]
    plan += [("lever", s, fetch_lever) for s in SEED_COMPANIES["lever"]]
    plan += [("ashby", a, fetch_ashby) for a in SEED_COMPANIES.get("ashby", [])]

    for source, token, fn in plan:
        jobs, err = None, None
        for attempt in (1, 2):  # one automatic retry for transient timeouts
            try:
                jobs = fn(token)
                break
            except urllib.error.HTTPError as e:
                err = f"HTTP {e.code}"
                if e.code == 404:
                    break  # bad token — retrying won't help
                time.sleep(2)
            except Exception as e:  # timeouts, DNS, JSON errors
                err = str(e)[:60]
                time.sleep(2)
        if jobs is not None:
            all_jobs.extend(jobs)
            ok.append((source, token, len(jobs)))
            print(f"  ok    {source:<10} {token:<14} {len(jobs)} PM roles")
        else:
            failed.append((source, token, err))
            print(f"  FAIL  {source:<10} {token:<14} {err}")
        time.sleep(0.4)  # be polite

    # de-dupe on (company, title, location)
    seen, deduped = set(), []
    for j in all_jobs:
        key = (j["company"].lower(), j["title"].lower(), j["location"].lower())
        if key not in seen:
            seen.add(key)
            deduped.append(j)

    # tag priority roles
    kws = [k.lower() for k in PRIORITY_KEYWORDS]
    for j in deduped:
        j["priority"] = any(k in j["title"].lower() for k in kws)

    deduped.sort(key=lambda j: j["posted"] or "", reverse=True)

    out = Path(__file__).resolve().parent / "dist"
    out.mkdir(exist_ok=True)
    (out / "jobs.json").write_text(json.dumps(deduped, indent=2), encoding="utf-8")
    (out / "index.html").write_text(render_html(deduped), encoding="utf-8")

    print("\n----------------------------------------")
    print(f"boards resolved : {len(ok)} / {len(plan)}")
    print(f"jobs collected  : {len(all_jobs)}  ->  {len(deduped)} after de-dupe")
    if failed:
        print("failed boards   : " + ", ".join(f"{t} ({e})" for _, t, e in failed))
        print("  (fix tokens in SEED_COMPANIES — check the careers page URL)")
    print(f"\nopen: {out.resolve() / 'index.html'}")


# ---------------------------------------------------------------------------
# 6. Static site template (data embedded — works from file:// or Pages)
# ---------------------------------------------------------------------------
def render_html(jobs) -> str:
    now_utc = datetime.now(timezone.utc)
    generated = now_utc.strftime("%Y-%m-%d %H:%M UTC")
    payload = json.dumps(jobs).replace("</", "<\\/")
    template = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PM Market — __COUNT__ open roles</title>
<style>
  :root{
    --paper:#f7f6f2; --ink:#16211c; --dim:#5c6a63; --line:#dcd9cf;
    --fresh:#0e7a4d; --card:#ffffff; --accent:#144733; --star:#b8860b;
  }
  @media (prefers-color-scheme: dark){
    :root{ --paper:#131715; --ink:#e8ece9; --dim:#93a09a; --line:#2a322e;
           --fresh:#4fc78f; --card:#1a201d; --accent:#bfe3d1; --star:#e8c252; }
  }
  *{box-sizing:border-box; margin:0}
  body{background:var(--paper); color:var(--ink);
       font:15px/1.5 "Avenir Next","Segoe UI",system-ui,sans-serif;
       padding:0 16px 64px}
  .wrap{max-width:920px; margin:0 auto}
  header{padding:36px 0 20px; border-bottom:2px solid var(--ink)}
  h1{font-size:26px; font-weight:700; letter-spacing:-.02em}
  h1 .tick{color:var(--fresh)}
  .meta{margin-top:6px; color:var(--dim);
        font:12px/1.4 "SF Mono",ui-monospace,Menlo,Consolas,monospace}
  .tape{display:flex; gap:24px; margin-top:14px; flex-wrap:wrap;
        font:12px "SF Mono",ui-monospace,Menlo,Consolas,monospace}
  .tape b{font-size:20px; display:block; font-family:inherit}
  .tape .up b{color:var(--fresh)}
  .filters{position:sticky; top:0; background:var(--paper); z-index:5;
           display:flex; gap:8px; flex-wrap:wrap; padding:14px 0;
           border-bottom:1px solid var(--line)}
  input,select{font:inherit; color:var(--ink); background:var(--card);
               border:1px solid var(--line); border-radius:6px; padding:8px 10px}
  input:focus,select:focus,button.act:focus{outline:2px solid var(--fresh); outline-offset:1px}
  #q{flex:1; min-width:150px}
  .job{display:flex; gap:12px; align-items:baseline; padding:14px 4px;
       border-bottom:1px solid var(--line); flex-wrap:wrap}
  .job.priority{background:color-mix(in srgb, var(--fresh) 6%, transparent)}
  .job .when{width:64px; flex-shrink:0; color:var(--dim);
             font:12px "SF Mono",ui-monospace,Menlo,Consolas,monospace}
  .job .when.fresh{color:var(--fresh); font-weight:700}
  .job .main{flex:1; min-width:220px}
  .job a{color:var(--ink); text-decoration:none; font-weight:600}
  .job a:hover{text-decoration:underline; text-underline-offset:3px}
  .sub{color:var(--dim); font-size:13px; margin-top:2px}
  .badges{display:flex; gap:6px; flex-shrink:0; align-items:center}
  .badge{font:11px "SF Mono",ui-monospace,Menlo,Consolas,monospace;
         border:1px solid var(--line); border-radius:999px; padding:2px 9px;
         color:var(--dim); white-space:nowrap}
  .badge.level{color:var(--accent); border-color:var(--accent)}
  .badge.remote{color:var(--fresh); border-color:var(--fresh)}
  .badge.new{color:var(--paper); background:var(--fresh); border-color:var(--fresh); font-weight:700}
  .badge.pri{color:var(--star); border-color:var(--star)}
  .salary{font:12px "SF Mono",ui-monospace,Menlo,Consolas,monospace; color:var(--ink)}
  button.act{background:none; border:1px solid var(--line); border-radius:6px;
             color:var(--dim); cursor:pointer; font-size:14px; line-height:1;
             padding:4px 8px}
  button.act:hover{border-color:var(--ink); color:var(--ink)}
  button.act.star.on{color:var(--star); border-color:var(--star)}
  .empty{padding:48px 0; text-align:center; color:var(--dim)}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>PM Market <span class="tick">▲</span></h1>
    <div class="meta">generated __GENERATED__ · refreshes daily ~7:00 AM PT · greenhouse + lever + ashby public APIs</div>
    <div class="tape">
      <div class="up"><b id="statFresh">0</b>new in 24h</div>
      <div><b id="statTotal">0</b>open roles</div>
      <div><b id="statSaved">0</b>saved</div>
      <div><b id="statNext">—</b>next refresh</div>
    </div>
  </header>
  <div class="filters">
    <input id="q" type="search" placeholder="Search title, company, location" aria-label="Search">
    <select id="view" aria-label="View">
      <option value="all">All roles</option>
      <option value="priority">Priority</option>
      <option value="saved">Saved ★</option>
      <option value="new">New since last visit</option>
      <option value="hidden">Hidden</option>
    </select>
    <select id="level" aria-label="Level"><option value="">All levels</option></select>
    <select id="remote" aria-label="Work mode">
      <option value="">Any</option><option value="1">Remote</option><option value="0">On-site / hybrid</option>
    </select>
    <select id="source" aria-label="Source"><option value="">All sources</option></select>
  </div>
  <div id="list"></div>
</div>
<script>
const JOBS = __PAYLOAD__;
const REFRESH_HOUR_PT = __REFRESH_HOUR__;
const els = { q:q, view:view, level:level, remote:remote, source:source, list:list };
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const now = Date.now();

/* --- persistent state (this browser only) --- */
const store = {
  get(k, d){ try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch(e){ return d; } },
  set(k, v){ try { localStorage.setItem(k, JSON.stringify(v)); } catch(e){} }
};
const saved  = new Set(store.get('pmb_saved',  []));
const hidden = new Set(store.get('pmb_hidden', []));
const prevVisit = store.get('pmb_lastvisit', null);
store.set('pmb_lastvisit', new Date().toISOString());

function age(iso){
  if(!iso) return {label:'—', fresh:false};
  const h = (now - Date.parse(iso)) / 36e5;
  if(isNaN(h)) return {label:'—', fresh:false};
  if(h < 24) return {label: Math.max(1,Math.round(h)) + 'h', fresh:true};
  return {label: Math.round(h/24) + 'd', fresh:false};
}
function isNew(j){
  if(!prevVisit || !j.posted) return false;
  const p = Date.parse(j.posted), v = Date.parse(prevVisit);
  return !isNaN(p) && !isNaN(v) && p > v;
}
function fill(sel, values){
  [...new Set(values)].sort().forEach(v=>{
    const o = document.createElement('option'); o.value = v; o.textContent = v; sel.append(o);
  });
}
fill(els.level, JOBS.map(j=>j.level));
fill(els.source, JOBS.map(j=>j.source));

function render(){
  const q = els.q.value.toLowerCase().trim();
  const mode = els.view.value;
  let rows = JOBS.map((j,i)=>({j,i})).filter(({j}) => {
    if(mode === 'hidden') { if(!hidden.has(j.url)) return false; }
    else if(hidden.has(j.url)) return false;
    if(mode === 'saved'    && !saved.has(j.url)) return false;
    if(mode === 'priority' && !j.priority) return false;
    if(mode === 'new'      && !isNew(j)) return false;
    if(q && !(j.title + ' ' + j.company + ' ' + j.location).toLowerCase().includes(q)) return false;
    if(els.level.value && j.level !== els.level.value) return false;
    if(els.remote.value !== '' && String(+j.remote) !== els.remote.value) return false;
    if(els.source.value && j.source !== els.source.value) return false;
    return true;
  });
  rows.sort((a,b) => (b.j.priority - a.j.priority)
    || ((Date.parse(b.j.posted)||0) - (Date.parse(a.j.posted)||0)));
  els.list.innerHTML = rows.length ? rows.map(({j,i}) => {
    const a = age(j.posted);
    const starred = saved.has(j.url);
    return `<div class="job ${j.priority?'priority':''}">
      <span class="when ${a.fresh?'fresh':''}">${a.fresh?'● ':''}${a.label}</span>
      <span class="main">
        <a href="${esc(j.url)}" target="_blank" rel="noopener">${esc(j.title)}</a>
        ${isNew(j)?'<span class="badge new">new</span>':''}
        <div class="sub">${esc(j.company)}${j.location? ' · ' + esc(j.location):''}
          ${j.salary? ' · <span class=salary>' + esc(j.salary) + '</span>':''}</div>
      </span>
      <span class="badges">
        ${j.priority? '<span class="badge pri">priority</span>':''}
        <span class="badge level">${esc(j.level)}</span>
        ${j.remote? '<span class="badge remote">remote</span>':''}
        <span class="badge">${esc(j.source)}</span>
        <button class="act star ${starred?'on':''}" data-i="${i}" data-act="star"
          aria-label="${starred?'Unsave':'Save'} job" title="${starred?'Unsave':'Save'}">${starred?'★':'☆'}</button>
        <button class="act" data-i="${i}" data-act="hide"
          aria-label="${mode==='hidden'?'Unhide':'Hide'} job" title="${mode==='hidden'?'Unhide':'Hide'}">${mode==='hidden'?'undo':'×'}</button>
      </span>
    </div>`;
  }).join('') : `<div class="empty">${mode==='hidden' ? 'Nothing hidden.' :
      mode==='saved' ? 'No saved roles yet — tap ☆ on a job to save it.' :
      mode==='new' ? (prevVisit ? 'Nothing new since your last visit.' : 'Welcome — everything is new on a first visit. Check back tomorrow.') :
      'No roles match. Clear a filter, or add companies to the seed list.'}</div>`;
  statSaved.textContent = saved.size;
}

els.list.addEventListener('click', e => {
  const b = e.target.closest('button.act');
  if(!b) return;
  const j = JOBS[+b.dataset.i];
  if(!j) return;
  const set = b.dataset.act === 'star' ? saved : hidden;
  set.has(j.url) ? set.delete(j.url) : set.add(j.url);
  store.set('pmb_saved',  [...saved]);
  store.set('pmb_hidden', [...hidden]);
  render();
});

/* --- countdown to next scheduled refresh (7:00 AM Pacific) --- */
function msToNextRefresh(){
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
    timeZone:'America/Los_Angeles', hour12:false,
    hour:'2-digit', minute:'2-digit', second:'2-digit'
  }).formatToParts(new Date()).map(p=>[p.type, p.value]));
  const secs = (Number(parts.hour) % 24)*3600 + Number(parts.minute)*60 + Number(parts.second);
  let diff = REFRESH_HOUR_PT*3600 - secs;
  if(diff <= 0) diff += 86400;
  return diff*1000;
}
function tickCountdown(){
  const ms = msToNextRefresh();
  const h = Math.floor(ms/36e5), m = Math.floor(ms%36e5/6e4), s = Math.floor(ms%6e4/1e3);
  statNext.textContent = h > 0 ? `${h}h ${m}m` : `${m}m ${s}s`;
}
tickCountdown();
setInterval(tickCountdown, 1000);

/* --- header stats --- */
statTotal.textContent = JOBS.filter(j=>!hidden.has(j.url)).length;
statFresh.textContent = JOBS.filter(j=>age(j.posted).fresh && !hidden.has(j.url)).length;
[els.q, els.view, els.level, els.remote, els.source].forEach(el => el.addEventListener('input', render));
render();
</script>
</body>
</html>"""
    return (template
            .replace("__COUNT__", str(len(jobs)))
            .replace("__GENERATED__", html_mod.escape(generated))
            .replace("__REFRESH_HOUR__", str(REFRESH_HOUR_PT))
            .replace("__PAYLOAD__", payload))


if __name__ == "__main__":
    print("PM Jobs Board — fetching public ATS boards...\n")
    run()
