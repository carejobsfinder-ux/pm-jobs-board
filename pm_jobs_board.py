#!/usr/bin/env python3
"""
PM Jobs Board — MVP aggregator
==============================
Pulls live Product Manager roles from the public, no-auth Greenhouse Job Board
API and Lever Postings API for a seed list of companies, normalizes them into
one schema, de-duplicates, and generates a self-contained job board:

    dist/index.html   <- open this in any browser (data embedded, works offline)
    dist/jobs.json    <- the raw normalized data

Run:
    python3 pm_jobs_board.py

No pip installs required (stdlib only). Re-run any time to refresh.
Add/remove companies in SEED_COMPANIES below. Wrong tokens are harmless:
the script reports which boards resolved and which 404'd.

Endpoints used (public GETs, no API key):
    Greenhouse: https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
    Lever:      https://api.lever.co/v0/postings/{site}?mode=json
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
# 1. SEED LIST — edit me.
#    Tokens are best-effort guesses; find the real one in a company's careers
#    page URL (boards.greenhouse.io/<token> or jobs.lever.co/<site>).
#    The run summary tells you which ones resolved.
# ---------------------------------------------------------------------------
SEED_COMPANIES = {
    "greenhouse": [
        # fintech (verified this batch: stripe, coinbase, robinhood)
        "affirm", "brex", "chime", "gusto", "marqeta", "mercury", "sofi",
        "carta", "checkr", "current", "stripe", "coinbase", "robinhood",
        # consumer / marketplace
        "airbnb", "instacart", "doordashusa", "pinterest", "lyft", "reddit",
        "duolingo", "discord", "roblox",
        # infra / dev / AI
        "figma", "databricks", "scaleai", "anthropic", "cloudflare",
        "dropbox", "airtable", "vercel",
        # unverified guesses — the run report will confirm
        "gitlab", "datadog", "mongodb", "asana", "intercom", "amplitude",
    ],
    "lever": [
        "netflix", "palantir", "kraken", "voleon",
        "mistral", "spotify", "plaid",
    ],
    "ashby": [
        # verified: socure. Rest are guesses — the run report will confirm.
        "socure", "ramp", "openai", "notion", "linear", "deel",
    ],
}

GH_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
LEVER_URL = "https://api.lever.co/v0/postings/{site}?mode=json"
ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/{name}?includeCompensation=true"
TIMEOUT = 15
HEADERS = {"User-Agent": "pm-jobs-board-mvp/0.1 (personal project)"}

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
# 3. Fetchers
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
        jobs.append({
            "title": title.strip(),
            "company": (j.get("company_name") or token).strip(),
            "location": ((j.get("location") or {}).get("name") or "").strip(),
            "remote": "remote" in ((j.get("location") or {}).get("name") or "").lower(),
            "salary": "",
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
# 4. Pipeline
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
# 5. Static site template (data embedded — works from file://, no server)
# ---------------------------------------------------------------------------
def render_html(jobs) -> str:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
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
    --fresh:#0e7a4d; --card:#ffffff; --accent:#144733;
  }
  @media (prefers-color-scheme: dark){
    :root{ --paper:#131715; --ink:#e8ece9; --dim:#93a09a; --line:#2a322e;
           --fresh:#4fc78f; --card:#1a201d; --accent:#bfe3d1; }
  }
  *{box-sizing:border-box; margin:0}
  body{background:var(--paper); color:var(--ink);
       font:15px/1.5 "Avenir Next","Segoe UI",system-ui,sans-serif;
       padding:0 16px 64px}
  .wrap{max-width:880px; margin:0 auto}
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
  input:focus,select:focus{outline:2px solid var(--fresh); outline-offset:1px}
  #q{flex:1; min-width:160px}
  .job{display:flex; gap:14px; align-items:baseline; padding:14px 4px;
       border-bottom:1px solid var(--line); flex-wrap:wrap}
  .job .when{width:66px; flex-shrink:0; color:var(--dim);
             font:12px "SF Mono",ui-monospace,Menlo,Consolas,monospace}
  .job .when.fresh{color:var(--fresh); font-weight:700}
  .job .main{flex:1; min-width:230px}
  .job a{color:var(--ink); text-decoration:none; font-weight:600}
  .job a:hover{text-decoration:underline; text-underline-offset:3px}
  .sub{color:var(--dim); font-size:13px; margin-top:2px}
  .badges{display:flex; gap:6px; flex-shrink:0}
  .badge{font:11px "SF Mono",ui-monospace,Menlo,Consolas,monospace;
         border:1px solid var(--line); border-radius:999px; padding:2px 9px;
         color:var(--dim); white-space:nowrap}
  .badge.level{color:var(--accent); border-color:var(--accent)}
  .badge.remote{color:var(--fresh); border-color:var(--fresh)}
  .salary{font:12px "SF Mono",ui-monospace,Menlo,Consolas,monospace;
          color:var(--ink)}
  .empty{padding:48px 0; text-align:center; color:var(--dim)}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>PM Market <span class="tick">▲</span></h1>
    <div class="meta">generated __GENERATED__ · greenhouse + lever public APIs · re-run pm_jobs_board.py to refresh</div>
    <div class="tape">
      <div class="up"><b id="statFresh">0</b>new in 24h</div>
      <div><b id="statTotal">0</b>open roles</div>
      <div><b id="statCos">0</b>companies</div>
      <div><b id="statRemote">0</b>remote</div>
    </div>
  </header>
  <div class="filters">
    <input id="q" type="search" placeholder="Search title, company, location" aria-label="Search">
    <select id="level" aria-label="Level"><option value="">All levels</option></select>
    <select id="remote" aria-label="Work mode">
      <option value="">Any mode</option><option value="1">Remote</option><option value="0">On-site / hybrid</option>
    </select>
    <select id="source" aria-label="Source"><option value="">All sources</option></select>
  </div>
  <div id="list"></div>
</div>
<script>
const JOBS = __PAYLOAD__;
const els = { q:q, level:level, remote:remote, source:source, list:list };
const esc = s => s.replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const now = Date.now();
function age(iso){
  if(!iso) return {label:'—', fresh:false};
  const h = (now - Date.parse(iso)) / 36e5;
  if(isNaN(h)) return {label:'—', fresh:false};
  if(h < 24) return {label: Math.max(1,Math.round(h)) + 'h', fresh:true};
  return {label: Math.round(h/24) + 'd', fresh:false};
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
  const rows = JOBS.filter(j =>
    (!q || (j.title + ' ' + j.company + ' ' + j.location).toLowerCase().includes(q)) &&
    (!els.level.value || j.level === els.level.value) &&
    (els.remote.value === '' || String(+j.remote) === els.remote.value) &&
    (!els.source.value || j.source === els.source.value)
  );
  els.list.innerHTML = rows.length ? rows.map(j => {
    const a = age(j.posted);
    return `<div class="job">
      <span class="when ${a.fresh?'fresh':''}">${a.fresh?'● ':''}${a.label}</span>
      <span class="main">
        <a href="${esc(j.url)}" target="_blank" rel="noopener">${esc(j.title)}</a>
        <div class="sub">${esc(j.company)}${j.location? ' · ' + esc(j.location):''}
          ${j.salary? ' · <span class=salary>' + esc(j.salary) + '</span>':''}</div>
      </span>
      <span class="badges">
        <span class="badge level">${esc(j.level)}</span>
        ${j.remote? '<span class="badge remote">remote</span>':''}
        <span class="badge">${esc(j.source)}</span>
      </span>
    </div>`;
  }).join('') : '<div class="empty">No roles match. Clear a filter, or add companies to the seed list and re-run.</div>';
}
statTotal.textContent = JOBS.length;
statCos.textContent = new Set(JOBS.map(j=>j.company)).size;
statRemote.textContent = JOBS.filter(j=>j.remote).length;
statFresh.textContent = JOBS.filter(j=>age(j.posted).fresh).length;
Object.values(els).forEach(el => el.addEventListener && el.addEventListener('input', render));
render();
</script>
</body>
</html>"""
    return (template
            .replace("__COUNT__", str(len(jobs)))
            .replace("__GENERATED__", html_mod.escape(generated))
            .replace("__PAYLOAD__", payload))


if __name__ == "__main__":
    print("PM Jobs Board — fetching public ATS boards...\n")
    run()
