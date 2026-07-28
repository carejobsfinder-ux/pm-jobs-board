#!/usr/bin/env python3
"""
Landing page renderer for pm_jobs_board.py  (direction 1B — "Terminal")
=======================================================================

Drop this file next to pm_jobs_board.py and wire it up in two lines.

1. At the top of pm_jobs_board.py, next to the other imports:

       from render_landing import render_landing_html

2. In run(), right after the two existing writes:

       (out / "landing.html").write_text(
           render_landing_html(deduped, trending, company_counts), encoding="utf-8"
       )

   If you'd rather the landing page BE the site root and the board live at
   /board, swap the two filenames instead:

       (out / "board.html").write_text(render_html(deduped, trending, company_counts), encoding="utf-8")
       (out / "index.html").write_text(
           render_landing_html(deduped, trending, company_counts, board_url="board.html"),
           encoding="utf-8"
       )

Design notes (so edits stay in voice):
  * Modernist structure — flush-left everything, zero border radius, 2px rules
    as section seams, ink on near-white, one accent used sparingly.
  * The accent is the board's own emerald (#10b981 / #059669) so the landing
    page and dist/index.html read as one product.
  * Fully responsive: single column under 860px, nav links fold under 720px.
  * No dependencies, no build step, no tracking. Stdlib only.
"""

import html as html_mod
import json
from datetime import datetime, timezone

# Partner names shown in the grayscale marquee. Kept explicit rather than
# derived, so the row stays legible even on a thin run; every name here must
# be a company whose board is actually in the seed list.
MARQUEE_COMPANIES = [
    "Stripe", "Anthropic", "Linear", "Figma", "Ramp", "Vercel",
    "Notion", "Databricks", "Coinbase", "Cloudflare", "Airtable", "Asana",
]


def render_landing_html(jobs, trending, company_counts, board_url="index.html",
                        refresh_hour_pt=7) -> str:
    """Return the full landing page as one self-contained HTML string."""
    now_utc = datetime.now(timezone.utc)

    total = len(jobs)

    # roles first published in the last 24h
    fresh = 0
    for j in jobs:
        posted = j.get("posted")
        if not posted:
            continue
        try:
            dt = datetime.fromisoformat(str(posted).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if (now_utc - dt).total_seconds() < 86_400:
                fresh += 1
        except (ValueError, TypeError):
            continue

    companies = len(company_counts) if company_counts else len({j.get("company") for j in jobs})

    # trending rows — top five hirers, same data the board's widget uses
    rows = []
    for co, cnt in (trending or [])[:5]:
        rows.append(
            '<li class="hirer"><span class="hirer-name">%s</span>'
            '<span class="hirer-count">%s</span></li>'
            % (html_mod.escape(str(co)), html_mod.escape(str(cnt)))
        )
    trending_rows = "\n              ".join(rows) or \
        '<li class="hirer"><span class="hirer-name">No roles in this run</span>'\
        '<span class="hirer-count">0</span></li>'

    marquee = "".join("<span>%s</span>" % html_mod.escape(c) for c in MARQUEE_COMPANIES)

    return (TEMPLATE
            .replace("__BOARD_URL__", html_mod.escape(board_url, quote=True))
            .replace("__COUNT__", f"{total:,}")
            .replace("__FRESH__", f"{fresh:,}")
            .replace("__COMPANIES__", f"{companies:,}")
            .replace("__REFRESH_HOUR__", str(refresh_hour_pt))
            .replace("__GENERATED__", html_mod.escape(now_utc.strftime("%Y-%m-%d %H:%M UTC")))
            .replace("__GENERATED_ISO__", html_mod.escape(now_utc.isoformat()))
            .replace("__TRENDING_ROWS__", trending_rows)
            .replace("__MARQUEE__", marquee))


TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PM Jobs Board — __COUNT__ open product & people roles</title>
<meta name="description" content="__COUNT__ live product and people roles, read every morning straight off __COMPANIES__ company job boards. Published salary ranges, no recruiter reposts, no account.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  :root{
    --paper:#f9fafb; --white:#ffffff; --ink:#111827;
    --ink-70:#4b5563; --ink-55:#6b7280; --hair:#e5e7eb;
    --accent:#10b981; --accent-600:#059669; --accent-700:#047857;
    --font:"Archivo",system-ui,-apple-system,sans-serif;
    --mono:ui-monospace,"SF Mono",Menlo,monospace;
    --edge:clamp(20px,5vw,64px);
  }
  *{box-sizing:border-box}
  html{scroll-behavior:smooth}
  @media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
  body{margin:0;background:var(--paper);color:var(--ink);font:400 16px/1.6 var(--font);text-wrap:pretty;-webkit-font-smoothing:antialiased}
  h1,h2,h3{font-weight:800;letter-spacing:-0.025em;margin:0;line-height:1.06}
  p{margin:0}
  a{color:inherit;text-decoration:none;transition:color .18s ease}
  a:hover{color:var(--accent-700)}
  ul{margin:0;padding:0;list-style:none}
  :focus-visible{outline:2px solid var(--accent-600);outline-offset:2px}
  ::selection{background:color-mix(in srgb,var(--accent) 28%,transparent)}
  .wrap{max-width:1200px;margin:0 auto;padding:0 var(--edge)}
  .rule{height:2px;border:0;margin:0;background:var(--ink)}
  .mono{font-family:var(--mono)}
  .kicker{display:inline-flex;align-items:center;gap:8px;font:700 12px/1 var(--mono);letter-spacing:.06em;text-transform:uppercase;color:var(--accent-700);border:1px solid var(--accent);padding:6px 10px}
  .mark{width:12px;height:12px;background:var(--accent);display:block;flex:none}

  /* buttons — flush-left labels, zero radius, 2px edges */
  .btn{display:inline-flex;align-items:center;justify-content:flex-start;gap:8px;
    font:800 15px/1.2 var(--font);text-align:left;border:2px solid transparent;border-radius:0;
    padding:13px 22px;cursor:pointer;transition:background .18s ease,color .18s ease,border-color .18s ease}
  .btn-primary{background:var(--accent-600);border-color:var(--accent-600);color:var(--white)}
  .btn-primary:hover{background:var(--accent-700);border-color:var(--accent-700);color:var(--white)}
  .btn-primary:active{background:#065f46;border-color:#065f46}
  .btn-ghost{background:transparent;border-color:var(--ink);color:var(--ink)}
  .btn-ghost:hover{border-color:var(--accent-600);color:var(--accent-700);background:color-mix(in srgb,var(--accent) 10%,transparent)}
  .btn-sm{font-size:14px;padding:9px 16px}
  .btn-invert{background:var(--accent);border-color:var(--accent);color:var(--ink)}
  .btn-invert:hover{background:var(--paper);border-color:var(--paper);color:var(--ink)}

  /* nav — sticky, glass */
  .nav{position:sticky;top:0;z-index:30;display:flex;align-items:center;gap:32px;
    padding:14px var(--edge);background:color-mix(in srgb,var(--paper) 76%,transparent);
    backdrop-filter:blur(16px) saturate(140%);-webkit-backdrop-filter:blur(16px) saturate(140%);
    border-bottom:2px solid var(--ink)}
  .nav-inner{max-width:1200px;margin:0 auto;width:100%;display:flex;align-items:center;gap:32px}
  .brand{display:flex;align-items:center;gap:10px;font:800 18px/1 var(--font);letter-spacing:-0.01em;margin-right:auto}
  .nav a.nav-link{font:600 14px/1 var(--font);white-space:nowrap}

  /* hero */
  .hero{display:grid;grid-template-columns:minmax(0,1.28fr) minmax(0,.72fr);gap:56px;align-items:center;padding:80px 0 60px}
  .hero h1{font-size:clamp(38px,4.6vw,58px);margin:22px 0 0;margin-left:-.055em}
  .hero h1 .line{display:block}
  .hero .sub{font-size:17px;line-height:28px;max-width:52ch;margin-top:26px;color:var(--ink-70)}
  .hero .row{display:flex;gap:12px;flex-wrap:wrap;margin-top:32px}
  .hero .facts{display:flex;gap:26px;flex-wrap:wrap;margin-top:32px;padding-top:24px;border-top:2px solid var(--hair);font:400 12px/1 var(--mono);color:var(--ink-55)}

  /* board preview */
  .board{border:2px solid var(--ink);background:var(--white);box-shadow:0 12px 32px color-mix(in srgb,#111827 14%,transparent)}
  .board-bar{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 16px;background:var(--ink);color:var(--paper);font:400 11px/1 var(--mono);letter-spacing:.06em;text-transform:uppercase}
  .board-bar span{display:flex;align-items:center;gap:8px}
  .board-bar .dot{width:8px;height:8px;background:var(--accent);display:block}
  .board-body{padding:18px 16px}
  .tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
  .tile{border:1px solid var(--hair);padding:12px}
  .tile b{display:block;font:700 24px/1 var(--mono)}
  .tile .accent{color:var(--accent-600)}
  .tile small{display:block;font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-55);margin-top:6px}
  .chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:16px}
  .chip{font:700 11px/1 var(--font);padding:6px 10px;border:1px solid var(--hair);color:var(--ink-70)}
  .chip.on{background:var(--accent);border-color:var(--accent);color:var(--white)}
  .hirers{margin-top:18px;border-top:2px solid var(--hair);padding-top:14px}
  .hirers h2{font:700 10px/1 var(--font);letter-spacing:.1em;text-transform:uppercase;color:var(--ink-55)}
  .hirer{display:flex;justify-content:space-between;padding:9px 0;border-bottom:1px solid var(--hair);font-size:13px}
  .hirer:last-child{border-bottom:0}
  .hirer-name{font-weight:700}
  .hirer-count{font:700 13px/1.4 var(--mono);color:var(--accent-600)}

  /* marquee */
  .proof{border-top:2px solid var(--ink);border-bottom:2px solid var(--ink);background:var(--white);padding:20px 0;overflow:hidden}
  .marquee{display:flex;gap:56px;width:max-content;animation:marquee 38s linear infinite;filter:grayscale(1) contrast(1.05);opacity:.5}
  .marquee>div{display:flex;gap:56px;font:800 20px/1 var(--font);letter-spacing:-0.015em;white-space:nowrap}
  @keyframes marquee{from{transform:translateX(0)}to{transform:translateX(-50%)}}
  @media (prefers-reduced-motion:reduce){.marquee{animation:none;flex-wrap:wrap;width:auto}}

  /* features — bento */
  .features{padding:60px 0 56px}
  .features-head{display:flex;align-items:baseline;justify-content:space-between;gap:24px;flex-wrap:wrap}
  .features-head h2{font-size:clamp(26px,3.2vw,34px);margin-left:-.03em}
  .features-head .idx{font:400 12px/1 var(--mono);color:var(--ink-55)}
  .bento{display:grid;grid-template-columns:repeat(3,1fr);gap:2px;background:var(--ink);border:2px solid var(--ink);margin-top:36px}
  .cell{background:var(--white);padding:28px 24px 30px;display:flex;flex-direction:column;gap:12px}
  .cell .num{font:400 11px/1 var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--ink-55)}
  .cell h3{font-size:21px;line-height:1.2}
  .cell p{font-size:14.5px;line-height:24px;color:var(--ink-70)}
  .cell .mark{width:14px;height:14px}
  .cell-wide{background:var(--paper);grid-column:span 2;flex-direction:row;align-items:center;gap:24px;flex-wrap:wrap;padding:26px 24px}
  .cell-wide div{flex:1;min-width:240px}
  .cell-wide h3{font-size:19px;letter-spacing:-0.01em}
  .cell-wide p{margin-top:8px}
  .badge{font:700 11px/1 var(--mono);padding:6px 10px;background:var(--accent);color:var(--white)}
  .cell-stat{background:var(--paper);justify-content:center;gap:6px;padding:26px 24px}
  .cell-stat b{font:700 30px/1 var(--mono);color:var(--accent-600)}
  .cell-stat small{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-55)}

  /* close */
  .close{background:var(--ink);color:var(--paper)}
  .close .wrap{padding:76px var(--edge)}
  .close .grid{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,.8fr);gap:56px;align-items:end}
  .close h2{font-size:clamp(30px,3.8vw,40px);line-height:1.07;margin-left:-.05em}
  .close h2 .line{display:block}
  .close h2 .accent{color:var(--accent)}
  .close p{font-size:15.5px;line-height:26px;color:#cbd5e1}
  .signup{display:flex;gap:8px;margin-top:20px}
  .input{flex:1;min-width:0;font:400 14px/1.2 var(--font);padding:12px;border:2px solid var(--paper);border-radius:0;background:transparent;color:var(--paper)}
  .input::placeholder{color:#94a3b8}
  .close .btn-primary{border-color:var(--accent-600)}
  .close-row{margin-top:40px}

  /* footer */
  footer{background:var(--white)}
  .fgrid{display:grid;grid-template-columns:minmax(0,1.3fr) repeat(3,minmax(0,.7fr));gap:40px;padding:52px 0 36px}
  .fgrid p{font-size:14px;line-height:24px;margin-top:14px;max-width:32ch;color:var(--ink-55)}
  .fcol{display:flex;flex-direction:column;gap:10px}
  .fcol h2{font:700 11px/1 var(--font);letter-spacing:.1em;text-transform:uppercase;color:var(--ink-55);margin-bottom:4px}
  .fcol a{font-size:14px}
  .legal{border-top:2px solid var(--ink);padding:18px 0 36px;display:flex;justify-content:space-between;gap:20px;flex-wrap:wrap;font-size:13px;color:var(--ink-55)}

  /* responsive */
  @media (max-width:980px){
    .hero{grid-template-columns:1fr;gap:40px;padding:56px 0 48px}
    .close .grid{grid-template-columns:1fr;gap:32px;align-items:start}
    .fgrid{grid-template-columns:1fr 1fr;gap:32px}
  }
  @media (max-width:860px){
    .bento{grid-template-columns:1fr}
    .cell-wide{grid-column:span 1}
  }
  @media (max-width:720px){
    .nav a.nav-link{display:none}
    .tiles{grid-template-columns:1fr 1fr}
    .btn{width:100%;justify-content:flex-start}
    .hero .row .btn{width:auto}
  }
  @media (max-width:560px){
    .fgrid{grid-template-columns:1fr}
    .signup{flex-direction:column}
    .signup .btn{width:100%}
    .hero .row{flex-direction:column;align-items:stretch}
    .hero .row .btn{width:100%}
  }
</style>
</head>
<body>

<nav class="nav">
  <div class="nav-inner">
    <span class="brand"><span class="mark"></span>PM Jobs Board</span>
    <a class="nav-link" href="__BOARD_URL__">The board</a>
    <a class="nav-link" href="#how">How it works</a>
    <a class="nav-link" href="#companies">Companies</a>
    <a class="nav-link" href="#digest">Digest</a>
    <a class="btn btn-primary btn-sm" href="__BOARD_URL__">Browse open roles</a>
  </div>
</nav>

<main>
  <div class="wrap">
    <section class="hero">
      <div>
        <span class="kicker"><span class="dot" style="width:7px;height:7px;background:var(--accent);display:block"></span><span id="freshness">updated __GENERATED__</span></span>
        <h1>
          <span class="line">Stop refreshing</span>
          <span class="line">forty career pages.</span>
        </h1>
        <p class="sub">__COUNT__ live product and people roles, read every morning off __COMPANIES__ company job boards — with the salary range the company actually published, and nothing that closed yesterday.</p>
        <div class="row">
          <a class="btn btn-primary" href="__BOARD_URL__">Browse open roles →</a>
          <a class="btn btn-ghost" href="#digest">Get the Monday digest</a>
        </div>
        <div class="facts">
          <span>5 ATS APIs</span><span>US roles only</span><span>no account</span><span>no tracking</span>
        </div>
      </div>

      <div class="board" aria-label="Preview of the live board">
        <div class="board-bar">
          <span><span class="dot"></span>the board</span>
          <span>next refresh <span id="countdown">—</span></span>
        </div>
        <div class="board-body">
          <div class="tiles">
            <div class="tile"><b class="accent">__COUNT__</b><small>open roles</small></div>
            <div class="tile"><b class="accent">+__FRESH__</b><small>new in 24h</small></div>
            <div class="tile"><b>__COMPANIES__</b><small>companies</small></div>
          </div>
          <div class="chips">
            <span class="chip on">Product Manager</span>
            <span class="chip">People Partner</span>
            <span class="chip">AI/ML</span>
            <span class="chip">Fintech</span>
            <span class="chip">Remote</span>
            <span class="chip">$180k+</span>
          </div>
          <div class="hirers" id="companies">
            <h2>Trending hirers</h2>
            <ul>
              __TRENDING_ROWS__
            </ul>
          </div>
        </div>
      </div>
    </section>
  </div>

  <div class="proof" aria-label="Companies on the board">
    <div class="marquee">
      <div>__MARQUEE__</div>
      <div aria-hidden="true">__MARQUEE__</div>
    </div>
  </div>

  <div class="wrap">
    <section class="features" id="how">
      <div class="features-head">
        <h2>Built like a tool, not a listing site.</h2>
        <span class="idx">03 / features</span>
      </div>
      <div class="bento">
        <article class="cell">
          <span class="mark"></span>
          <div class="num">01 · source</div>
          <h3>Read from the company itself</h3>
          <p>Greenhouse, Lever, Ashby, Workable and Recruitee — the same boards their recruiters post to. Pulled down, deduped, and gone the moment the company closes the role.</p>
        </article>
        <article class="cell">
          <span class="mark"></span>
          <div class="num">02 · pay</div>
          <h3>Salary parsed, not promised</h3>
          <p>Published ranges are lifted out of the posting body so you can set a floor and filter. If a company printed no number, the row says so — nothing is estimated.</p>
        </article>
        <article class="cell">
          <span class="mark"></span>
          <div class="num">03 · fit</div>
          <h3>Filters for a real search</h3>
          <p>Function, level, headcount, industry, workplace, posting age. Pin the specialisms you want, star what you're working, hide what you're not — all kept in your browser.</p>
        </article>
        <article class="cell cell-wide">
          <div>
            <h3>New since your last visit</h3>
            <p>The board remembers when you were here and badges everything posted since. Two minutes a morning, not forty tabs.</p>
          </div>
          <span class="badge">NEW</span>
        </article>
        <article class="cell cell-stat">
          <b>__REFRESH_HOUR__:00</b>
          <small>AM Pacific · every day</small>
        </article>
      </div>
    </section>
  </div>

  <section class="close" id="digest">
    <div class="wrap">
      <div class="grid">
        <h2>
          <span class="line">Open the board.</span>
          <span class="line accent">It's already up to date.</span>
        </h2>
        <div>
          <p>Or take it by email — one Monday note with the week's new roles and the companies that started hiring.</p>
          <form class="signup" action="" method="post">
            <label for="email" class="mono" style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)">Email address</label>
            <input class="input" id="email" name="email" type="email" placeholder="you@work.com" required>
            <button class="btn btn-primary" type="submit">Subscribe</button>
          </form>
        </div>
      </div>
      <div class="close-row">
        <a class="btn btn-invert" href="__BOARD_URL__">Browse __COUNT__ open roles →</a>
      </div>
    </div>
  </section>
</main>

<footer>
  <div class="wrap">
    <div class="fgrid">
      <div>
        <span class="brand"><span class="mark"></span>PM Jobs Board</span>
        <p>A static board generated every morning from public ATS APIs. No accounts, no tracking, no sponsored rows.</p>
      </div>
      <nav class="fcol">
        <h2>Board</h2>
        <a href="__BOARD_URL__">All open roles</a>
        <a href="__BOARD_URL__">Product Manager</a>
        <a href="__BOARD_URL__">People Partner</a>
        <a href="__BOARD_URL__">Remote only</a>
      </nav>
      <nav class="fcol">
        <h2>Companies</h2>
        <a href="#companies">Trending hirers</a>
        <a href="__BOARD_URL__">By industry</a>
        <a href="__BOARD_URL__">By headcount</a>
        <a href="#digest">Suggest a company</a>
      </nav>
      <nav class="fcol">
        <h2>About</h2>
        <a href="#how">How it works</a>
        <a href="#how">Data sources</a>
        <a href="jobs.json">jobs.json</a>
        <a href="#digest">Contact</a>
      </nav>
    </div>
    <div class="legal">
      <span>© <span id="year">2026</span> PM Jobs Board. Built from public ATS APIs.</span>
      <span class="mono">generated <time datetime="__GENERATED_ISO__">__GENERATED__</time></span>
    </div>
  </div>
</footer>

<script>
  var REFRESH_HOUR_PT = __REFRESH_HOUR__;

  document.getElementById('year').textContent = new Date().getFullYear();

  /* "updated N minutes ago", localized */
  (function(){
    var el = document.getElementById('freshness');
    var d = new Date("__GENERATED_ISO__");
    if (isNaN(d)) return;
    var mins = Math.max(0, Math.round((Date.now() - d.getTime()) / 6e4));
    el.textContent = mins < 1 ? 'refreshed just now'
      : mins < 60 ? 'refreshed ' + mins + ' minutes ago'
      : 'refreshed ' + Math.round(mins / 60) + 'h ago';
  })();

  /* countdown to the next scheduled build — same clock as the board */
  function msToNextRefresh(){
    var p = {};
    new Intl.DateTimeFormat('en-US', {timeZone:'America/Los_Angeles', hour12:false,
      hour:'2-digit', minute:'2-digit', second:'2-digit'})
      .formatToParts(new Date()).forEach(function(x){ p[x.type] = x.value; });
    var secs = (Number(p.hour) % 24) * 3600 + Number(p.minute) * 60 + Number(p.second);
    var diff = REFRESH_HOUR_PT * 3600 - secs;
    if (diff <= 0) diff += 86400;
    return diff * 1000;
  }
  function tick(){
    var ms = msToNextRefresh();
    var h = Math.floor(ms / 36e5), m = Math.floor(ms % 36e5 / 6e4), s = Math.floor(ms % 6e4 / 1e3);
    document.getElementById('countdown').textContent = h > 0 ? h + 'h ' + m + 'm' : m + 'm ' + s + 's';
  }
  tick(); setInterval(tick, 1000);
</script>
</body>
</html>"""


if __name__ == "__main__":
    # Smoke test: python3 render_landing.py  ->  writes dist/landing.html
    from pathlib import Path
    demo_jobs = [{"company": c, "posted": datetime.now(timezone.utc).isoformat()}
                 for c in ("Stripe", "Anthropic", "Linear", "Figma")]
    demo_trending = [("Stripe", 5), ("Anthropic", 3), ("Linear", 2), ("Figma", 2)]
    out = Path(__file__).resolve().parent / "dist"
    out.mkdir(exist_ok=True)
    (out / "landing.html").write_text(
        render_landing_html(demo_jobs, demo_trending, {c: 1 for c in ("Stripe", "Anthropic", "Linear", "Figma")}),
        encoding="utf-8",
    )
    print("wrote", out / "landing.html")
