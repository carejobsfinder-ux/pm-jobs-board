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
# Keywords to highlight in job titles and descriptions (appears as a badge).
KEYWORD_HIGHLIGHTER = ["risk", "fraud", "payments", "identity", "platform"]

# Company size buckets for filtering (company name → employee count range).
COMPANY_SIZES = {
    "stripe": "1000+", "coinbase": "1000+", "airbnb": "1000+", "instacart": "1000+",
    "pinterest": "1000+", "lyft": "1000+", "reddit": "1000+", "discord": "1000+",
    "figma": "1000+", "databricks": "1000+", "anthropic": "500-1000", "cloudflare": "1000+",
    "dropbox": "1000+", "mongodb": "1000+", "gitlab": "1000+", "datadog": "1000+",
    "asana": "1000+", "vercel": "100-500", "airtable": "100-500",
    "cursor": "50-200", "replit": "50-200", "supabase": "100-500", "ramp": "50-200",
    "openai": "100-500", "notion": "500-1000", "linear": "50-200", "sierra": "50-200",
    "harvey": "50-200", "vanta": "100-500", "clerk": "50-200", "sardine": "50-200",
    "socure": "100-500", "samsara": "1000+", "databricks": "500-1000", "anthropic": "100-500",
}

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
        # startup / risk-adjacent (verified working above; failed guesses removed)
        "samsara",
    ],
    "lever": [
        "netflix", "palantir", "kraken", "voleon",
        "mistral", "spotify", "plaid",
        # verified this session
        "dnb", "Flex",
    ],
    "ashby": [
        "socure", "ramp", "openai", "notion", "linear", "deel",
        # startup-heavy guesses (Ashby skews to newer high-growth startups);
        # posthog is cited in Ashby's own docs — the run report confirms the rest
        "posthog", "cursor", "replit", "supabase", "vanta", "clerk",
        "elevenlabs", "sierra", "harvey", "cognition",
        "browserbase", "sardine", "column",
    ],
    "workable": [
        # SMB-leaning ATS; verified example board to smoke-test the integration.
        # Replace/extend with companies you care about (subdomain from
        # apply.workable.com/<subdomain>).
        "epignosis",
    ],
    "recruitee": [
        # SMB/EU-leaning ATS; verified example board to smoke-test the
        # integration (subdomain from <subdomain>.recruitee.com).
        "adamsmithinternational1",
    ],
}

GH_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
LEVER_URL = "https://api.lever.co/v0/postings/{site}?mode=json"
ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/{name}?includeCompensation=true"
WORKABLE_URL = "https://www.workable.com/api/accounts/{sub}?details=true"
RECRUITEE_URL = "https://{sub}.recruitee.com/api/offers/"
TIMEOUT = 15
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

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


def tag_keywords(j: dict) -> list:
    """Find matches of KEYWORD_HIGHLIGHTER in title and description."""
    tags = []
    for kw in KEYWORD_HIGHLIGHTER:
        text = (j.get("title", "") + " " + j.get("description", "")).lower()
        if kw.lower() in text:
            tags.append(kw)
            break  # only tag once per keyword per job
    return tags


def has_days_open(j: dict) -> int:
    """Days between posted_at and now. Returns -1 if no posted date."""
    if not j.get("posted"):
        return -1
    try:
        posted_str = j["posted"].replace("Z", "+00:00")
        posted_dt = datetime.fromisoformat(posted_str)
        # Ensure both datetimes are timezone-aware
        if posted_dt.tzinfo is None:
            posted_dt = posted_dt.replace(tzinfo=timezone.utc)
        now_dt = datetime.now(timezone.utc)
        days = (now_dt - posted_dt).days
        return max(0, days)
    except (ValueError, AttributeError, TypeError):
        return -1


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
            "description": html_mod.unescape((j.get("content") or "")[:500]),  # first 500 chars
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
            "description": (p.get("text", "")[:500] if isinstance(p.get("text"), str) else ""),
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
            "description": (j.get("descriptionRaw") or "")[:500] if isinstance(j.get("descriptionRaw"), str) else "",
            "source": "ashby",
        })
    return jobs


def fetch_workable(sub: str):
    """Workable public careers API. Fields beyond the documented ones
    (title/url/location/department/employment_type) are mapped defensively."""
    data = _get_json(WORKABLE_URL.format(sub=sub))
    company = (data.get("name") or sub).strip()
    jobs = []
    for j in (data.get("jobs") or []):
        title = j.get("title", "") or ""
        if not is_pm_role(title):
            continue
        loc = j.get("location")
        if isinstance(loc, dict):
            loc = ", ".join(str(v) for v in (loc.get("city"), loc.get("country")) if v)
        loc = (loc or "").strip() if isinstance(loc, str) else ""
        jobs.append({
            "title": title.strip(),
            "company": company,
            "location": loc,
            "remote": bool(j.get("remote")) or "remote" in loc.lower(),
            "salary": "",
            "level": classify_level(title),
            "posted": j.get("published_on") or j.get("created_at") or "",
            "url": j.get("url", ""),
            "description": (j.get("description", "")[:500] if isinstance(j.get("description"), str) else ""),
            "source": "workable",
        })
    return jobs


def fetch_recruitee(sub: str):
    """Recruitee public offers API (documented fields: title, location,
    department, careers_url, remote)."""
    data = _get_json(RECRUITEE_URL.format(sub=sub))
    jobs = []
    for j in (data.get("offers") or []):
        title = j.get("title", "") or ""
        if not is_pm_role(title):
            continue
        loc = (j.get("location") or "").strip()
        jobs.append({
            "title": title.strip(),
            "company": (j.get("company_name") or sub).strip(),
            "location": loc,
            "remote": bool(j.get("remote")) or "remote" in loc.lower(),
            "salary": "",
            "level": classify_level(title),
            "posted": j.get("published_at") or j.get("created_at") or "",
            "url": j.get("careers_url", ""),
            "description": (j.get("description", "")[:500] if isinstance(j.get("description"), str) else ""),
            "source": "recruitee",
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
    plan += [("workable", w, fetch_workable) for w in SEED_COMPANIES.get("workable", [])]
    plan += [("recruitee", r, fetch_recruitee) for r in SEED_COMPANIES.get("recruitee", [])]

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

    # de-dupe on (company, title) only — catches near-dupes across ATS where
    # location might be "San Francisco" vs "SF"
    seen, deduped = set(), []
    for j in all_jobs:
        key = (j["company"].lower(), j["title"].lower())
        if key not in seen:
            seen.add(key)
            # add new fields
            j["days_open"] = has_days_open(j)
            j["keywords"] = tag_keywords(j)
            j["size"] = COMPANY_SIZES.get(j["company"].lower(), "Unknown")
            # truncate description to first 200 chars for tooltip
            desc = j.get("description") or ""
            if isinstance(desc, str):
                j["description_preview"] = (desc[:200] + "…") if len(desc) > 200 else desc
            else:
                j["description_preview"] = ""
            deduped.append(j)

    # sort by: keywords match first, then recency
    deduped.sort(key=lambda j: (len(j.get("keywords", [])) == 0, j["posted"] or ""), reverse=True)

    # track company open role counts for the trending widget
    company_counts = {}
    for j in deduped:
        co = j["company"]
        company_counts[co] = company_counts.get(co, 0) + 1
    
    # top 5 trending companies by open role count
    trending = sorted(company_counts.items(), key=lambda x: -x[1])[:5]

    out = Path(__file__).resolve().parent / "dist"
    out.mkdir(exist_ok=True)
    (out / "jobs.json").write_text(json.dumps(deduped, indent=2), encoding="utf-8")
    (out / "index.html").write_text(
        render_html(deduped, trending, company_counts), encoding="utf-8"
    )

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
def render_html(jobs, trending, company_counts) -> str:
    now_utc = datetime.now(timezone.utc)
    generated = now_utc.strftime("%Y-%m-%d %H:%M UTC")
    generated_iso = now_utc.isoformat()
    payload = json.dumps(jobs).replace("</", "<\\/")
    trending_payload = json.dumps(trending).replace("</", "<\\/")
    template = r"""<!DOCTYPE html>
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
  .badge.key{color:var(--star); border-color:var(--star); font-weight:600}
  .salary{font:12px "SF Mono",ui-monospace,Menlo,Consolas,monospace; color:var(--ink)}
  .trending{margin:12px 0; padding:14px; background:var(--card); border:1px solid var(--line);
            border-radius:8px; font-size:13px}
  .stat-card{display:flex; gap:16px; flex-direction:column}
  .stat-title{font-weight:700; color:var(--dim); font-size:11px; text-transform:uppercase; letter-spacing:0.05em}
  .stat-rows{display:grid; gap:6px}
  .stat-row{display:flex; justify-content:space-between; padding:4px 0;
            border-bottom:1px solid var(--line)}
  .stat-row:last-child{border:none}
  .stat-row .co{font-weight:600; flex:1}
  .stat-row .cnt{font-family:"SF Mono",ui-monospace,Menlo,Consolas,monospace; font-weight:700; color:var(--fresh)}
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
    <div class="meta">updated <span id="genTime" data-iso="__GENERATED_ISO__">__GENERATED__</span> · refreshes daily ~7:00 AM PT · greenhouse + lever + ashby public APIs</div>
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
    <select id="remote" aria-label="Workplace">
      <option value="">Any</option><option value="1">Remote</option><option value="0">On-site / hybrid</option>
    </select>
    <select id="source" aria-label="Source"><option value="">All sources</option></select>
    <select id="size" aria-label="Company size"><option value="">All sizes</option></select>
    <input id="salMin" type="number" placeholder="Min $" min="0" step="5000" aria-label="Minimum salary">
    <input id="salMax" type="number" placeholder="Max $" min="0" step="5000" aria-label="Maximum salary">
  </div>
  <div id="trending" class="trending"></div>
  <div id="list"></div>
</div>
<script>
const JOBS = __PAYLOAD__;
const REFRESH_HOUR_PT = __REFRESH_HOUR__;
const els = { q:q, view:view, level:level, remote:remote, source:source, size:size, salMin:salMin, salMax:salMax, list:list, trending:trending };
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
fill(els.size, JOBS.map(j=>j.size));

/* --- render trending companies widget --- */
const TRENDING = __TRENDING__;
if(TRENDING.length > 0){
  const html = '<div class="stat-card"><div class="stat-title">Trending</div><div class="stat-rows">' +
    TRENDING.map(([co, cnt]) => `<div class="stat-row"><span class="co">${esc(co)}</span><span class="cnt">${cnt}</span></div>`).join('') +
    '</div></div>';
  els.trending.innerHTML = html;
}

function render(){
  const q = els.q.value.toLowerCase().trim();
  const mode = els.view.value;
  const salMin = els.salMin.value ? parseInt(els.salMin.value) : 0;
  const salMax = els.salMax.value ? parseInt(els.salMax.value) : Infinity;
  
  let rows = JOBS.map((j,i)=>({j,i})).filter(({j}) => {
    if(mode === 'hidden') { if(!hidden.has(j.url)) return false; }
    else if(hidden.has(j.url)) return false;
    if(mode === 'saved'    && !saved.has(j.url)) return false;
    if(mode === 'priority' && (j.keywords||[]).length === 0) return false;
    if(mode === 'new'      && !isNew(j)) return false;
    if(q && !(j.title + ' ' + j.company + ' ' + j.location).toLowerCase().includes(q)) return false;
    if(els.level.value && j.level !== els.level.value) return false;
    if(els.remote.value !== '' && String(+j.remote) !== els.remote.value) return false;
    if(els.source.value && j.source !== els.source.value) return false;
    if(els.size.value && j.size !== els.size.value) return false;
    // salary filter: parse "$X–$Y" format
    if(j.salary && (salMin > 0 || salMax < Infinity)){
      const m = j.salary.match(/\$(\d+,?\d*)/g);
      if(m && m.length >= 1){
        const lo = parseInt(m[0].replace(/[\$,]/g,''));
        if(lo < salMin || lo > salMax) return false;
      } else return false;
    }
    return true;
  });
  rows.sort((a,b) => ((b.j.keywords||[]).length - (a.j.keywords||[]).length)
    || ((Date.parse(b.j.posted)||0) - (Date.parse(a.j.posted)||0)));
  els.list.innerHTML = rows.length ? rows.map(({j,i}) => {
    const a = age(j.posted);
    const starred = saved.has(j.url);
    const daysOpen = j.days_open >= 0 ? j.days_open : -1;
    const isStale = daysOpen >= 90;
    const kwBadges = (j.keywords||[]).map(k => `<span class="badge key">${esc(k)}</span>`).join('');
    return `<div class="job ${(j.keywords||[]).length > 0?'has-keywords':''}">
      <span class="when ${a.fresh?'fresh':''}" title="${daysOpen >= 0 ? daysOpen + ' days open' : 'date unknown'}">${a.fresh?'● ':''}${a.label}${isStale?' ⚠':''}}</span>
      <span class="main">
        <a href="${esc(j.url)}" target="_blank" rel="noopener" title="${esc(j.description_preview)}">${esc(j.title)}</a>
        ${isNew(j)?'<span class="badge new">new</span>':''}
        <div class="sub">${esc(j.company)}${j.location? ' · ' + esc(j.location):''}${j.size && j.size !== 'Unknown' ? ' · ' + esc(j.size) + ' employees' : ''}
          ${j.salary? ' · <span class=salary>' + esc(j.salary) + '</span>':''}</div>
      </span>
      <span class="badges">
        ${kwBadges}
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

/* --- localized "updated" timestamp --- */
(function(){
  const el = document.getElementById('genTime');
  const d = new Date(el.dataset.iso);
  if(!isNaN(d)){
    const mins = Math.max(0, Math.round((Date.now() - d.getTime())/6e4));
    const agoTxt = mins < 60 ? mins + 'm ago' : Math.round(mins/60) + 'h ago';
    el.textContent = d.toLocaleString(undefined,
      {month:'short', day:'numeric', hour:'numeric', minute:'2-digit'}) + ' (' + agoTxt + ')';
  }
})();

/* --- header stats --- */
statTotal.textContent = JOBS.filter(j=>!hidden.has(j.url)).length;
statFresh.textContent = JOBS.filter(j=>age(j.posted).fresh && !hidden.has(j.url)).length;
[els.q, els.view, els.level, els.remote, els.source, els.size, els.salMin, els.salMax].forEach(el => el.addEventListener('input', render));
render();
</script>
</body>
</html>"""
    return (template
            .replace("__COUNT__", str(len(jobs)))
            .replace("__GENERATED__", html_mod.escape(generated))
            .replace("__GENERATED_ISO__", html_mod.escape(generated_iso))
            .replace("__REFRESH_HOUR__", str(REFRESH_HOUR_PT))
            .replace("__TRENDING__", trending_payload)
            .replace("__PAYLOAD__", payload))


if __name__ == "__main__":
    print("PM Jobs Board — fetching public ATS boards...\n")
    run()
