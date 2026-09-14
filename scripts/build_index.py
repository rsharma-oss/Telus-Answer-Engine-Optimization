#!/usr/bin/env python3
"""Regenerate the data-driven regions of index.html from the longitudinal store.

Idempotent; run after every pull. Only the marked regions change — the deliverable
and archive cards stay hand-authored.
"""
import datetime, json, pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent
STORE = REPO / "data" / "longitudinal" / "telus.jsonl"
PAGE = REPO / "index.html"


def splice(src, a, b, content):
    if a not in src or b not in src:
        return src  # marker retired — skip silently rather than break the weekly job
    i = src.index(a) + len(a)
    j = src.index(b)
    return src[:i] + content + src[j:]


def pretty(d):
    return datetime.date.fromisoformat(d).strftime("%B %-d, %Y")


def main():
    recs = [json.loads(l) for l in STORE.read_text().splitlines() if l.strip()]
    api = [r for r in recs if "api" in r]
    latest, first = api[-1], api[0]
    a = latest["api"]
    d = latest["date"]

    trend = a.get("trend", "stable")
    delta = a["visibility_score"] - first["api"]["visibility_score"]
    move = ("holding flat" if delta == 0 else
            f"{'up' if delta > 0 else 'down'} {abs(delta)} point{'s' if abs(delta) != 1 else ''} since tracking began")

    hero = (f'Ongoing AI visibility tracking for Telus across <strong>5 AI models</strong> and '
            f'<strong>20 ICP queries</strong>. Current headline (30d, as of {pretty(d)}): visibility '
            f'<strong>{a["visibility_score"]}/100</strong> over <strong>{a["runs"]:,} runs</strong> — '
            f'{trend}, {move}. {len(api)} pulls on record since {pretty(first["date"])}.')

    # The store is the live source; the dated markdown is only the original snapshot.
    mds = sorted((REPO / "data").glob("visibility-data-*.md"))
    md_note = ""
    if mds:
        md_date = mds[-1].stem.replace("visibility-data-", "")
        # Plain span — the whole card is already an <a>, and HTML5 forbids nested anchors.
        md_note = (f' The first dated snapshot (<span style="color:#10B981;font-weight:600">'
                   f'{pretty(md_date)}</span>) is kept for reference.')
    card = (f'<a class="link-card" href="data/longitudinal/telus.jsonl">\n'
            f'      <div class="link-kicker">DATA</div>\n'
            f'      <div class="link-title">Tracking store · {len(api)} pulls to {pretty(d)}</div>\n'
            f'      <div class="link-body">Append-only machine-readable record of every pull — scores, per-model '
            f'breakdown, prompt matrix, competitors and citations. Every page on this site is generated from it.'
            f'{md_note}</div>\n    </a>')

    # Stat strip tiles — regenerated from the same source as the hero.
    models = a.get("models", {})
    surface_labels = {"chatgpt": "ChatGPT", "gemini": "Gemini", "perplexity": "Perplexity",
                      "google_ai_overview": "Google AIO", "google_ai_mode": "Google AI Mode"}
    if models:
        top_key = max(models, key=lambda k: models[k].get("score", 0))
        top_label = surface_labels.get(top_key, top_key)
        top_score = models[top_key].get("score", 0)
        runs_sub = f"{len(models)} surfaces · {top_label} strongest at {top_score}"
    else:
        runs_sub = "5 surfaces tracked"
    latest_short = datetime.date.fromisoformat(d).strftime("%b %-d")
    stat = (
        f'\n  <div class="stat-tile"><div class="v">{a["visibility_score"]}<small>/100</small></div>'
        f'<div class="l">AI Visibility · 30d</div>'
        f'<div class="s">{trend}, {move.replace("since tracking began", "since tracking began Jul 17")}</div></div>\n'
        f'  <div class="stat-tile"><div class="v">{a["runs"]:,}</div>'
        f'<div class="l">Model runs · 30d</div>'
        f'<div class="s">{runs_sub}</div></div>\n'
        f'  <div class="stat-tile"><div class="v">{len(api)}</div>'
        f'<div class="l">Consecutive weekly pulls</div>'
        f'<div class="s">automated Monday cadence · {latest_short} latest</div></div>\n'
    )

    s = PAGE.read_text()
    s = splice(s, "<!-- HERO:START -->", "<!-- HERO:END -->", hero)
    s = splice(s, "<!-- STAT:START -->", "<!-- STAT:END -->", stat)
    s = splice(s, "<!-- STAMP:START -->", "<!-- STAMP:END -->",
               f"Tracked since June 2026 · updated {pretty(d)}")
    today = datetime.date.today()
    foot = f"Data through {pretty(d)}" + ("" if today.isoformat() == d else f" · page rebuilt {today.strftime('%B %-d, %Y')}")
    s = splice(s, "<!-- FOOT:START -->", "<!-- FOOT:END -->", foot)
    s = splice(s, "<!-- DATACARD:START -->", "<!-- DATACARD:END -->", card)
    PAGE.write_text(s)
    print(f"rebuilt index.html → {d}")


if __name__ == "__main__":
    main()
