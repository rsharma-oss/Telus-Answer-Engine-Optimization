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

    # newest dated markdown pull, if any; otherwise point at the store itself
    mds = sorted((REPO / "data").glob("visibility-data-*.md"))
    if mds:
        href, label, body = (f"data/{mds[-1].name}",
                             f'Latest data pull · {pretty(mds[-1].stem.replace("visibility-data-", ""))}',
                             "Raw dated snapshot from our AI visibility tracking API. Prior pulls accumulate in this folder with each cycle.")
    else:
        href, label, body = ("data/longitudinal/telus.jsonl", "Tracking store · JSONL",
                             "Append-only record of every pull.")
    card = (f'<a class="link-card" href="{href}">\n'
            f'      <div class="link-kicker">DATA</div>\n'
            f'      <div class="link-title">{label}</div>\n'
            f'      <div class="link-body">{body} Machine-readable store: '
            f'<code>data/longitudinal/telus.jsonl</code> ({len(api)} pulls).</div>\n    </a>')

    s = PAGE.read_text()
    s = splice(s, "<!-- HERO:START -->", "<!-- HERO:END -->", hero)
    s = splice(s, "<!-- STAMP:START -->", "<!-- STAMP:END -->",
               f"Tracked since June 2026 · updated {pretty(d)}")
    s = splice(s, "<!-- FOOT:START -->", "<!-- FOOT:END -->", f"Updated {pretty(d)}")
    s = splice(s, "<!-- DATACARD:START -->", "<!-- DATACARD:END -->", card)
    PAGE.write_text(s)
    print(f"rebuilt index.html → {d}")


if __name__ == "__main__":
    main()
