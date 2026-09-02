#!/usr/bin/env python3
"""Regenerate the live-data regions of scorecard.html from the longitudinal store.

Only the API-derived regions are rebuilt (hero, competitor grid, footer stamp).
The June/July manual-analysis sections — the journey strip, the coverage gauge,
the 7-day daily-trend charts — are a DIFFERENT methodology (coverage % and
average-score-among-mentions) and stay as authored, stamped with their own dates.
"""
import datetime, json, pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent
STORE = REPO / "data" / "longitudinal" / "telus.jsonl"
PAGE = REPO / "scorecard.html"
COLORS = ["#EF4444", "#F59E0B", "#0066CC", "#94A3B8", "#94A3B8", "#94A3B8"]


def splice(src, a, b, content):
    i = src.index(a) + len(a)
    j = src.index(b)
    return src[:i] + content + src[j:]


def pretty(d):
    return datetime.date.fromisoformat(d).strftime("%B %-d, %Y")


def main():
    recs = [json.loads(l) for l in STORE.read_text().splitlines() if l.strip()]
    api = [r for r in recs if "api" in r]
    latest = api[-1]
    a = latest["api"]
    d = latest["date"]
    models = a["models"]
    best = max(models.items(), key=lambda kv: kv[1]["score"])
    worst = min(models.items(), key=lambda kv: kv[1]["score"])
    daily = sorted(a["daily_scores"].items())
    last7 = [v for _, v in daily[-7:]]
    weak = sorted(((k, v) for k, v in a["prompts"].items() if v is not None), key=lambda kv: kv[1])[:4]

    def label(m):
        return m.replace("_", " ").replace("google ", "Google ").title().replace("Ai", "AI")

    hero = (
        f'<div class="hero-eyebrow">30-day tracking window · {a["runs"]:,} runs · 5 AI models · 20 tracked ICP queries</div>\n'
        f'      <div class="hero-headline">Telus AI visibility at <em>{a["visibility_score"]}/100</em> — {a.get("trend","stable")}.</div>\n'
        f'      <div class="hero-sub">Over the 30-day window ending {pretty(d)}, Telus scored <strong>{a["visibility_score"]}/100</strong> '
        f'across <strong>{a["runs"]:,} runs</strong>. {label(best[0])} is the strongest surface (<strong>{best[1]["score"]}</strong>); '
        f'{label(worst[0])} the weakest (<strong>{worst[1]["score"]}</strong>). Daily scores over the last week ran '
        f'{min(last7)}–{max(last7)}. The remaining gaps are all unbranded commercial-intent prompts.</div>'
    )

    ring = sorted(a["competitors"].items(), key=lambda kv: -kv[1])
    cards = "".join(
        f'<div class="comp-card" style="border-top:3px solid {COLORS[i % len(COLORS)]}">\n'
        f'      <div class="comp-rank">#{i+1}</div>\n'
        f'      <div class="comp-name">{n}</div>\n'
        f'      <div class="comp-score-row"><div class="comp-score-num" style="color:{COLORS[i % len(COLORS)]}">{v}</div>'
        f'<div class="comp-score-label">visibility score / 100</div></div>\n    </div>'
        for i, (n, v) in enumerate(ring))
    comps = (f'<div class="section-title">Competitor Visibility Scores · 30d · Telus: {a["visibility_score"]}</div>\n'
             f'  <div class="comp-grid">{cards}</div>')

    s = PAGE.read_text()
    s = splice(s, "<!-- HERO:START -->", "<!-- HERO:END -->", hero)
    s = splice(s, "<!-- COMPS:START -->", "<!-- COMPS:END -->", comps)
    s = splice(s, "<!-- FOOT:START -->", "<!-- FOOT:END -->", f"Compiled {pretty(d)}")
    PAGE.write_text(s)
    print(f"rebuilt scorecard.html → {d}")


if __name__ == "__main__":
    main()
