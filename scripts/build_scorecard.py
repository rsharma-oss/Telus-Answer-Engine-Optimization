#!/usr/bin/env python3
"""Regenerate scorecard.html entirely from the longitudinal store.

Every data region is rebuilt on each run: hero, gauge, trajectory strip,
current-state stats, daily-score chart, prompt table, competitor grid,
cited sources, footer. Nothing is hand-maintained, so nothing goes stale.

The June/July manual-analysis sections (coverage %, avg-score-among-mentions,
sentiment volume) were REMOVED 2026-09-02 at the operator's direction — they
were a different metric family and had gone stale. Do not reintroduce them
without a matching data source in the store.
"""
import datetime, json, pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent
STORE = REPO / "data" / "longitudinal" / "telus.jsonl"
PAGE = REPO / "scorecard.html"
COLORS = ["#EF4444", "#F59E0B", "#0066CC", "#94A3B8", "#94A3B8", "#94A3B8"]
LABELS = [
    (["reliability-outages", "i-m-tired-of-service-outages"],
     "I'm tired of service outages — is there a telecom known for reliability in 2026?"),
    (["best-value-telcos", "who-feels-that-telus-provides-the-best-v"],
     "Who feels that Telus provides the best value among Canadian telcos?"),
    (["family-unlimited-data", "which-provider-has-the-best-family-unlim"],
     "Which provider has the best family unlimited data plans in 2026?"),
    (["user-satisfaction", "what-s-the-general-satisfaction-level-am"],
     "What's the general satisfaction level among Telus users in 2026?"),
    (["urban-vs-rural-quality", "what-s-the-difference-in-service-quality"],
     "What's the difference in service quality for urban vs rural areas?"),
    (["family-plan-too-expensive", "what-do-most-families-do-when-they-find"],
     "What do most families do when their wireless plan is too expensive?"),
    (["business-owners-telecom", "what-do-business-owners-think-about-usin"],
     "What do business owners think about using Telus for their company?"),
    (["bundle-phone-fiber", "sign-up-for-2026-bundle-deal-phone-plans"],
     "Sign up for 2026 bundle deal: phone plans with fiber optic internet"),
    (["smb-wireless-unlimited", "my-small-business-needs-a-cost-effective"],
     "My small business needs cost-effective wireless with unlimited data"),
    (["switch-from-rogers", "is-switching-to-telus-from-rogers-for-be"],
     "Is switching to Telus from Rogers for better internet speeds worth it?"),
    (["customer-service-experiences", "anyone-have-positive-experiences-with-te"],
     "Anyone have positive experiences with Telus customer service?"),
    (["newcomer-family-plan", "i-m-moving-to-canada-in-2026-and-need-a"],
     "I'm moving to Canada in 2026 and need a reliable family wireless plan"),
    (["unexpected-fees", "has-anyone-experienced-unexpected-fees-w"],
     "Has anyone experienced unexpected fees with their Telus mobile plan?"),
    (["home-internet-disappointment", "has-anyone-been-disappointed-with-telus"],
     "Has anyone been disappointed with Telus' home internet service?"),
    (["5g-speed-vs-bell-rogers", "for-those-who-ve-recently-tried-telus-5g"],
     "For those who've tried Telus 5G — how's the speed vs Bell and Rogers?"),
    (["rural-reliability", "does-telus-offer-reliable-service-for-ru"],
     "Does Telus offer reliable service for rural residents in 2026?"),
    (["bell-vs-other-5g", "considering-bell-versus-another-provider"],
     "Considering Bell versus another provider — is 5G coverage comparable?"),
    (["home-office-wireline", "buy-best-wireline-solution-for-my-home"],
     "Buy best wireline solution for my home office setup"),
    (["flexible-monthly-data-plans", "are-there-flexible-mobile-data-plans-i"],
     "Are there flexible mobile data plans I can adjust monthly based on usage?"),
    (["activation-fee-sentiment", "how-do-people-feel-about-activation-and"],
     "How do people feel about activation and setup fees from Canadian carriers?"),
]


def pretty(d):
    return datetime.date.fromisoformat(d).strftime("%B %-d, %Y")


def short(d):
    return datetime.date.fromisoformat(d).strftime("%b %-d")


def label_for(key):
    for prefixes, text in LABELS:
        for p in prefixes:
            if key.startswith(p) or p.startswith(key):
                return text
    return key.replace("-", " ").capitalize()


def model_label(m):
    return (m.replace("_", " ").replace("google ", "Google ").title()
            .replace("Ai", "AI").replace("Chatgpt", "ChatGPT"))


def splice(src, name, content):
    a = src.index(f"<!-- {name}:START -->") + len(f"<!-- {name}:START -->")
    b = src.index(f"<!-- {name}:END -->")
    return src[:a] + content + src[b:]


def esc(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#x27;")


def build_actions(a, d):
    """Three priority actions derived from the current data: the two weakest
    prompts, then the most contested mid-band prompt. Every number is read from
    the store — per-surface detail comes from the 7-day prompt x model matrix —
    so a card can never quote a stale score."""
    scored = sorted(((k, v) for k, v in a["prompts"].items() if v is not None), key=lambda kv: kv[1])
    matrix = a.get("prompt_matrix_7d", {})
    srcs = a["top_sources"]
    ring = sorted(a["competitors"].items(), key=lambda kv: -kv[1])
    lead = ring[0] if ring else ("Bell", 0)
    second = ring[1] if len(ring) > 1 else ("Rogers", 0)

    def surfaces(key):
        row = None
        for mk, mv in matrix.items():
            if mk.startswith(key[:30]) or key.startswith(mk[:30]):
                row = mv
                break
        if not row:
            return None, None
        names = {"gpt-4o-mini": "ChatGPT", "gemini-2.5-flash": "Gemini", "sonar": "Perplexity",
                 "google-aio": "Google AIO", "google-ai-mode": "Google AI Mode"}
        parts, zeros = [], []
        for m, label in names.items():
            v = row["models"].get(m)
            if v is None:
                continue
            parts.append(f"{label} {v}")
            if v == 0:
                zeros.append(label)
        return " · ".join(parts), zeros

    contested = [kv for kv in scored if 40 <= kv[1] <= 65]
    picks = [scored[0], scored[1], (contested[0] if contested else scored[2])]

    cards = []
    for i, (key, val) in enumerate(picks, start=1):
        q = label_for(key)
        target = 60 if val < 20 else (70 if val < 45 else 80)
        per_surface, zeros = surfaces(key)
        src = srcs[(i - 1) % max(1, len(srcs))]
        if zeros:
            diag = (f'Zero presence on {", ".join(zeros)} — on those surfaces the answer is written without Telus in it. '
                    if len(zeros) < 5 else 'Zero presence on every tracked surface. ')
        else:
            diag = 'Telus is named but not authoritatively. '
        detail = f'Across surfaces: {per_surface}. ' if per_surface else ''
        cards.append(
            f'<div class="action-card">\n'
            f'      <div class="action-num">0{i} · HIGH</div>\n'
            f'      <div class="action-title">{esc(q)}</div>\n'
            f'      <div class="action-body">Scores <strong>{val}/100</strong> as of {pretty(d)}. {detail}{diag}'
            f'{lead[0]} ({lead[1]}) and {second[0]} ({second[1]}) are the co-cited names in this space, and '
            f'{src["domain"]} ({src["citations"]:,} citations, influence {src["influence"]}) is among the sources '
            f'models pull from to answer it.</div>\n'
            f'      <div class="action-impact">Lift from {val}/100 toward {target}+</div>\n    </div>')
    return '<div class="actions-grid">' + "\n".join(cards) + '</div>'


def build():
    recs = [json.loads(l) for l in STORE.read_text().splitlines() if l.strip()]
    api = [r for r in recs if "api" in r]
    latest, first = api[-1], api[0]
    a, a0 = latest["api"], first["api"]
    d = latest["date"]
    models = a["models"]
    best = max(models.items(), key=lambda kv: kv[1]["score"])
    worst = min(models.items(), key=lambda kv: kv[1]["score"])
    daily = sorted(a["daily_scores"].items())
    last7 = [v for _, v in daily[-7:]]
    score = a["visibility_score"]
    delta = score - a0["visibility_score"]

    # ---- hero + gauge -------------------------------------------------
    hero = (
        f'<div class="hero-eyebrow">30-day window ending {pretty(d)} · {a["runs"]:,} runs · 5 AI models · 20 tracked ICP queries</div>\n'
        f'      <div class="hero-headline">Telus AI visibility at <em>{score}/100</em> — {a.get("trend","stable")}.</div>\n'
        f'      <div class="hero-sub">Across <strong>{a["runs"]:,} runs</strong> in the 30 days to {pretty(d)}, Telus scored '
        f'<strong>{score}/100</strong>. {model_label(best[0])} is the strongest surface (<strong>{best[1]["score"]}</strong>); '
        f'{model_label(worst[0])} the weakest (<strong>{worst[1]["score"]}</strong>). Daily scores over the last week ran '
        f'{min(last7)}–{max(last7)}. Tracking spans {len(api)} pulls since {pretty(first["date"])} '
        f'({"no net change" if delta == 0 else f"{delta:+d} points"} over that span). The remaining gaps are all '
        f'unbranded commercial-intent prompts.</div>'
    )
    circ = 339.3
    gauge = (
        f'<div class="gauge-wrap">\n'
        f'      <svg class="gauge-svg" width="140" height="140" viewBox="0 0 140 140">\n'
        f'        <circle class="gauge-bg" cx="70" cy="70" r="54"/>\n'
        f'        <circle fill="none" stroke="#10B981" stroke-width="12" stroke-linecap="round" cx="70" cy="70" r="54" '
        f'stroke-dasharray="{circ}" stroke-dashoffset="{circ * (1 - score/100):.1f}"/>\n'
        f'        <g transform="rotate(90,70,70)">\n'
        f'          <text style="font-family:\'DM Mono\',monospace;font-size:44px;font-weight:500;fill:#10B981" '
        f'text-anchor="middle" dominant-baseline="middle" x="70" y="66">{score}</text>\n'
        f'          <text style="font-family:\'DM Mono\',monospace;font-size:11px;fill:rgba(255,255,255,.55);letter-spacing:1px" '
        f'text-anchor="middle" dominant-baseline="middle" x="70" y="92">VISIBILITY</text>\n'
        f'        </g>\n      </svg>\n'
        f'      <div class="gauge-label">{short(d)} · {"flat vs" if delta == 0 else f"{delta:+d} vs"} first pull ({short(first["date"])})</div>\n'
        f'    </div>'
    )

    # ---- trajectory table (scales to any number of pulls) -------------
    def arrow(cur, prev):
        if prev is None:
            return '<span style="color:#A0B4C8">—</span>'
        dd = cur - prev
        if dd == 0:
            return '<span style="color:#A0B4C8">0</span>'
        col = "#10B981" if dd > 0 else "#EF4444"
        return f'<span style="color:{col}">{dd:+d}</span>'

    trows = []
    prev = None
    for r in api:
        ra = r["api"]
        sc = ra["visibility_score"]
        trows.append(
            f'<tr><td style="padding-left:14px;font-family:\'DM Mono\',monospace">{pretty(r["date"])}</td>'
            f'<td class="r" style="font-family:\'DM Mono\',monospace;font-weight:600;color:#0B1F3B">{sc}</td>'
            f'<td class="r" style="font-family:\'DM Mono\',monospace">{arrow(sc, prev)}</td>'
            f'<td class="r" style="font-family:\'DM Mono\',monospace;color:#6B8299">{ra["runs"]:,}</td>'
            f'<td class="r" style="font-family:\'DM Mono\',monospace;color:#6B8299">{ra["competitors"].get("Bell","–")}</td>'
            f'<td class="r" style="font-family:\'DM Mono\',monospace;color:#6B8299">{ra["competitors"].get("Rogers","–")}</td></tr>')
        prev = sc
    journey = (
        f'<div class="section" style="margin-top:28px">\n'
        f'  <div class="section-title">Trajectory · every pull since tracking began</div>\n'
        f'  <table class="prompt-table"><thead><tr>'
        f'<th style="padding-left:14px">Pull date</th><th class="r">Telus</th><th class="r">Δ</th>'
        f'<th class="r">Runs (30d)</th><th class="r">Bell</th><th class="r">Rogers</th>'
        f'</tr></thead><tbody>{"".join(trows)}</tbody></table>\n</div>\n\n')

    # ---- current-state stats ------------------------------------------
    live = [v for v in a["prompts"].values() if v is not None]
    strong = sum(1 for v in live if v >= 70)
    weak = sum(1 for v in live if v < 40)
    stats = (
        f'<div class="section">\n  <div class="section-title">Current State · {pretty(d)}</div>\n'
        f'  <div class="stat-row">\n'
        f'    <div class="stat-card good"><div class="stat-num">{score}</div><div class="stat-label">Visibility score (0–100), 30-day window</div>'
        f'<div class="stat-sub">{"Flat" if delta == 0 else f"{delta:+d} pts"} since {short(first["date"])}</div></div>\n'
        f'    <div class="stat-card good"><div class="stat-num">{strong}/{len(live)}</div><div class="stat-label">Tracked queries scoring 70+</div>'
        f'<div class="stat-sub">Reputation prompts lead the set</div></div>\n'
        f'    <div class="stat-card warn"><div class="stat-num">{weak}</div><div class="stat-label">Queries below 40 — all unbranded commercial intent</div>'
        f'<div class="stat-sub">The addressable gap</div></div>\n'
        f'    <div class="stat-card info"><div class="stat-num">{a["citation_totals"]["citations"]:,}</div>'
        f'<div class="stat-label">Citations in the Telus answer space · 30d</div>'
        f'<div class="stat-sub">{a["citation_totals"]["domains"]:,} unique domains</div></div>\n'
        f'  </div>\n</div>\n\n')

    # ---- daily score chart --------------------------------------------
    pts = daily[-30:]
    W, H, ML, MR, MT, MB = 1000, 280, 46, 16, 20, 34
    pw, ph = W - ML - MR, H - MT - MB
    lo, hi = 40, 100
    X = lambda i: ML + (i / max(1, len(pts) - 1)) * pw
    Y = lambda v: MT + (hi - v) / (hi - lo) * ph
    grid = "".join(
        f'<line x1="{ML}" y1="{Y(v):.1f}" x2="{W-MR}" y2="{Y(v):.1f}" stroke="#E6EDF5"/>'
        f'<text x="{ML-10}" y="{Y(v)+4:.1f}" text-anchor="end" font-family="DM Mono" font-size="11" fill="#A0B4C8">{v}</text>'
        for v in (40, 60, 80, 100))
    line = " ".join(("M" if i == 0 else "L") + f"{X(i):.1f} {Y(v):.1f}" for i, (_, v) in enumerate(pts))
    area = f'{line} L {X(len(pts)-1):.1f} {Y(lo):.1f} L {X(0):.1f} {Y(lo):.1f} Z'
    ticks = "".join(
        f'<text x="{X(i):.1f}" y="{H-12}" text-anchor="middle" font-family="DM Mono" font-size="11" fill="#A0B4C8">{dt[5:]}</text>'
        for i, (dt, _) in enumerate(pts) if i % max(1, len(pts)//7) == 0 or i == len(pts)-1)
    dots = "".join(
        f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="3.5" fill="#0066CC"/>'
        for i, (_, v) in enumerate(pts) if v in (min(p[1] for p in pts), max(p[1] for p in pts)) or i == len(pts)-1)
    trend = (
        f'<div class="section">\n  <div class="section-title">Daily Visibility · Last {len(pts)} Days</div>\n'
        f'  <div class="chart-card"><div class="chart-title">Daily visibility score</div>'
        f'<div class="chart-sub">{pts[0][0]} → {pts[-1][0]} · share-of-answer weighted, all five models</div>'
        f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto">'
        f'{grid}<path d="{area}" fill="#0066CC" opacity="0.08"/>'
        f'<path d="{line}" fill="none" stroke="#0066CC" stroke-width="2.5" stroke-linejoin="round"/>{dots}{ticks}</svg></div>\n'
        f'</div>\n\n')

    # ---- prompt table --------------------------------------------------
    scored = sorted(((k, v) for k, v in a["prompts"].items() if v is not None), key=lambda kv: -kv[1])
    def row(k, v):
        c = "#10B981" if v >= 70 else ("#F59E0B" if v >= 40 else "#EF4444")
        return (f'<tr><td style="padding-left:14px"><span class="prompt-text">{esc(label_for(k))}</span></td>'
                f'<td class="r"><span style="color:{c};font-family:\'DM Mono\',monospace;font-weight:600">{v}</span></td>'
                f'<td><div class="src-track" style="margin:0"><div class="src-fill" style="width:{v}%;background:{c}"></div></div></td></tr>')
    divider = ('<tr><td colspan="3" style="padding:4px 14px;background:#F8FAFC;font-size:10px;font-weight:700;'
               'letter-spacing:.1em;text-transform:uppercase;color:#A0B4C8;border-top:1px dashed #D6E4F0;'
               'border-bottom:1px dashed #D6E4F0">↓ Bottom 5 · highest leverage</td></tr>')
    prompts = (
        f'<div class="section">\n  <div class="section-title">Prompt Performance · Top 3 + Bottom 5 · {pretty(d)}</div>\n'
        f'  <table class="prompt-table"><thead><tr><th style="padding-left:14px">Query</th><th class="r">Score (30d)</th>'
        f'<th style="min-width:160px">Score Bar</th></tr></thead><tbody>'
        + "".join(row(k, v) for k, v in scored[:3]) + divider
        + "".join(row(k, v) for k, v in scored[-5:]) + '</tbody></table>\n</div>\n\n')

    # ---- cited sources -------------------------------------------------
    srcs = sorted(a["top_sources"], key=lambda x: -x["citations"])[:10]
    top_c = max(s["citations"] for s in srcs)
    own = ("telus.com", "forum.telus.com")
    rows = "".join(
        f'<div class="src-row">\n'
        f'      <div class="src-domain{" own" if s["domain"] in own else ""}">{s["domain"]}</div>\n'
        f'      <div class="src-track"><div class="src-fill" style="width:{s["citations"]/top_c*100:.0f}%;'
        f'background:{"#0066CC" if s["domain"] in own else "#7EB3E8"}"></div></div>\n'
        f'      <div class="src-count">{s["citations"]:,}</div>\n    </div>' for s in srcs)
    owned_total = sum(s["citations"] for s in a["top_sources"] if s["domain"] in own)
    sources = (
        f'<div class="section">\n  <div class="section-title">Top Cited Sources · Where AI Pulls Telus Information From</div>\n'
        f'  <div class="sources-grid">{rows}</div>\n'
        f'  <div class="insight"><div class="insight-icon">📊</div><div class="insight-text">'
        f'<strong>{srcs[0]["domain"]} leads at {srcs[0]["citations"]:,} citations</strong> (influence {srcs[0]["influence"]}/100). '
        f'Owned properties (telus.com + forum.telus.com) contribute {owned_total:,} of the {a["citation_totals"]["citations"]:,} '
        f'citations in this answer space — the rest is earned or third-party ground.</div></div>\n</div>\n\n')

    s = PAGE.read_text()
    for name, content in (("HERO", hero), ("GAUGE", gauge), ("JOURNEY", journey), ("STATS", stats),
                          ("TREND", trend), ("PROMPTS", prompts), ("SOURCES", sources)):
        s = splice(s, name, content)
    # competitor grid
    ring = sorted(a["competitors"].items(), key=lambda kv: -kv[1])
    cards = "".join(
        f'<div class="comp-card" style="border-top:3px solid {COLORS[i % len(COLORS)]}">\n'
        f'      <div class="comp-rank">#{i+1}</div>\n      <div class="comp-name">{n}</div>\n'
        f'      <div class="comp-score-row"><div class="comp-score-num" style="color:{COLORS[i % len(COLORS)]}">{v}</div>'
        f'<div class="comp-score-label">visibility score / 100</div></div>\n    </div>'
        for i, (n, v) in enumerate(ring))
    # ---- competitor callout (was hand-written and went stale) ----------
    lead = ring[0]
    ratio = score / lead[1] if lead[1] else None
    trailing = ", ".join(f"{n} ({v})" for n, v in ring[1:4])
    comp_insight = (
        f'<div class="insight"><div class="insight-icon">🏁</div><div class="insight-text">'
        f'<strong>Telus at {score} leads the tracked set</strong>'
        + (f' — roughly {ratio:.1f}× the nearest rival, {lead[0]} ({lead[1]}).' if ratio and ratio >= 1.1
           else f', narrowly ahead of {lead[0]} ({lead[1]}).' if ratio and ratio >= 1
           else f', now behind {lead[0]} ({lead[1]}).')
        + f' Behind them: {trailing}. Scores are share-of-answer weighted over the 30 days to {pretty(d)}.'
        f'</div></div>')

    # ---- page stamps ---------------------------------------------------
    win_start = daily[0][0] if daily else d
    window_label = f'{short(win_start)} → {short(d)}'
    title = f'<title>Telus · AI Visibility Scorecard · {pretty(d)}</title>'

    s = splice(s, "COMPS", f'<div class="section-title">Competitor Visibility Scores · 30d · Telus: {score}</div>\n'
                           f'  <div class="comp-grid">{cards}</div>\n  {comp_insight}')
    s = splice(s, "ACTIONS", build_actions(a, d))
    today = datetime.date.today()
    foot = (f"Data through {pretty(d)}" +
            ("" if today.isoformat() == d else f" · page rebuilt {today.strftime('%B %-d, %Y')}"))
    s = splice(s, "FOOT", foot)
    s = splice(s, "TITLE", title)
    s = splice(s, "WINDOW", window_label)
    PAGE.write_text(s)
    print(f"rebuilt scorecard.html → {d}")


if __name__ == "__main__":
    build()
