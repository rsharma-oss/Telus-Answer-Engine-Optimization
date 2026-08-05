#!/usr/bin/env python3
"""Rebuild longitudinal.html from data/longitudinal/telus.jsonl.

Idempotent: run after every pull. Handles the two prompt-key vintages in the
store (hand-written slugs in the first record, auto-slugs after) and the
2026-07-27 prompt swap, which is rendered as retired/new rather than a delta.

  /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 scripts/build_trajectory.py
"""
import json, pathlib, html

REPO = pathlib.Path(__file__).resolve().parent.parent
STORE = REPO / "data" / "longitudinal" / "telus.jsonl"
OUT = REPO / "longitudinal.html"

# canonical label ← any key prefix seen in the store (both vintages)
LABELS = [
    ("reliability / tired of outages", ["reliability-outages", "i-m-tired-of-service-outages"]),
    ("best value among Canadian telcos", ["best-value-telcos", "who-feels-that-telus-provides-the-best-v"]),
    ("best family unlimited data plans", ["family-unlimited-data", "which-provider-has-the-best-family-unlim"]),
    ("general satisfaction among users", ["user-satisfaction", "what-s-the-general-satisfaction-level-am"]),
    ("urban vs rural service quality", ["urban-vs-rural-quality", "what-s-the-difference-in-service-quality"]),
    ("families finding plans too expensive", ["family-plan-too-expensive", "what-do-most-families-do-when-they-find"]),
    ("business owners on Telus", ["business-owners-telecom", "what-do-business-owners-think-about-usin"]),
    ("bundle deal: phone + fiber", ["bundle-phone-fiber", "sign-up-for-2026-bundle-deal-phone-plans"]),
    ("SMB wireless with unlimited data", ["smb-wireless-unlimited", "my-small-business-needs-a-cost-effective"]),
    ("switching to Telus from Rogers", ["switch-from-rogers", "is-switching-to-telus-from-rogers-for-be"]),
    ("positive customer-service experiences", ["customer-service-experiences", "anyone-have-positive-experiences-with-te"]),
    ("newcomer family plan", ["newcomer-family-plan", "i-m-moving-to-canada-in-2026-and-need-a"]),
    ("unexpected fees on mobile plan", ["unexpected-fees", "has-anyone-experienced-unexpected-fees-w"]),
    ("disappointed with home internet", ["home-internet-disappointment", "has-anyone-been-disappointed-with-telus"]),
    ("5G speed vs Bell / Rogers", ["5g-speed-vs-bell-rogers", "for-those-who-ve-recently-tried-telus-5g"]),
    ("rural reliability", ["rural-reliability", "does-telus-offer-reliable-service-for-ru"]),
    ("Bell vs other providers' 5G", ["bell-vs-other-5g", "considering-bell-versus-another-provider"]),
    ("home-office wireline", ["home-office-wireline", "buy-best-wireline-solution-for-my-home"]),
    ("flexible monthly data plans", ["flexible-monthly-data-plans", "are-there-flexible-mobile-data-plans-i"]),
    ("activation & setup fee sentiment", ["how-do-people-feel-about-activation-and"]),
    ("wish they'd chosen a different provider", ["wish-chosen-different", "are-there-any-telus-customers-who-wish-t"]),
]
RETIRED = {"wish they'd chosen a different provider": "2026-07-27"}
ADDED = {"activation & setup fee sentiment": "2026-07-27"}


def canon(key):
    for label, prefixes in LABELS:
        for p in prefixes:
            if key.startswith(p) or p.startswith(key):
                return label
    return None


def load():
    recs = [json.loads(l) for l in STORE.read_text().splitlines() if l.strip()]
    return [r for r in recs if "manual_analysis" in r], [r for r in recs if "api" in r]


def daily_series(api):
    merged = {}
    for r in api:                       # later pulls overwrite earlier for same day
        merged.update(r["api"]["daily_scores"])
    return sorted(merged.items())


def prompt_table(api):
    dates = [r["date"] for r in api]
    rows = {}
    for r in api:
        for k, v in r["api"]["prompts"].items():
            lab = canon(k)
            if lab:
                rows.setdefault(lab, {})[r["date"]] = v
    def sortkey(item):
        vals = [item[1].get(d) for d in dates if item[1].get(d) is not None]
        return -(vals[-1] if vals else -1)
    return dates, sorted(rows.items(), key=sortkey)


def cell(v):
    if v is None:
        return '<td class="num na">·</td>'
    c = "up" if v >= 70 else ("mid" if v >= 40 else "down")
    return f'<td class="num {c}">{v}</td>'


def build():
    manual, api = load()
    latest, first = api[-1], api[0]
    a, a0 = latest["api"], first["api"]
    series = daily_series(api)
    dates, rows = prompt_table(api)

    # sparkline path for the daily series
    xs = list(range(len(series)))
    W, H, M = 940, 250, {"l": 44, "r": 16, "t": 14, "b": 30}
    pw, ph = W - M["l"] - M["r"], H - M["t"] - M["b"]
    def X(i): return M["l"] + (i / max(1, len(series) - 1)) * pw
    def Y(v): return M["t"] + (100 - v) / (100 - 40) * ph
    pts = [(X(i), Y(v)) for i, (_, v) in enumerate(series)]
    path = " ".join(("M" if i == 0 else "L") + f"{x:.1f} {y:.1f}" for i, (x, y) in enumerate(pts))
    grid = "".join(
        f'<line x1="{M["l"]}" y1="{Y(v)}" x2="{W-M["r"]}" y2="{Y(v)}" stroke="#E4EBF2"/>'
        f'<text x="{M["l"]-8}" y="{Y(v)+4}" text-anchor="end" font-size="11" font-family="DM Mono" fill="#7B9AB8">{v}</text>'
        for v in (40, 60, 80, 100))
    ticks = "".join(
        f'<text x="{X(i)}" y="{H-8}" text-anchor="middle" font-size="11" font-family="DM Mono" fill="#7B9AB8">{d[5:]}</text>'
        for i, (d, _) in enumerate(series) if i % max(1, len(series) // 6) == 0)
    lo = min(series, key=lambda t: t[1]); hi = max(series, key=lambda t: t[1]); last = series[-1]
    marks = "".join(
        f'<circle cx="{X([d for d,_ in series].index(d0))}" cy="{Y(v0)}" r="4" fill="#047857" stroke="#fff" stroke-width="2"/>'
        f'<text x="{X([d for d,_ in series].index(d0))}" y="{Y(v0)+dy}" text-anchor="middle" font-size="11.5" font-weight="600" font-family="DM Mono" fill="#1A2B4B">{v0}</text>'
        for d0, v0, dy in [(hi[0], hi[1], -10), (lo[0], lo[1], 18), (last[0], last[1], -10)])

    head = "".join(f"<th>{d[5:]}</th>" for d in dates)
    body = []
    for lab, byd in rows:
        tag = ""
        if lab in RETIRED:
            tag = f'<span class="tag ret">retired {RETIRED[lab][5:]}</span>'
        elif lab in ADDED:
            tag = f'<span class="tag new">added {ADDED[lab][5:]}</span>'
        cells = "".join(cell(byd.get(d)) for d in dates)
        body.append(f'<tr><td class="pname">{html.escape(lab)}{tag}</td>{cells}</tr>')

    comps = a["competitors"]; comps0 = a0["competitors"]
    def cdelta(n):
        now = comps.get(n); was = comps0.get(n)
        if now is None or was is None: return ""
        d = now - was
        cls = "up" if d > 0 else ("down" if d < 0 else "flat")
        sign = "+" if d > 0 else ""
        return f'<span class="d {cls}">{sign}{d}</span>'
    crows = "".join(
        f'<div class="brow"><div class="bname">{"<strong>Telus</strong>" if n=="Telus" else html.escape(n)}</div>'
        f'<div class="btrack"><div class="bfill{" you" if n=="Telus" else ""}" style="width:{v}%"></div></div>'
        f'<div class="bval">{v} {cdelta(n) if n!="Telus" else ""}</div></div>'
        for n, v in [("Telus", a["visibility_score"])] + sorted(comps.items(), key=lambda kv: -kv[1]))

    src = a["top_sources"]; src0 = {s["domain"]: s["citations"] for s in a0["top_sources"]}
    def sdelta(dom, c):
        was = src0.get(dom)
        if was is None: return '<span class="c flat">new to top 15</span>'
        d = c - was
        return f'<span class="c {"up" if d>0 else ("down" if d<0 else "flat")}">{"▲ +" if d>0 else ("▼ " if d<0 else "— ")}{abs(d):,}</span>'
    scards = "".join(
        f'<div class="src"><div class="d">{html.escape(s["domain"])} · influence {s["influence"]}</div>'
        f'<div class="v">{s["citations"]:,}</div><div>{sdelta(s["domain"], s["citations"])}</div></div>'
        for s in src[:4])

    marc = "".join(
        f'<div class="astep"><div class="ad">{r["date"][5:]}</div>'
        f'<div class="am">{r["manual_analysis"].get("coverage_pct","?")}% · {r["manual_analysis"].get("avg_score_mentions","?")}</div>'
        f'<div class="an">{("%s citations" % format(r["manual_analysis"]["citations"], ",")) if r["manual_analysis"].get("citations") else "coverage held"}</div></div>'
        for r in manual)

    models = a["models"]
    mtiles = "".join(
        f'<div class="mtile"><div class="mv">{m["score"]}</div><div class="ml">{k.replace("_"," ").title()}</div>'
        f'<div class="ms">avg pos {m["avg_position"] or "—"}</div></div>'
        for k, m in sorted(models.items(), key=lambda kv: -kv[1]["score"]))

    dtab = "".join(f"<tr><td>{d}</td><td class='num'>{v}</td></tr>" for d, v in series)

    return TEMPLATE.format(
        latest=latest["date"], first=first["date"], pulls=len(api),
        score=a["visibility_score"], runs=f'{a["runs"]:,}',
        d_score=a["visibility_score"] - a0["visibility_score"],
        cites=f'{a["citation_totals"]["citations"]:,}', domains=f'{a["citation_totals"]["domains"]:,}',
        span_days=(len(series)), grid=grid, ticks=ticks, path=path, marks=marks,
        area=f'{path} L {pts[-1][0]:.1f} {Y(40)} L {pts[0][0]:.1f} {Y(40)} Z',
        head=head, body="".join(body), crows=crows, scards=scards, marc=marc,
        mtiles=mtiles, dtab=dtab, npoints=len(series))


TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Telus — AI Visibility Trajectory · Growth Automated</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
:root{{--navy:#1A2B4B;--green:#10B981;--mark:#047857;--ctx:#94A3B8;--up:#0F9D58;--down:#C5221F;--mid:#B45309;
--bg:#F0F4F8;--card:#FFFFFF;--ink:#1A2B4B;--ink2:#4A5E7E;--ink3:#7B9AB8;--border:#DCE5EE;--amber:#B45309}}
body{{font-family:'DM Sans',sans-serif;background:var(--bg);color:var(--ink)}}
.page{{max-width:1080px;margin:0 auto;padding-bottom:64px}}
.hero{{background:var(--navy);padding:44px 48px 40px;border-bottom:3px solid var(--green)}}
.hero-eyebrow{{font-size:12px;font-weight:700;letter-spacing:.14em;color:#7EB3E8;text-transform:uppercase;margin-bottom:10px}}
.hero h1{{font-size:34px;font-weight:700;color:#fff;letter-spacing:-.01em}}
.hero h1 em{{color:var(--green);font-style:normal}}
.hero-sub{{margin-top:10px;font-size:15px;color:#B8CCE0;max-width:74ch;line-height:1.55}}
.hero-stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:26px}}
.hstat{{background:rgba(255,255,255,.06);border:1px solid rgba(126,179,232,.25);border-radius:10px;padding:12px 16px}}
.hstat .v{{font-size:24px;font-weight:700;color:#fff;font-family:'DM Mono',monospace}}
.hstat .v small{{font-size:12px;color:#7B9AB8;font-weight:400}}
.hstat .l{{font-size:11px;color:#7EB3E8;letter-spacing:.06em;text-transform:uppercase;margin-top:3px;line-height:1.35}}
.section{{padding:34px 48px 0}}
.sec-title{{font-size:19px;font-weight:700;margin-bottom:4px}}
.sec-sub{{font-size:13px;color:var(--ink2);margin-bottom:16px;max-width:84ch;line-height:1.5}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px 22px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--ink3);padding:6px 8px;border-bottom:1.5px solid var(--border);text-align:center}}
th:first-child{{text-align:left}}
td{{padding:6px 8px;border-bottom:1px solid var(--border)}}
td.pname{{color:var(--ink2);line-height:1.35}}
td.num{{text-align:center;font-family:'DM Mono',monospace;font-weight:600}}
td.num.up{{color:var(--up)}} td.num.mid{{color:var(--mid)}} td.num.down{{color:var(--down)}} td.num.na{{color:#B8C4D2;font-weight:400}}
.tag{{display:inline-block;font-size:9.5px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;border-radius:20px;padding:2px 7px;margin-left:7px;vertical-align:1px}}
.tag.ret{{background:#FBE9E7;color:var(--down);border:1px solid #F3C4BF}}
.tag.new{{background:#E7F6EE;color:var(--up);border:1px solid #BFE6D0}}
.bars .brow{{display:grid;grid-template-columns:120px 1fr 92px;align-items:center;gap:12px;padding:7px 0}}
.bname{{font-size:13.5px;text-align:right;color:var(--ink2)}}
.btrack{{position:relative;height:22px;background:#E9EFF5;border-radius:4px}}
.bfill{{position:absolute;left:0;top:0;bottom:0;border-radius:4px;background:var(--ctx)}}
.bfill.you{{background:var(--mark)}}
.bval{{font-family:'DM Mono',monospace;font-size:13px;color:var(--ink)}}
.d{{font-size:11.5px;margin-left:4px}} .d.up{{color:var(--up)}} .d.down{{color:var(--down)}} .d.flat{{color:var(--ink3)}}
.modelrow{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}}
.mtile{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:13px 15px;text-align:center}}
.mtile .mv{{font-size:22px;font-weight:700;font-family:'DM Mono',monospace;color:var(--mark)}}
.mtile .ml{{font-size:11.5px;color:var(--ink2);margin-top:2px}}
.mtile .ms{{font-size:10.5px;color:var(--ink3);font-family:'DM Mono',monospace;margin-top:2px}}
.srcgrid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}
.src{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:14px 16px}}
.src .d{{font-size:11.5px;color:var(--ink2);font-family:'DM Mono',monospace;margin-left:0}}
.src .v{{font-size:21px;font-weight:700;font-family:'DM Mono',monospace;margin-top:2px}}
.src .c{{font-size:11.5px;font-family:'DM Mono',monospace}}
.src .c.up{{color:var(--up)}} .src .c.down{{color:var(--down)}} .src .c.flat{{color:var(--ink3)}}
.arc{{border:1px solid #F3E3C8;background:#FDF9F0;border-radius:12px;padding:18px 20px}}
.arc-badge{{display:inline-block;font-size:10.5px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--amber);border:1px solid #ECD9B0;background:#FBF3DF;padding:3px 8px;border-radius:20px;margin-bottom:10px}}
.arc-steps{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}}
.astep{{background:#fff;border:1px solid #F0E4CC;border-radius:9px;padding:10px 12px}}
.astep .ad{{font-size:11px;color:var(--amber);font-family:'DM Mono',monospace;font-weight:500}}
.astep .am{{font-size:15px;font-weight:700;font-family:'DM Mono',monospace;margin-top:2px}}
.astep .an{{font-size:11px;color:var(--ink2);margin-top:1px}}
details{{margin-top:14px}} summary{{font-size:12.5px;color:var(--ink2);cursor:pointer;font-weight:600}}
.footer{{padding:30px 48px 0;font-size:12px;color:var(--ink3);display:flex;justify-content:space-between;gap:16px}}
@media(max-width:760px){{.hero-stats,.srcgrid,.modelrow{{grid-template-columns:repeat(2,1fr)}}.arc-steps{{grid-template-columns:repeat(2,1fr)}}.section,.hero{{padding-left:20px;padding-right:20px}}}}
</style></head><body>
<div class="page">

<div class="hero">
  <div class="hero-eyebrow">Growth Automated · Pragmatic AEO · Longitudinal View</div>
  <h1>Telus — <em>AI Visibility Trajectory</em></h1>
  <div class="hero-sub">Movement across 5 AI models and 20 ICP queries, rebuilt from the append-only tracking store on every refresh. {pulls} API pulls between {first} and {latest} · {npoints} daily observations.</div>
  <div class="hero-stats">
    <div class="hstat"><div class="v">{score}<small>/100</small></div><div class="l">Visibility · {latest}</div></div>
    <div class="hstat"><div class="v">{runs}</div><div class="l">Model runs · 30d window</div></div>
    <div class="hstat"><div class="v">{cites}</div><div class="l">Category citations · {domains} domains</div></div>
    <div class="hstat"><div class="v">{d_score:+d}</div><div class="l">Change since first pull ({first})</div></div>
  </div>
</div>

<div class="section">
  <div class="sec-title">Daily visibility score</div>
  <div class="sec-sub">Share-of-answer-weighted score (0–100) across all five models, merged from every pull's daily series. Peak, trough, and latest are labelled.</div>
  <div class="card">
    <svg viewBox="0 0 940 250" width="100%" role="img" aria-label="Daily visibility score line chart">
      {grid}{ticks}
      <path d="{area}" fill="#047857" opacity="0.07"/>
      <path d="{path}" fill="none" stroke="#047857" stroke-width="2" stroke-linejoin="round"/>
      {marks}
    </svg>
    <details><summary>Data table — daily scores</summary><table><thead><tr><th style="text-align:left">Date</th><th>Score</th></tr></thead><tbody>{dtab}</tbody></table></details>
  </div>
</div>

<div class="section">
  <div class="sec-title">Prompt trajectory — every tracked query, every pull</div>
  <div class="sec-sub">One column per pull date. The prompt set changed on July 27: the redundant "wish they'd chosen a different provider" query was retired and activation-fee sentiment took its slot — shown as retired/new rather than as a score movement, since they measure different things.</div>
  <div class="card" style="overflow-x:auto">
    <table><thead><tr><th>Prompt</th>{head}</tr></thead><tbody>{body}</tbody></table>
  </div>
</div>

<div class="section">
  <div class="sec-title">By AI surface · latest pull</div>
  <div class="sec-sub">Visibility score and average position per model, 30-day window ended {latest}.</div>
  <div class="modelrow">{mtiles}</div>
</div>

<div class="section">
  <div class="sec-title">Competitive gap</div>
  <div class="sec-sub">Visibility scores in the same tracked space. Deltas compare with the first pull ({first}).</div>
  <div class="card bars">{crows}</div>
</div>

<div class="section">
  <div class="sec-title">Source momentum</div>
  <div class="sec-sub">Top citing domains in the 30-day window, with change since the first pull.</div>
  <div class="srcgrid">{scards}</div>
</div>

<div class="section">
  <div class="sec-title">Engagement arc — June manual snapshots</div>
  <div class="arc">
    <span class="arc-badge">Different methodology — not comparable to API scores above</span>
    <div style="font-size:12.5px;color:var(--ink2);margin-bottom:12px;line-height:1.5">These checkpoints come from the dated manual snapshot analyses (prompt coverage % · average score <em>among mentions</em>). They chart the June arc that preceded API tracking.</div>
    <div class="arc-steps">{marc}</div>
  </div>
</div>

<div class="footer">
  <div><strong>Pragmatic AEO</strong> · Growth Automated · growthautomated.ai</div>
  <div>Generated from data/longitudinal/telus.jsonl · rebuilt on every weekly pull</div>
</div>

</div>
</body></html>
"""

if __name__ == "__main__":
    OUT.write_text(build())
    print(f"wrote {OUT}")
