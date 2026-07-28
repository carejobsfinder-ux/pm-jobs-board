#!/usr/bin/env python3
"""
PM Jobs Board — Combined (uses render_board.py and render_landing.py)
Generates index.html (landing) + board.html (job board) in one script.
"""

import json
import html as html_mod
import sys
import time
import urllib.request
import urllib.error
import re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

# Import the two render functions
from render_board import render_html as render_board_html
from render_landing import render_landing_html

# ============================================================================
# CONFIG
# ============================================================================

REFRESH_HOUR_PT = 7
SEED_COMPANIES = {
    "greenhouse": ["coinbase","airbnb","pinterest","amplitude","asana","consensys","mercury","mixpanel","blockchain","alloy","cloudflare","elastic","brex","figma","twilio","mongodb","stripe","robinhood","gusto","chime","dropbox","affirm","scaleai","intercom","databricks","betterment","instacart","anthropic","reddit","lyft","airtable","vercel"],
    "lever": ["wealthfront","ro","alloy"],
}

COMPANY_INDUSTRIES = {
    "Fintech": ["stripe","ramp","mercury","chime","betterment","wealthfront","affirm","ro","coinbase"],
    "AI/ML": ["anthropic","openai","cohere","cursor","midjourney","sift","ultralytics"],
    "DevTools": ["linear","replit","vercel","modal","vanta","openhands","localstack"],
    "Enterprise SaaS": ["asana","airtable","notion","figma","intercom","databricks","cloudflare"],
    "Consumer": ["reddit","lyft","instacart","pinterest"],
    "Risk": ["alloy","socure","sardine"],
}

ROLE_FUNCTIONS = {
    "Product Manager": {
        "include": [r"product (manager|management|lead|owner)", r"head of product", r"\bapm\b", r"associate product"],
        "exclude": [r"project manager", r"product design", r"product support", r"product analyst", r"product marketing"],
    },
    "People Partner": {
        "include": [r"people (partner|operations|manager|ops)", r"recruiting", r"talent (acquisition|manager)",
                    r"recruiter", r"human resources", r"HR (manager|specialist|operations)", r"employee relations",
                    r"organizational development"],
        "exclude": [r"people success manager"],
    },
}

SIZE_ORDER = ["50-200","100-500","500-1000","1000+"]

# ============================================================================
# FETCH FUNCTIONS
# ============================================================================

def fetch_greenhouse(token):
    url = "https://boards-api.greenhouse.io/v1/boards/{}/jobs?content=true".format(token)
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=8) as resp:
        data = json.loads(resp.read())
    return [{"url": "https://boards.greenhouse.io/embed/job_board/jobs/{}".format(j['id']),
             "title": j.get("title",""),
             "company": token,
             "posted": j.get("published_at",""),
             "location": j.get("location",{}).get("name",""),
             "body": j.get("content","")} for j in data.get("jobs",[])]

def fetch_lever(site):
    url = "https://api.lever.co/v0/postings/{}?mode=json".format(site)
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=8) as resp:
        data = json.loads(resp.read())
    # data can be a list or dict with postings key
    postings = data if isinstance(data, list) else data.get("postings", [])
    return [{"url": j.get("hostedUrl",""),
             "title": j.get("text",""),
             "company": site,
             "posted": j.get("createdAt",""),
             "location": ", ".join([j.get("locations",[])[0].get("name","")] if j.get("locations") else []),
             "body": j.get("description","")} for j in postings]

def fetch_ashby(name):
    url = "https://api.ashbyhq.com/posting-api/job-board/{}?includeCompensation=true".format(name)
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=8) as resp:
        data = json.loads(resp.read())
    return [{"url": j.get("jobUrl",""),
             "title": j.get("title",""),
             "company": name,
             "posted": j.get("createdAt",""),
             "location": j.get("location",{}).get("name",""),
             "body": j.get("descriptionHtml","")} for j in data.get("jobs",[])]

def fetch_workable(sub):
    url = "https://www.workable.com/api/accounts/{}?details=true".format(sub)
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=8) as resp:
        data = json.loads(resp.read())
    return [{"url": j.get("url",""),
             "title": j.get("title",""),
             "company": sub,
             "posted": j.get("published_at",""),
             "location": j.get("location",""),
             "body": j.get("description","")} for j in data.get("jobs",[])]

def fetch_recruitee(sub):
    url = "https://{}.recruitee.com/api/offers/".format(sub)
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=8) as resp:
        data = json.loads(resp.read())
    return [{"url": o.get("url",""),
             "title": o.get("title",""),
             "company": sub,
             "posted": o.get("created_at",""),
             "location": o.get("location",""),
             "body": o.get("description","")} for o in data.get("offers",[])]

# ============================================================================
# PROCESSING
# ============================================================================

def is_target_role(title, body, role_name="Product Manager"):
    if role_name not in ROLE_FUNCTIONS:
        return False
    config = ROLE_FUNCTIONS[role_name]
    text = "{} {}".format(title, body).lower()
    
    for pattern in config.get("exclude", []):
        if re.search(pattern, text, re.I):
            return False
    
    for pattern in config.get("include", []):
        if re.search(pattern, text, re.I):
            return True
    return False

def classify_level(title):
    patterns = [
        (r"\bintern\b", "Intern"),
        (r"associate|\bapm\b", "Associate"),
        (r"\bprincipal\b", "Principal"),
        (r"\bstaff\b", "Staff"),
        (r"\bgroup\b|\bgpm\b", "Group"),
        (r"director", "Director"),
        (r"\bvp\b|vice president|head of|chief", "VP/Head"),
        (r"manager", "Manager"),
        (r"senior|\bsr\.?\b|\blead\b", "Senior"),
    ]
    for pattern, level in patterns:
        if re.search(pattern, title, re.I):
            return level
    return "IC"

def extract_salary(body):
    match = re.search(r'\$(\d+[,\d]*)\s*(?:K|,000)?\s*(?:[-–]\s*\$?(\d+[,\d]*)\s*(?:K|,000)?)?', body)
    if match:
        try:
            min_sal = int(match.group(1).replace(",", ""))
            if min_sal < 1000:
                min_sal *= 1000
            max_sal = None
            if match.group(2):
                max_sal = int(match.group(2).replace(",", ""))
                if max_sal < 1000:
                    max_sal *= 1000
            return {"min": min_sal, "max": max_sal}
        except:
            pass
    return {}

def classify_industry(company_name):
    company_lower = company_name.lower()
    for industry, companies in COMPANY_INDUSTRIES.items():
        if any(c.lower() in company_lower for c in companies):
            return industry
    return "Other"

def classify_size(company_name):
    return "500-1000"

def has_days_open(posted):
    try:
        posted_dt = datetime.fromisoformat(posted.replace('Z', '+00:00'))
        now_dt = datetime.now(timezone.utc)
        return (now_dt - posted_dt).days
    except:
        return 0

def run():
    all_jobs, ok, failed = [], [], []
    plan = [("greenhouse", t, fetch_greenhouse) for t in SEED_COMPANIES["greenhouse"]]
    plan += [("lever", s, fetch_lever) for s in SEED_COMPANIES["lever"]]

    def fetch_with_retry(source, token, fn):
        jobs, err = None, None
        for attempt in (1, 2):
            try:
                jobs = fn(token)
                break
            except urllib.error.HTTPError as e:
                err = "HTTP {}".format(e.code)
                if e.code == 404:
                    break
                time.sleep(0.5)
            except Exception as e:
                err = str(e)[:60]
                time.sleep(0.5)
        return (jobs, source, token, err)

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(fetch_with_retry, source, token, fn) for source, token, fn in plan]
        for future in as_completed(futures):
            jobs, source, token, err = future.result()
            if jobs is not None:
                all_jobs.extend(jobs)
                ok.append((source, token, len(jobs)))
                print("  ok    {:<10} {:<14} {} roles".format(source, token, len(jobs)))
            else:
                failed.append((source, token, err))
                print("  fail  {:<10} {:<14} {}".format(source, token, err))

    # Process & dedupe
    processed = []
    for j in all_jobs:
        title = html_mod.escape(j.get("title", "")).strip()
        company = html_mod.escape(j.get("company", "")).strip()
        location = html_mod.escape(j.get("location", "")).strip()
        body = j.get("body", "")
        
        # Determine role function
        if is_target_role(title, body, "Product Manager"):
            function = "Product Manager"
        elif is_target_role(title, body, "People Partner"):
            function = "People Partner"
        else:
            continue
        
        level = classify_level(title)
        salary = extract_salary(body)
        industry = classify_industry(company)
        size = classify_size(company)
        remote = "remote" in location.lower() or "hybrid" in location.lower()
        days_open = has_days_open(j.get("posted", ""))
        
        processed.append({
            "url": j.get("url", ""),
            "title": title,
            "company": company,
            "location": location,
            "posted": j.get("posted", ""),
            "function": function,
            "level": level,
            "salary": salary,
            "industry": industry,
            "size": size,
            "remote": remote,
            "body": body,
            "days_open": days_open,
            "keywords": [],
        })

    # Dedupe
    seen = set()
    deduped = []
    for j in processed:
        key = (j["company"], j["title"])
        if key not in seen:
            seen.add(key)
            deduped.append(j)

    # Format salary for rendering
    for j in deduped:
        if j.get("salary"):
            min_sal = j["salary"].get("min", 0)
            max_sal = j["salary"].get("max")
            if min_sal and max_sal:
                j["salary"] = "${:,.0f}K–${:,.0f}K".format(min_sal / 1000, max_sal / 1000)
            elif min_sal:
                j["salary"] = "${:,.0f}K+".format(min_sal / 1000)
            else:
                j["salary"] = ""
        else:
            j["salary"] = ""
    company_counts = {}
    for j in deduped:
        c = j["company"]
        company_counts[c] = company_counts.get(c, 0) + 1

    trending = sorted(company_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    # Write output
    out = Path("dist")
    out.mkdir(exist_ok=True)
    
    (out / "jobs.json").write_text(json.dumps(deduped, indent=2), encoding="utf-8")
    (out / "index.html").write_text(
        render_landing_html(deduped, trending, company_counts, board_url="board.html"), encoding="utf-8"
    )
    (out / "board.html").write_text(
        render_board_html(deduped, trending, company_counts, landing_url="index.html"), encoding="utf-8"
    )

    print("\n----------------------------------------")
    print("boards resolved : {} / {}".format(len(ok), len(plan)))
    print("jobs collected  : {}  ->  {} after de-dupe".format(len(all_jobs), len(deduped)))
    if failed:
        print("failed boards   : " + ", ".join("{} ({})".format(t, e) for _, t, e in failed))
    print("\nopen: {}".format(out.resolve() / 'index.html'))

if __name__ == "__main__":
    print("\nPM Jobs Board — fetching public ATS boards...\n")
    run()
