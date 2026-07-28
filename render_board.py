#!/usr/bin/env python3
"""
Board renderer, restyled to match the landing page (direction 1B — "Terminal")
=============================================================================

A drop-in replacement for render_html() in pm_jobs_board.py. Same signature,
same __TOKEN__ replacement, same markup hooks — every id and class the page's
JavaScript touches is unchanged, so the filtering, starring, hiding, "new since
last visit", countdown and stats logic is copied over verbatim and keeps
working.

Wiring — two options.

  A) Import it (recommended; leaves pm_jobs_board.py's own render_html in place
     as a fallback). Near the other imports:

         from render_board import render_html   # restyled board

     Put that AFTER the def of the old render_html so the import wins, or just
     delete the old function.

  B) Paste over it: copy render_html() and BOARD_TEMPLATE from this file into
     pm_jobs_board.py, replacing the old render_html() and its template.

Either way verify_build() still passes: the template contains id="jobFunction",
id="salMin" and selectedFunc, and render_html([], [], {}) renders.

What changed, and only this:
  * Archivo (800 headings) replaces the system font stack.
  * border-radius: 0 everywhere — the landing page rounds nothing.
  * 2px ink rules on section seams (nav, filter bar, header); 1px hairlines
    stay as row rules inside lists and tables.
  * The ink #111827 bar and emerald #10b981 / #059669 accent from the landing.
  * Mono numerals for the stat tape, ages, salaries and badges.
  * A sticky glass nav with a link back to landing.html.
  * Dark mode dropped — the landing page has one ground, and the two pages sat
    on different ones. Re-add a prefers-color-scheme block if you want it back.
"""

import html as html_mod
import json
from datetime import datetime, timezone


def render_html(jobs, trending, company_counts, landing_url="landing.html",
                refresh_hour_pt=7) -> str:
    now_utc = datetime.now(timezone.utc)
    generated = now_utc.strftime("%Y-%m-%d %H:%M UTC")
    generated_iso = now_utc.isoformat()
    payload = json.dumps(jobs).replace("</", "<\\/")
    trending_payload = json.dumps(trending).replace("</", "<\\/")
    return (BOARD_TEMPLATE
            .replace("__COUNT__", str(len(jobs)))
            .replace("__LANDING_URL__", html_mod.escape(landing_url, quote=True))
            .replace("__GENERATED__", html_mod.escape(generated))
            .replace("__GENERATED_ISO__", html_mod.escape(generated_iso))
            .replace("__REFRESH_HOUR__", str(refresh_hour_pt))
            .replace("__TRENDING__", trending_payload)
            .replace("__PAYLOAD__", payload))


BOARD_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PM Jobs Board — __COUNT__ open roles</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  :root{
    --paper:#f9fafb; --white:#ffffff; --ink:#111827;
    --ink-70:#4b5563; --muted:#6b7280; --hair:#e5e7eb;
    --accent:#10b981; --accent-600:#059669; --accent-700:#047857;
    --pin:#b45309;
    --font:"Archivo",system-ui,-apple-system,sans-serif;
    --mono:ui-monospace,"SF Mono",Menlo,monospace;
    --edge:clamp(16px,4vw,52px);
  }
  *{box-sizing:border-box;margin:0}
  html{scroll-behavior:smooth}
  @media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
  body{background:var(--paper);color:var(--ink);font:400 15px/1.55 var(--font);padding:0 0 64px;text-wrap:pretty;-webkit-font-smoothing:antialiased}
  .wrap{max-width:1200px;margin:0 auto;padding:0 var(--edge)}
  a{color:inherit;text-decoration:none;transition:color .18s ease}
  a:hover{color:var(--accent-700)}
  :focus-visible{outline:2px solid var(--accent-600);outline-offset:2px}
  ::selection{background:color-mix(in srgb,var(--accent) 28%,transparent)}
  .mark{width:12px;height:12px;background:var(--accent);display:block;flex:none}

  /* nav — the landing page's sticky glass bar */
  nav.top{position:sticky;top:0;z-index:30;display:flex;align-items:center;
    padding:14px var(--edge);background:color-mix(in srgb,var(--paper) 78%,transparent);
    backdrop-filter:blur(16px) saturate(140%);-webkit-backdrop-filter:blur(16px) saturate(140%);
    border-bottom:2px solid var(--ink)}
  nav.top .inner{max-width:1200px;margin:0 auto;width:100%;display:flex;align-items:center;gap:24px}
  nav.top .brand{display:flex;align-items:center;gap:10px;font:800 18px/1 var(--font);letter-spacing:-0.01em;margin-right:auto}
  nav.top a.link{font:600 14px/1 var(--font);white-space:nowrap}

  /* masthead */
  header{padding:40px 0 32px;border-bottom:2px solid var(--ink)}
  h1{font:800 clamp(28px,4vw,40px)/1.06 var(--font);letter-spacing:-0.025em;margin-left:-0.045em}
  h1 .tick{color:var(--accent-600)}
  .meta{color:var(--muted);font:400 12px/1.5 var(--mono);margin-top:12px}
  .tape{display:flex;gap:36px;margin-top:24px;flex-wrap:wrap}
  .tape>div{display:flex;flex-direction:column;gap:6px;font:600 11px/1 var(--font);letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
  .tape b{font:700 26px/1 var(--mono);color:var(--ink)}
  .tape .up b{color:var(--accent-600)}

  /* filter bar */
  .filters{position:sticky;top:58px;background:color-mix(in srgb,var(--paper) 92%,transparent);
    backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);
    z-index:20;display:flex;gap:8px;flex-wrap:wrap;align-items:center;
    padding:14px var(--edge);border-bottom:2px solid var(--ink);
    transition:transform .28s ease-out,opacity .28s ease-out}
  .filters>*{flex:none}
  .filters.compact{transform:translateY(-100%);opacity:0;pointer-events:none}
  input,select{font:500 13px/1.2 var(--font);color:var(--ink);background:var(--white);
    border:1px solid var(--hair);border-radius:0;padding:9px 10px;transition:border-color .18s ease,box-shadow .18s ease}
  select{appearance:none;padding-right:26px;
    background-image:linear-gradient(45deg,transparent 50%,var(--ink) 50%),linear-gradient(135deg,var(--ink) 50%,transparent 50%);
    background-position:calc(100% - 14px) 50%,calc(100% - 9px) 50%;
    background-size:5px 5px,5px 5px;background-repeat:no-repeat}
  input:hover,select:hover{border-color:var(--ink)}
  input:focus,select:focus{outline:none;border-color:var(--accent-600);box-shadow:0 0 0 2px color-mix(in srgb,var(--accent) 28%,transparent)}
  input[type=number]{width:104px;font-family:var(--mono)}
  #q{flex:1 1 200px;min-width:140px}

  /* pills */
  .industry-pills{display:flex;gap:6px;flex-wrap:wrap}
  .pill{font:700 12px/1 var(--font);padding:8px 12px;border-radius:0;border:1px solid var(--hair);
    background:var(--white);color:var(--ink-70);cursor:pointer;transition:all .18s ease}
  .pill:hover{border-color:var(--ink);color:var(--ink)}
  .pill.selected{background:var(--accent);border-color:var(--accent);color:var(--white)}

  /* trending card */
  .trending{margin:32px 0 8px;padding:0;background:var(--white);border:2px solid var(--ink);border-radius:0}
  .trending:empty{display:none}
  .stat-card{display:flex;flex-direction:column}
  .stat-title{font:700 10px/1 var(--font);letter-spacing:.1em;text-transform:uppercase;color:var(--paper);
    background:var(--ink);padding:11px 16px}
  .stat-rows{display:grid;padding:6px 16px 10px}
  .stat-row{display:flex;justify-content:space-between;gap:16px;padding:9px 0;border-bottom:1px solid var(--hair);font-size:13px}
  .stat-row:last-child{border-bottom:0}
  .stat-row .co{font-weight:700;flex:1}
  .stat-row .cnt{font:700 13px/1.4 var(--mono);color:var(--accent-600)}

  /* job rows */
  #list{margin-top:8px}
  .job{display:flex;gap:20px;align-items:flex-start;padding:22px 0;border-bottom:1px solid var(--hair);
    flex-wrap:wrap;transition:background .18s ease}
  .job:hover{background:color-mix(in srgb,var(--accent) 5%,transparent)}
  .job.has-keywords{border-left:3px solid var(--accent);padding-left:16px;margin-left:-19px}
  .job .when{width:62px;flex:none;color:var(--muted);font:700 11px/1.6 var(--mono);letter-spacing:.02em}
  .job .when.fresh{color:var(--accent-600)}
  .job .main{flex:1;min-width:220px}
  .job a{color:var(--ink);font:800 17px/1.25 var(--font);letter-spacing:-0.015em}
  .job a:hover{color:var(--accent-700)}
  .sub{color:var(--muted);font-size:13px;margin-top:8px;display:flex;gap:8px;flex-wrap:wrap}
  .salary{font:700 12px/1.5 var(--mono);color:var(--ink)}
  .badges{display:flex;gap:6px;flex:none;align-items:center;flex-wrap:wrap}
  .badge{font:700 10px/1 var(--mono);letter-spacing:.06em;text-transform:uppercase;
    border:1px solid var(--hair);border-radius:0;padding:6px 8px;color:var(--muted);white-space:nowrap}
  .badge.level{color:var(--ink);border-color:var(--ink)}
  .badge.remote{color:var(--accent-700);border-color:var(--accent)}
  .badge.new{color:var(--white);background:var(--accent-600);border-color:var(--accent-600)}
  .badge.key{color:var(--pin);border-color:var(--pin)}
  button.act{background:var(--white);border:1px solid var(--hair);border-radius:0;color:var(--muted);
    cursor:pointer;font:700 13px/1 var(--mono);padding:7px 9px;transition:all .18s ease}
  button.act:hover{border-color:var(--ink);color:var(--ink)}
  button.act.star.on{color:var(--pin);border-color:var(--pin)}
  .empty{padding:56px 0;color:var(--muted);font-size:14px;border-bottom:1px solid var(--hair)}

  footer.board-foot{border-top:2px solid var(--ink);margin-top:40px;padding-top:20px;
    display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;font:400 12px/1.6 var(--mono);color:var(--muted)}

  @media (max-width:720px){
    nav.top a.link{display:none}
    .filters{top:56px}
    input[type=number]{width:calc(50% - 4px)}
    .tape{gap:24px}
    .job.has-keywords{margin-left:0;padding-left:13px}
  }
</style>
</head>
<body>
<nav class="top">
  <div class="inner">
    <span class="brand"><span class="mark"></span>PM Jobs Board</span>
    <a class="link" href="__LANDING_URL__">How it works</a>
    <a class="link" href="jobs.json">jobs.json</a>
  </div>
</nav>
<div class="wrap">
  <header>
    <h1>The board <span class="tick">▲</span></h1>
    <div class="meta">updated <span id="genTime" data-iso="__GENERATED_ISO__">__GENERATED__</span> · refreshes daily ~__REFRESH_HOUR__:00 AM PT · greenhouse + lever + ashby + workable + recruitee</div>
    <div class="tape">
      <div class="up"><b id="statFresh">0</b><span>new in 24h</span></div>
      <div><b id="statTotal">0</b><span>open roles</span></div>
      <div><b id="statSaved">0</b><span>saved</span></div>
      <div><b id="statNext">—</b><span>next refresh</span></div>
    </div>
  </header>
</div>
<div class="filters">
  <select id="jobFunction" aria-label="Role function"><option value="">All roles</option></select>
  <input id="q" type="search" placeholder="Search title, company, location" aria-label="Search">
  <select id="view" aria-label="View">
    <option value="all">All roles</option>
    <option value="priority">Priority</option>
    <option value="saved">Saved ★</option>
    <option value="new">New since last visit</option>
    <option value="hidden">Hidden</option>
  </select>
  <select id="level" aria-label="Level"><option value="">All levels</option></select>
  <select id="size" aria-label="Company size"><option value="">All sizes</option></select>
  <input id="salMin" type="number" placeholder="Min $" min="0" step="5000" aria-label="Minimum salary">
  <input id="salMax" type="number" placeholder="Max $" min="0" step="5000" aria-label="Maximum salary">
  <select id="age" aria-label="Job age"><option value="">Any age</option><option value="14">Posted in last 14d</option><option value="30">Posted in last 30d</option><option value="60">Posted in last 60d</option></select>
  <div id="industryPills" class="industry-pills" aria-label="Industry filter"></div>
  <div id="workplacePills" class="industry-pills" aria-label="Workplace filter"></div>
</div>
<div class="wrap">
  <div id="trending" class="trending"></div>
  <div id="list"></div>
  <footer class="board-foot">
    <span>© PM Jobs Board · built from public ATS APIs</span>
    <span>static site · no tracking · no account</span>
  </footer>
</div>
<script>
const JOBS = __PAYLOAD__;
const REFRESH_HOUR_PT = __REFRESH_HOUR__;
const SIZE_ORDER = ["50-200", "100-500", "500-1000", "1000+"];
const els = {
  q: document.getElementById('q'),
  view: document.getElementById('view'),
  jobFunction: document.getElementById('jobFunction'),
  level: document.getElementById('level'),
  remote: document.getElementById('remote'),
  size: document.getElementById('size'),
  salMin: document.getElementById('salMin'),
  salMax: document.getElementById('salMax'),
  age: document.getElementById('age'),
  list: document.getElementById('list'),
  trending: document.getElementById('trending'),
  industryPills: document.getElementById('industryPills'),
  workplacePills: document.getElementById('workplacePills')
};
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
const selectedIndustries = new Set(store.get('pmb_selectedIndustries', []));
const selectedWorkplaces = new Set(store.get('pmb_selectedWorkplaces', []));
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
function fill(sel, values, sortOrder){
  const sorted = [...new Set(values)].sort((a,b) => {
    if(sortOrder) {
      const aIdx = sortOrder.indexOf(a);
      const bIdx = sortOrder.indexOf(b);
      if(aIdx >= 0 && bIdx >= 0) return aIdx - bIdx;
    }
    return a.localeCompare(b);
  });
  sorted.forEach(v=>{
    const o = document.createElement('option'); o.value = v; o.textContent = v; sel.append(o);
  });
}
/* --- populate function dropdown from all unique functions in jobs --- */
const allFunctions = new Set();
JOBS.forEach(j => (j.functions||[]).forEach(f => allFunctions.add(f)));
[...allFunctions].sort().forEach(f => {
  const o = document.createElement('option');
  const count = JOBS.filter(j => (j.functions||[]).includes(f)).length;
  o.value = f; o.textContent = `${f} (${count})`;
  jobFunction.append(o);
});

/* --- dynamic dropdown updates when function changes --- */
function updateDropdownsForFunction() {
  if (!els.jobFunction || !els.level || !els.size) return;

  const selectedFunc = els.jobFunction.value;
  const jobsInFunc = selectedFunc ? JOBS.filter(j => (j.functions||[]).includes(selectedFunc)) : JOBS;

  els.level.innerHTML = '<option value="">All levels</option>';
  fill(els.level, jobsInFunc.map(j => j.level));

  els.size.innerHTML = '<option value="">All sizes</option>';
  fill(els.size, jobsInFunc.map(j => j.size), SIZE_ORDER);

  if(els.q) els.q.value = '';
  if(els.salMin) els.salMin.value = '';
  if(els.salMax) els.salMax.value = '';

  store.set('pmb_selectedFunction', selectedFunc);

  render();
}

if(els.jobFunction) els.jobFunction.addEventListener('change', updateDropdownsForFunction);

/* --- render industry pills --- */
const industries = ["Fintech", "AI/ML", "DevTools", "Enterprise SaaS", "Consumer", "Risk"];
if(els.industryPills) {
  els.industryPills.innerHTML = industries.map(ind =>
    `<button class="pill ${selectedIndustries.has(ind) ? 'selected' : ''}" data-industry="${ind}">${ind}</button>`
  ).join('');

  els.industryPills.querySelectorAll('.pill').forEach(pill => {
    pill.addEventListener('click', (e) => {
      const ind = e.target.dataset.industry;
      if(selectedIndustries.has(ind)) {
        selectedIndustries.delete(ind);
        e.target.classList.remove('selected');
      } else {
        selectedIndustries.add(ind);
        e.target.classList.add('selected');
      }
      store.set('pmb_selectedIndustries', [...selectedIndustries]);
      render();
    });
  });
}

/* --- render workplace pills --- */
const workplaces = ["Remote", "Hybrid", "On-site"];
if(els.workplacePills) {
  els.workplacePills.innerHTML = workplaces.map(wp =>
    `<button class="pill ${selectedWorkplaces.has(wp) ? 'selected' : ''}" data-workplace="${wp}">${wp}</button>`
  ).join('');

  els.workplacePills.querySelectorAll('.pill').forEach(pill => {
    pill.addEventListener('click', (e) => {
      const wp = e.target.dataset.workplace;
      if(selectedWorkplaces.has(wp)) {
        selectedWorkplaces.delete(wp);
        e.target.classList.remove('selected');
      } else {
        selectedWorkplaces.add(wp);
        e.target.classList.add('selected');
      }
      store.set('pmb_selectedWorkplaces', [...selectedWorkplaces]);
      render();
    });
  });
}

/* --- render trending companies widget --- */
const TRENDING = __TRENDING__;
if(TRENDING.length > 0){
  const funcLabel = els.jobFunction.value ? ` in ${els.jobFunction.value}` : '';
  const html = '<div class="stat-card"><div class="stat-title" title="Companies with most open roles' + funcLabel + '">Trending hirers</div><div class="stat-rows">' +
    TRENDING.map(([co, cnt]) => `<div class="stat-row"><span class="co">${esc(co)}</span><span class="cnt">${cnt}</span></div>`).join('') +
    '</div></div>';
  els.trending.innerHTML = html;
}

function render(){
  const q = els.q.value.toLowerCase().trim();
  const mode = els.view.value;
  const selectedFunc = els.jobFunction.value;
  const salMin = els.salMin.value ? parseInt(els.salMin.value) : 0;
  const salMax = els.salMax.value ? parseInt(els.salMax.value) : Infinity;
  const maxAge = els.age.value ? parseInt(els.age.value) : Infinity;  // days

  let rows = JOBS.map((j,i)=>({j,i})).filter(({j}) => {
    if(mode === 'hidden') { if(!hidden.has(j.url)) return false; }
    else if(hidden.has(j.url)) return false;
    if(mode === 'saved'    && !saved.has(j.url)) return false;
    if(mode === 'priority' && (j.keywords||[]).length === 0) return false;
    if(mode === 'new'      && !isNew(j)) return false;
    if(selectedFunc && !(j.functions||[]).includes(selectedFunc)) return false;
    if(q && !(j.title + ' ' + j.company + ' ' + j.location).toLowerCase().includes(q)) return false;
    if(els.level.value && j.level !== els.level.value) return false;
    if(els.size.value && j.size !== els.size.value) return false;
    if(selectedIndustries.size > 0 && !selectedIndustries.has(j.industry || "Other")) return false;
    if(selectedWorkplaces.size > 0) {
      let jobWorkplace = "On-site";
      if(j.remote) {
        jobWorkplace = (j.location && j.location.toLowerCase().includes("hybrid")) ? "Hybrid" : "Remote";
      }
      if(!selectedWorkplaces.has(jobWorkplace)) return false;
    }
    if(maxAge < Infinity){
      const days = j.days_open || 0;
      if(days < 0 || days > maxAge) return false;
    }
    if(j.salary && (salMin > 0 || salMax < Infinity)){
      const m = j.salary.match(/\$(\d+,?\d*)/g);
      if(m && m.length >= 1){
        const lo = parseInt(m[0].replace(/[\$,]/g,''));
        if(lo < salMin || lo > salMax) return false;
      } else return false;
    }
    return true;
  });
  rows.sort((a,b) => {
    const aDate = a.j.posted ? Date.parse(a.j.posted) : 0;
    const bDate = b.j.posted ? Date.parse(b.j.posted) : 0;
    if(bDate !== aDate) return bDate - aDate;
    return ((b.j.keywords||[]).length - (a.j.keywords||[]).length);
  });
  els.list.innerHTML = rows.length ? rows.map(({j,i}) => {
    const a = age(j.posted);
    const starred = saved.has(j.url);
    const daysOpen = j.days_open >= 0 ? j.days_open : -1;
    const isStale = daysOpen >= 90;
    const kwBadges = (j.keywords||[]).map(k => `<span class="badge key">${esc(k)}</span>`).join('');
    return `<div class="job ${(j.keywords||[]).length > 0?'has-keywords':''}">
      <span class="when ${a.fresh?'fresh':''}" title="${daysOpen >= 0 ? daysOpen + ' days open' : 'date unknown'}">${a.fresh?'● ':''}${a.label}${isStale?' ⚠':''}</span>
      <span class="main">
        <a href="${esc(j.url)}" target="_blank" rel="noopener" title="${esc(j.description_preview)}">${esc(j.title)}</a>
        ${isNew(j)?'<span class="badge new">new</span>':''}
        <div class="sub"><span>${esc(j.company)}</span>${j.location? '<span>· ' + esc(j.location) + '</span>':''}${j.size && j.size !== 'Unknown' ? '<span>· ' + esc(j.size) + ' employees</span>' : ''}
          ${j.salary? '<span class=salary>' + esc(j.salary) + '</span>':''}</div>
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

/* --- countdown to next scheduled refresh --- */
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
[els.q, els.view, els.jobFunction, els.level, els.size, els.salMin, els.salMax, els.age].forEach(el => {
  if(el) el.addEventListener('input', render);
});

/* --- hide the filter bar on downward scroll --- */
let lastScrollY = 0;
const filtersBar = document.querySelector('.filters');
window.addEventListener('scroll', () => {
  const scrollY = window.scrollY;
  const scrollingDown = scrollY > lastScrollY;
  if(scrollY > 80 && scrollingDown) {
    filtersBar.classList.add('compact');
  } else {
    filtersBar.classList.remove('compact');
  }
  lastScrollY = scrollY;
}, { passive: true });

render();
</script>
</body>
</html>"""


if __name__ == "__main__":
    # Smoke test: python3 render_board.py  ->  writes dist/board-preview.html
    from pathlib import Path
    demo = [{
        "title": "Senior Product Manager, Fraud & Risk", "company": "Stripe",
        "location": "San Francisco, CA", "remote": True, "salary": "$180,000–$220,000",
        "level": "Senior", "posted": datetime.now(timezone.utc).isoformat(),
        "url": "https://example.com/1", "description_preview": "Own the fraud platform.",
        "functions": ["Product Manager"], "source": "greenhouse", "days_open": 1,
        "keywords": ["fraud"], "size": "1000+", "industry": "Fintech",
    }, {
        "title": "Associate Product Manager", "company": "Anthropic",
        "location": "San Francisco, CA", "remote": False, "salary": "$150,000–$180,000",
        "level": "Associate", "posted": datetime.now(timezone.utc).isoformat(),
        "url": "https://example.com/2", "description_preview": "",
        "functions": ["Product Manager"], "source": "greenhouse", "days_open": 3,
        "keywords": [], "size": "100-500", "industry": "AI/ML",
    }]
    out = Path(__file__).resolve().parent / "dist"
    out.mkdir(exist_ok=True)
    (out / "board-preview.html").write_text(
        render_html(demo, [("Stripe", 5), ("Anthropic", 3)], {"Stripe": 5, "Anthropic": 3}),
        encoding="utf-8")
    print("wrote", out / "board-preview.html")
