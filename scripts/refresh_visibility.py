#!/usr/bin/env python3
"""Weekly AI-visibility pull → append one dated record to data/longitudinal/<brand>.jsonl.

Talks JSON-RPC (MCP protocol, stateless streamable-HTTP) to the tracking
platform's endpoint. Reads config from ~/.config/aeo-tracker/config.json
(NEVER committed — keep keys out of this public repo). Expected shape:

{
  "api_base": "https://<tracking-platform-host>/api/mcp",
  "api_key": "<key>",
  "auth_header": "Authorization",
  "auth_prefix": "Bearer ",
  "brands": { "telus": "<brand-uuid>" }
}

Usage:
  python3 scripts/refresh_visibility.py --brand telus
  python3 scripts/refresh_visibility.py --brand telus --dry-run
"""
import argparse, datetime, json, pathlib, re, ssl, subprocess, sys, urllib.error, urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
CONFIG_PATH = pathlib.Path.home() / ".config" / "aeo-tracker" / "config.json"
GIT_AUTHOR = ["-c", "user.name=Rahul Sharma", "-c", "user.email=rahul@growthautomated.ai"]


def git_autopush(rel_path, date_str):
    """Commit + push the appended record. Failure is non-fatal — the record
    is already on disk; the next successful run (or a work session) pushes it."""
    try:
        subprocess.run(["git", "add", rel_path], cwd=REPO, check=True, capture_output=True)
        diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO)
        if diff.returncode == 0:
            return  # nothing staged
        subprocess.run(["git", *GIT_AUTHOR, "commit", "-m",
                        f"Longitudinal record {date_str} (automated weekly pull)"],
                       cwd=REPO, check=True, capture_output=True)
        subprocess.run(["git", "push"], cwd=REPO, check=True, capture_output=True, timeout=120)
        print(f"pushed {date_str} record to origin")
    except Exception as e:
        print(f"WARNING: auto-push failed ({e}) — record saved locally; will ride the next push", file=sys.stderr)


# Full path to npx — LaunchAgents get a minimal PATH; wrangler ships via npx.
_NPX = "/usr/local/bin/npx"

def cloudflare_deploy():
    """Push the current asset tree to the Cloudflare Static Assets Worker
    (telus-aeo). Uses OAuth credentials from `~/.wrangler/config/` set up
    by an interactive `wrangler login`. Non-fatal on failure — the source
    is still safe in git; the operator can re-deploy by hand."""
    try:
        # Ensure node/npx can find each other under launchd's minimal PATH.
        env = {**__import__("os").environ, "PATH":
               "/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin"}
        r = subprocess.run(
            [_NPX, "wrangler", "deploy"],
            cwd=REPO, env=env, capture_output=True, text=True, timeout=180,
        )
        if r.returncode == 0:
            # Last line of wrangler output is the Version ID line.
            tail = "\n".join(r.stdout.strip().splitlines()[-3:])
            print(f"cloudflare deploy ok\n{tail}")
        else:
            print(f"WARNING: cloudflare deploy failed (rc={r.returncode})\n"
                  f"stdout:\n{r.stdout}\nstderr:\n{r.stderr}", file=sys.stderr)
    except Exception as e:
        print(f"WARNING: cloudflare deploy raised ({e}) — GitHub push already "
              f"succeeded; re-run `npx wrangler deploy` manually to sync",
              file=sys.stderr)


# ------------- Weekly archive stamping (TELUS only) -------------
# Every Monday: copy the current exec PDFs into /archive/{name}-{yyyy-mm-dd}.pdf
# so the URL is frozen for future reference, and prepend a row to /history.html.
# Idempotent — safe to re-run.
EXEC_PDFS = [
    ("katherine-smb.pdf",       "Katherine · SMB read",   "President, TELUS SMB"),
    ("kevin-cmo.pdf",           "Kevin · Brand narrative","Chief Marketing Officer"),
    ("david-telco.pdf",         "David · Telco Division", "President, Telco Division"),
    ("kim-channels.pdf",        "Kim · Channel-specific", "VP, Digital & Channels"),
    ("rob-consumer-marcom.pdf", "Rob · Consumer Marcom",  "Director, Consumer Marcom"),
    ("jacob-organic.pdf",       "Jacob · Organic Ops",    "Head of Organic"),
]

# Per-exec slug-substring filters used to pick WoW movers that resonate with
# that audience. None = brand-wide (pick the biggest absolute movers overall).
# If the filter yields fewer than 3 movers, we top it up with brand-wide movers.
AUDIENCE_FILTERS = {
    "kevin-cmo":           None,
    "katherine-smb":       ["small-business", "business-owner", "cost-effective", "unlimited", "flexible"],
    "david-telco":         None,
    "kim-channels":        ["bundle", "flexible", "bell", "5g", "sign-up"],
    "rob-consumer-marcom": ["reliability", "outages", "fee", "flexible", "families", "satisfaction"],
    "jacob-organic":       ["bundle", "5g", "small-business", "flexible", "satisfaction"],
}


def stamp_archive(record_date):
    """Copy current exec PDFs to /archive/{name}-{date}.pdf, once per date per file.
    Returns the list of files freshly stamped this run."""
    import shutil
    archive_dir = REPO / "archive"
    archive_dir.mkdir(exist_ok=True)
    stamped = []
    for src_name, _, _ in EXEC_PDFS:
        src = REPO / src_name
        if not src.exists():
            print(f"  [archive] skip {src_name} (not on disk)")
            continue
        dst = archive_dir / f"{src_name[:-4]}-{record_date}.pdf"
        if dst.exists():
            print(f"  [archive] archive/{dst.name} already present (idempotent)")
            continue
        shutil.copy2(src, dst)
        stamped.append(dst.name)
        print(f"  [archive] stamped {dst.name}")
    return stamped


def insert_history_row(record_date, api_snapshot):
    """Prepend a new week card to history.html between WEEKS markers.
    Only touches the marker region; existing cards are preserved.
    Idempotent — a card for this date won't be inserted twice."""
    history = REPO / "history.html"
    if not history.exists():
        print("  [archive] history.html missing — skipping row insert")
        return
    src = history.read_text()
    start_tag = "<!-- WEEKS:START -->"
    end_tag = "<!-- WEEKS:END -->"
    if start_tag not in src or end_tag not in src:
        print("  [archive] history.html WEEKS markers missing — skipping")
        return
    # Already have a row for this date? Idempotent guard.
    if f"katherine-smb-{record_date}.pdf" in src:
        print(f"  [archive] history.html already has row for {record_date}")
        return

    # Derive week number from the highest existing "<!-- WEEK N -->" marker.
    # More robust than counting DOM matches (which false-match .wk-note, .wk-head).
    existing = [int(m) for m in re.findall(r'<!-- WEEK (\d+) -->', src)]
    week_num = (max(existing) if existing else 0) + 1

    parts = record_date.split("-")
    months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    pretty = f"{months[int(parts[1]) - 1]} {int(parts[2])}, {parts[0]}"

    score = api_snapshot.get("visibility_score", "?")
    runs = api_snapshot.get("runs", "?")

    pdf_rows = []
    for src_name, label, role in EXEC_PDFS:
        rel = f"archive/{src_name[:-4]}-{record_date}.pdf"
        if not (REPO / rel).exists():
            continue
        pdf_rows.append(
            f'      <a class="pdf-row" href="{rel}" target="_blank">'
            f'<span class="name">{label}<small>{role}</small></span>'
            f'<span class="kind">PDF</span></a>'
        )
    pdfs_html = "\n".join(pdf_rows) if pdf_rows else "      <em>No exec PDFs on disk this week.</em>"

    new_card = (
        f'<!-- WEEK {week_num} -->\n'
        f'<div class="wk">\n'
        f'  <div class="wk-head">\n'
        f'    <div class="wk-h-l">\n'
        f'      <div class="wk-tag">Week {week_num} &middot; Latest</div>\n'
        f'      <div class="wk-date">{pretty}</div>\n'
        f'    </div>\n'
        f'    <div class="wk-h-r">Auto-stamped by Monday refresh</div>\n'
        f'  </div>\n'
        f'  <div class="wk-body">\n'
        f'    <p class="wk-note"><strong>Panel-wide TELUS at {score}/100</strong> ({runs} runs this pull &middot; week {week_num} of the tracked engagement). '
        f'<em>WoW insights analysis pending — request the weekly walkthrough or open a PDF below.</em></p>\n'
        f'    <div class="pdfs">\n{pdfs_html}\n    </div>\n'
        f'  </div>\n'
        f'</div>\n\n'
    )

    # Downgrade any prior "· Latest" tag so only the newest week wears it.
    src = re.sub(r'class="wk-tag">Week (\d+) &middot; Latest</div>',
                 r'class="wk-tag">Week \1</div>', src)

    idx = src.index(start_tag) + len(start_tag) + 1  # newline after marker
    history.write_text(src[:idx] + new_card + src[idx:])
    print(f"  [archive] inserted Week {week_num} row into history.html")


SOURCES_TARGETS = ["kevin-cmo.html", "rob-consumer-marcom.html", "jacob-organic.html"]


def splice_sources(cfg, brand_id, record_date, ctx):
    """Pull top-6 citation sources (30d), compute WoW deltas against the prior
    stored snapshot, and splice the HTML between SOURCES markers in each exec
    PDF that carries them. Snapshots are append-only in
    data/longitudinal/sources-telus.jsonl so WoW deltas are reproducible.
    First run writes a baseline with no deltas."""
    try:
        # Pull wider than 6 — the API orders by influenceScore; we re-rank by
        # citationCount so the strip reflects actual share of citation volume.
        api = call_tool(cfg, "list_top_sources",
                        {"brandId": brand_id, "days": 30, "limit": 25}, ctx)
    except SystemExit:
        print("  [sources] list_top_sources failed — skipping splice", file=sys.stderr)
        return
    rows = api.get("sources") or api.get("topSources") or []
    if not rows:
        print("  [sources] API returned no rows — skipping splice")
        return

    # Share denominator is the full-window total citations, not just the
    # top-25 we fetched — the API returns it in totals.totalCitations.
    totals = api.get("totals") or {}
    denom = totals.get("totalCitations") or sum(r.get("citationCount", 0) for r in rows) or 1
    top6 = sorted(rows, key=lambda r: r.get("citationCount", 0), reverse=True)[:6]
    current = []
    for r in top6:
        current.append({
            "domain": r.get("domain", "unknown"),
            "citations": r.get("citationCount", 0),
            "share": round(100 * r.get("citationCount", 0) / denom, 2),
            "ownership": r.get("ownership", "thirdParty"),
        })

    store = REPO / "data" / "longitudinal" / "sources-telus.jsonl"
    store.parent.mkdir(parents=True, exist_ok=True)
    prior = {}
    if store.exists():
        for line in store.read_text().splitlines():
            if not line.strip():
                continue
            prev = json.loads(line)
            if prev["date"] == record_date:
                print(f"  [sources] snapshot for {record_date} already stored — reusing")
                continue
            prior = {s["domain"]: s["share"] for s in prev["sources"]}

    # Idempotency: append only if today's record isn't already there.
    already = False
    if store.exists():
        for line in store.read_text().splitlines():
            if line.strip() and json.loads(line)["date"] == record_date:
                already = True
                break
    if not already:
        with store.open("a") as f:
            f.write(json.dumps({"date": record_date, "sources": current},
                               separators=(",", ":")) + "\n")
        print(f"  [sources] snapshot stored for {record_date} ({len(current)} rows)")

    html_rows = []
    for s in current:
        klass = {"you": "own", "competitor": "comp"}.get(s["ownership"], "")
        delta_html = ""
        if s["domain"] in prior:
            d = round(s["share"] - prior[s["domain"]], 1)
            if d > 0.1:
                delta_html = f'<span class="src-wow up">+{d:.1f}pp</span>'
            elif d < -0.1:
                delta_html = f'<span class="src-wow down">{d:.1f}pp</span>'
            else:
                delta_html = '<span class="src-wow flat">flat</span>'
        else:
            delta_html = '<span class="src-wow flat">new</span>'
        bar_pct = min(100, round(s["share"] * 10))  # 10% share = full bar
        html_rows.append(
            f'<div class="src-row {klass}">'
            f'<span class="src-dom">{s["domain"]}</span>'
            f'<span class="src-bar"><span style="width:{bar_pct}%"></span></span>'
            f'<span class="src-pct">{s["share"]:.1f}%</span>'
            f'{delta_html}'
            f'</div>'
        )
    block = "".join(html_rows)

    for name in SOURCES_TARGETS:
        path = REPO / name
        if not path.exists():
            print(f"  [sources] {name} not on disk — skipping")
            continue
        splice(path, "<!-- SOURCES:START -->", "<!-- SOURCES:END -->", block)
        print(f"  [sources] spliced top-{len(current)} into {name}")


# ---------------- Weekly exec-band refresh (TELUS only) ----------------
# After the sources splice, each exec HTML needs:
#   - version chip bumped (v.YYYY-MM-DD)
#   - "N weekly pulls on record" bumped
#   - "ending {prev month day}" → "ending {this month day}"
#   - WoW band replaced with real Sep→Oct 5-style movers from the matrix
# Then re-render all 6 PDFs via Chrome headless. Called before stamp_archive
# so the frozen /archive/{name}-{date}.pdf carries the current week's content.
_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
_MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]


def _pretty_date(iso):
    """2026-10-05 → ('October 5', 'OCT 5')"""
    y, m, d = (int(x) for x in iso.split("-"))
    full_months = ["January","February","March","April","May","June",
                   "July","August","September","October","November","December"]
    return (f"{full_months[m-1]} {d}", f"{_MONTHS[m-1].upper()} {d}")


def _pick_movers(curr_matrix, prev_matrix, slug_substrings, k=3):
    """Return the top-k absolute movers (slug, prev, curr, delta) where delta != 0.
    If slug_substrings is set, prefer slugs matching any of them; fill with
    brand-wide movers if the filter is too narrow."""
    all_m = []
    for slug, data in curr_matrix.items():
        c = data.get("overall")
        p = (prev_matrix.get(slug) or {}).get("overall")
        if c is None or p is None or c == p:
            continue
        all_m.append((slug, p, c, c - p))
    all_m.sort(key=lambda t: abs(t[3]), reverse=True)
    if slug_substrings:
        focused = [t for t in all_m if any(s in t[0] for s in slug_substrings)]
        picked = focused[:k]
        if len(picked) < k:
            seen = {t[0] for t in picked}
            picked += [t for t in all_m if t[0] not in seen][: k - len(picked)]
        return picked
    return all_m[:k]


def _slug_to_label(slug):
    """Reverse the slug() transform into a plain label — truncated for the band.
    Prefers short, direct labels; falls back to the raw slug if nothing better."""
    # Known rewrites for the most common prompt shapes — keeps the band readable.
    rewrites = {
        "my-small-business-needs-a-cost-effective":  "SMB cost-effective wireless",
        "are-there-flexible-mobile-data-plans-i-c":  "Flexible mobile data",
        "sign-up-for-2026-bundle-deal-phone-plans":  "2026 bundle deal",
        "considering-bell-versus-another-provider":  "5G vs Bell",
        "how-do-people-feel-about-activation-and-":  "Activation-fee sentiment",
        "i-m-tired-of-service-outages-with-my-cur":  "Service-outages reliability",
        "has-anyone-been-disappointed-with-telus-":  "TELUS satisfaction",
        "who-feels-that-telus-provides-the-best-v":  "Business-owner satisfaction",
        "which-provider-has-the-best-family-unlim":  "Family unlimited data",
        "for-those-who-ve-recently-tried-telus-5g":  "TELUS 5G experience",
        "what-do-most-families-do-when-they-find-":  "Family-plan affordability",
        "buy-best-wireline-solution-for-my-home-o":  "Wireline home office",
        "what-s-the-difference-in-service-quality":  "Urban/rural service quality",
        "i-m-moving-to-canada-in-2026-and-need-a-":  "Moving to Canada wireless",
        "has-anyone-experienced-unexpected-fees-w":  "Unexpected-fees sentiment",
        "what-do-business-owners-think-about-usin": "Business-owner TELUS use",
    }
    for prefix, label in rewrites.items():
        if slug.startswith(prefix):
            return label
    # Fallback: first ~5 words, title-cased.
    words = slug.replace("-", " ").split()[:5]
    return " ".join(w.capitalize() for w in words)


def _wow_rows_html(movers):
    out = []
    for slug, prev, curr, delta in movers:
        label = _slug_to_label(slug)
        if delta > 0:
            arrow, klass, note = "▲", "up",   f"+{delta}pp"
        elif delta < 0:
            arrow, klass, note = "▼", "down", f"{delta}pp"
        else:
            continue
        out.append(
            f'<div class="wow-row {klass}"><span class="wow-arrow">{arrow}</span>'
            f'<span class="wow-label"><b>{label}</b> {prev} → {curr}</span>'
            f'<span class="wow-note">{note}</span></div>'
        )
    return "".join(out)


def _wow_headline(score, prev_score, top_mover):
    """Deterministic data-only headline — always the fallback if the editorial
    (Claude) path can't produce one. Pure math on the inputs; no narrative."""
    delta = score - prev_score
    if delta > 0:
        trend = f"up {delta} from {prev_score}"
    elif delta < 0:
        trend = f"down {abs(delta)} from {prev_score}"
    else:
        trend = f"held at {prev_score}"
    if top_mover:
        tag = f"Biggest mover: {_slug_to_label(top_mover[0])} {top_mover[1]} → {top_mover[2]}."
    else:
        tag = "No prompt moved materially this week."
    return f"Panel-wide {score}/100 ({trend}). {tag}"


# ---------------- Editorial headlines via Claude Messages API ----------------
# Each Monday we ask Claude for ONE sentence per exec that reads in operating
# voice (not marketing), uses only the numbers in the payload, and names the
# business signal — not a superlative. Falls back to the deterministic
# _wow_headline() on any failure (missing key, network, empty response, etc.)
# so the Monday run never dies on this step.

_CLAUDE_VOICE = (
    "You write one-sentence weekly-brief headlines for a Growth Automated client "
    "exec PDF (TELUS). Operating voice, measurement over marketing. Rules you "
    "MUST obey, every time:\n"
    "- Exactly one sentence, maximum 180 characters, no line breaks.\n"
    "- Lead with the number: panel-wide score and the week-over-week delta.\n"
    "- Then name the single biggest business signal using ONLY the numbers in "
    "the payload — do not invent any number, percentage, or comparison that "
    "isn't in the data.\n"
    "- No superlatives (banned words: unprecedented, historic, revolutionary, "
    "massive, huge, dramatic, record-breaking, game-changing).\n"
    "- Reference TELUS by name only when the move is TELUS-specific; otherwise "
    "say 'panel-wide'.\n"
    "- Return the sentence as plain text, no quotes, no preamble, no markdown."
)

_EXEC_LENS = {
    "kevin-cmo":           "Chief Marketing Officer — brand narrative, category-answer story",
    "katherine-smb":       "President, TELUS SMB — small-business read, SMB wireless + SMB value",
    "david-telco":         "President, Telco Division — top-line + direction, gains and reversals",
    "kim-channels":        "VP, Digital & Channels — channel-signal lens, bundles, flex-data, direct-comparison intents",
    "rob-consumer-marcom": "Director, Consumer Marcom — consumer-brand lanes, reliability, families, service experience",
    "jacob-organic":       "Head of Organic — organic-surface read, SEO + content lanes, mobile category",
}


def _claude_headline(exec_base, score, prev_score, movers, prev_date, record_date):
    """Call Anthropic Messages API for one editorial headline PROPOSAL. These
    proposals are written to a review file for operator approval — they are
    NEVER spliced into exec HTMLs directly by the Monday run (governance:
    editorial sign-off is Rahul's value-add, not Claude's). Returns the
    sentence string on success, or None on failure.
    API key from cfg['anthropic_api_key'] or env ANTHROPIC_API_KEY."""
    import os
    key = (CFG_CACHE.get("anthropic_api_key") if isinstance(CFG_CACHE, dict) else None) \
          or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    delta = score - prev_score
    mover_lines = "\n".join(
        f"- {_slug_to_label(s)}: {p} → {c} ({'+' if d>0 else ''}{d}pp)"
        for s, p, c, d in movers
    ) or "- (no prompt moved materially)"
    user = (
        f"EXEC: {_EXEC_LENS.get(exec_base, exec_base)}\n"
        f"WINDOW: 7-day pulls, {prev_date} → {record_date}\n"
        f"PANEL-WIDE: {score}/100 (prior week: {prev_score}, delta {'+' if delta>=0 else ''}{delta}pp)\n"
        f"TOP MOVERS this week:\n{mover_lines}\n\n"
        f"Write the one-sentence headline per the rules."
    )
    body = json.dumps({
        "model": "claude-sonnet-5",
        "max_tokens": 160,
        "system": _CLAUDE_VOICE,
        "messages": [{"role": "user", "content": user}],
    }).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages",
                                 data=body, method="POST")
    req.add_header("content-type", "application/json")
    req.add_header("anthropic-version", "2023-06-01")
    req.add_header("x-api-key", key)
    try:
        ctx = ssl.create_default_context(cafile="/etc/ssl/cert.pem")
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            res = json.loads(r.read().decode())
        text = (res.get("content") or [{}])[0].get("text", "").strip()
        if not text:
            return None
        # One-sentence guardrail — if Claude returned several, keep the first.
        text = text.splitlines()[0].strip().strip('"').strip()
        if len(text) > 240:
            return None  # suspiciously long — fall back
        return text
    except Exception as e:
        print(f"  [exec] claude headline failed for {exec_base} ({e}) — "
              f"falling back to data-only headline", file=sys.stderr)
        return None


# Lazy cache for the config dict — populated at main() start — so the Claude
# helper can reach the API key without threading cfg through every call site.
CFG_CACHE = None


def write_editorial_proposals(record_date, store_path):
    """Write a review file with Claude-proposed editorial headlines per exec,
    alongside the data-only headlines the Monday run actually published. The
    file is for Rahul's governance step: he reads it, edits as he likes, then
    runs scripts/apply_editorial.py to swap the editorial headlines into the
    live HTMLs + re-render PDFs + re-stamp archive + re-deploy.

    No side effects on the published artifacts — this is a WRITE-ONLY proposal."""
    recs = [json.loads(l) for l in store_path.read_text().splitlines() if l.strip()]
    recs = [r for r in recs if "api" in r]
    prior = [r for r in recs if r["date"] < record_date]
    if not prior:
        print("  [editorial] no prior record — skipping proposal (first run)")
        return None
    prev = prior[-1]
    prev_date = prev["date"]
    prev_score = prev["api"]["visibility_score"]
    matrix_prev = prev["api"].get("prompt_matrix_7d", {})
    this = next(r for r in recs if r["date"] == record_date)
    score = this["api"]["visibility_score"]
    matrix_curr = this["api"].get("prompt_matrix_7d", {})

    proposals_dir = REPO / "data" / "editorial-proposals"
    proposals_dir.mkdir(parents=True, exist_ok=True)
    out = proposals_dir / f"{record_date}.md"

    lines = [
        f"# Weekly editorial proposal · {record_date}",
        "",
        f"Panel-wide this week: **{score}/100** "
        f"({'+' if score-prev_score>=0 else ''}{score-prev_score}pp vs {prev_date}).",
        "",
        "**Governance:** Monday's auto-run published data-only headlines "
        "(deterministic, no narrative). The proposals below are Claude's "
        "editorial drafts for your review. To ship an edit, run:",
        "",
        f"```bash",
        f"python3 scripts/apply_editorial.py --date {record_date}",
        f"```",
        "",
        "Edit any `editorial:` line inline (the line that follows is what "
        "ships). Lines starting with `#` are ignored. Leaving a block blank "
        "or deleting the editorial line will leave the data-only headline "
        "in place for that exec.",
        "",
        "---",
        "",
    ]

    for pdf_name, label, _ in EXEC_PDFS:
        base = pdf_name[:-4]
        movers = _pick_movers(matrix_curr, matrix_prev,
                              AUDIENCE_FILTERS.get(base), k=3)
        data_only = _wow_headline(score, prev_score, movers[0] if movers else None)
        proposal = _claude_headline(base, score, prev_score, movers,
                                     prev_date, record_date)
        lines += [
            f"## {base} — {label}",
            "",
            f"**Audience filter:** `{AUDIENCE_FILTERS.get(base) or 'brand-wide'}`",
            "",
            "**Top movers this week:**",
        ]
        for s, p, c, d in movers:
            arrow = "▲" if d > 0 else "▼"
            lines.append(f"- {arrow} {_slug_to_label(s)}: {p} → {c} "
                         f"({'+' if d>0 else ''}{d}pp)")
        lines += [
            "",
            f"**Data-only (what shipped Monday):**",
            f"> {data_only}",
            "",
            f"**editorial:** {proposal or '(Claude headline unavailable — using data-only above)'}",
            "",
            "---",
            "",
        ]
    out.write_text("\n".join(lines))
    print(f"  [editorial] wrote proposal → {out}")
    return out


def _patch_exec_html(path, record_date, prev_date, pulls, score, prev_score,
                     matrix_curr, matrix_prev, audience_filter):
    """Idempotent patch of one exec HTML — safe to re-run."""
    src = path.read_text()
    # 0) Defend against stacked-band drift. On the Oct 5 run, Rob + Jacob had
    # two <div class="wow-band"> blocks (new Week N on top of stale Week N-1)
    # because an older patch left the prior band in place. Collapse any such
    # duplicates by keeping only the FIRST wow-band and discarding the rest.
    bands = [m.start() for m in re.finditer(r'<div class="wow-band">', src)]
    if len(bands) > 1:
        # Remove each extra wow-band using balanced-div depth tracking.
        for start in reversed(bands[1:]):
            depth, end = 0, start
            for m in re.finditer(r'<div\b|</div>', src[start:]):
                depth += 1 if m.group().startswith("<div") else -1
                if depth == 0:
                    end = start + m.end()
                    break
            while end < len(src) and src[end] in "\n\r\t ":
                end += 1
            src = src[:start] + src[end:]
        print(f"  [exec] {path.name}: collapsed {len(bands)-1} stale wow-band(s)")
    # 1) Version chip.
    src = re.sub(r'chip">v\.\d{4}-\d{2}-\d{2}', f'chip">v.{record_date}', src)
    # 2) Pull count — handle any prior "N weekly pulls on record".
    src = re.sub(r'\d+ weekly pulls on record',
                 f"{pulls} weekly pulls on record", src)
    # 3) Date references — "ending {prev-month day}" → "ending {this-month day}".
    this_long, this_short = _pretty_date(record_date)
    prev_long, prev_short = _pretty_date(prev_date)
    src = src.replace(f"ending {prev_long}", f"ending {this_long}")
    # 4) WoW band — pick movers, build headline + rows, splice in place.
    movers = _pick_movers(matrix_curr, matrix_prev, audience_filter, k=3)
    if not movers:
        print(f"  [exec] {path.name}: no movers found, leaving WoW band as-is")
        return False
    top = movers[0]
    headline = _wow_headline(score, prev_score, top)
    rows_html = _wow_rows_html(movers)
    tag_span = f"WEEK {pulls} &middot; WHAT SHIFTED &middot; {prev_short} – {this_short}"
    pattern = re.compile(
        r'(<div class="wow-tag">)WEEK \d+[^<]*(</div>\s*)'
        r'<div class="wow-h">[^<]*</div>\s*'
        r'(</div>\s*)'
        r'<div class="wow-r">.*?</div></div>',
        re.DOTALL,
    )
    repl = (f'\\g<1>{tag_span}\\g<2>'
            f'<div class="wow-h">{headline}</div>'
            f'\\g<3>'
            f'<div class="wow-r">{rows_html}</div>')
    new_src, n = pattern.subn(repl, src, count=1)
    if n == 0:
        print(f"  [exec] {path.name}: WARNING — WoW pattern not matched")
    else:
        src = new_src
    path.write_text(src)
    return n > 0


def _render_exec_pdf(basename):
    """Render one exec HTML to its sibling PDF via Chrome headless. file:// URL
    resolves relative /assets/scorecard-ga.css correctly."""
    html = REPO / f"{basename}.html"
    pdf = REPO / f"{basename}.pdf"
    r = subprocess.run(
        [_CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer",
         f"--print-to-pdf={pdf}", f"file://{html}"],
        capture_output=True, text=True, timeout=60,
    )
    # Chrome prints "N bytes written to file ..." on success (stdout or stderr).
    msg = (r.stdout + r.stderr).splitlines()
    hit = next((l for l in msg if "bytes written" in l), None)
    return hit


def refresh_exec_bands(record_date, score, store_path):
    """Patch all 6 TELUS exec HTMLs with Oct-5-style version/pulls/dates/WoW
    and re-render each PDF. Must run BEFORE stamp_archive so the frozen
    /archive/{name}-{date}.pdf copies carry the current week's numbers.
    Returns the list of (basename.pdf) that this run actually re-rendered."""
    # Pull the prior week's record from the store to compute WoW deltas.
    recs = [json.loads(l) for l in store_path.read_text().splitlines() if l.strip()]
    recs = [r for r in recs if "api" in r]
    pulls = len(recs)
    prior = [r for r in recs if r["date"] < record_date]
    if not prior:
        print("  [exec] no prior record — skipping exec patch (first run)")
        return []
    prev = prior[-1]
    prev_date = prev["date"]
    prev_score = prev["api"]["visibility_score"]
    matrix_prev = prev["api"].get("prompt_matrix_7d", {})
    this = next(r for r in recs if r["date"] == record_date)
    matrix_curr = this["api"].get("prompt_matrix_7d", {})

    rendered = []
    for pdf_name, _, _ in EXEC_PDFS:
        base = pdf_name[:-4]
        html = REPO / f"{base}.html"
        if not html.exists():
            print(f"  [exec] {base}.html missing — skipping")
            continue
        try:
            _patch_exec_html(html, record_date, prev_date, pulls,
                             score, prev_score, matrix_curr, matrix_prev,
                             AUDIENCE_FILTERS.get(base))
        except Exception as e:
            print(f"  [exec] {base}: patch failed ({e}) — skipping render",
                  file=sys.stderr)
            continue
        msg = _render_exec_pdf(base)
        if msg:
            print(f"  [exec] {base}: {msg}")
            rendered.append(pdf_name)
        else:
            print(f"  [exec] {base}: render FAILED — PDF left at prior state",
                  file=sys.stderr)
    return rendered


def _context():
    """Pick a context that actually has CAs loaded. The python.org build ships an
    empty trust store; the system /etc/ssl/cert.pem bundle is the reliable one."""
    try:
        ctx = ssl.create_default_context()
        ctx.load_default_certs()
        if ctx.cert_store_stats().get("x509_ca", 0) > 0:
            return ctx
    except Exception:
        pass
    return ssl.create_default_context(cafile="/etc/ssl/cert.pem")


def _post(cfg, body, ctx):
    req = urllib.request.Request(cfg["api_base"], data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json, text/event-stream")
    req.add_header(cfg.get("auth_header", "Authorization"),
                   cfg.get("auth_prefix", "Bearer ") + cfg["api_key"])
    with urllib.request.urlopen(req, timeout=90, context=ctx) as r:
        return r.read().decode()


def call_tool(cfg, name, arguments, ctx, _id=[0]):
    """Rate limit is 20 calls/min; the API answers 401/429 when throttled.
    Retry across the window boundary rather than dying mid-pull."""
    import time as _t
    _id[0] += 1
    body = json.dumps({"jsonrpc": "2.0", "id": _id[0], "method": "tools/call",
                       "params": {"name": name, "arguments": arguments}}).encode()
    raw = None
    for attempt in range(3):
        try:
            raw = _post(cfg, body, ctx)
            break
        except urllib.error.HTTPError as e:
            if e.code in (401, 429) and attempt < 2:
                print(f"throttled ({e.code}) on {name} — waiting for rate window", file=sys.stderr)
                _t.sleep(65)
                continue
            raise
        except urllib.error.URLError as e:
            if "CERTIFICATE_VERIFY_FAILED" in str(e.reason) and attempt < 2:
                ctx = ssl.create_default_context(cafile="/etc/ssl/cert.pem")
                continue
            raise
    if "data:" in raw:  # SSE framing — take the final data payload
        raw = [l[5:].strip() for l in raw.splitlines() if l.startswith("data:")][-1]
    res = json.loads(raw)
    if "error" in res:
        sys.exit(f"tool {name} failed: {res['error'].get('message')}")
    return json.loads(res["result"]["content"][0]["text"])


def slug(text, limit=40):
    s = "".join(c if c.isalnum() else "-" for c in text.lower())
    while "--" in s:
        s = s.replace("--", "-")
    return s.strip("-")[:limit]




MODEL_ORDER = ["gpt-4o-mini", "gemini-2.5-flash", "sonar", "google-aio", "google-ai-mode"]


def pull_matrix(cfg, brand_id, ctx):
    """Per-prompt per-model detail, 7-day window. ~21 calls, paced under 20/min."""
    import time as _t
    plist = call_tool(cfg, "list_prompts", {"brandId": brand_id, "days": 7}, ctx)
    details = []
    for p in plist.get("prompts", []):
        details.append(call_tool(cfg, "get_prompt_detail",
                                 {"brandId": brand_id, "promptId": p["promptId"], "days": 7}, ctx))
        _t.sleep(4.0)
    return details


def matrix_record(details):
    out = {}
    for d in details:
        by = {m["model"]: (m["score"] if m["totalRuns"] else None) for m in d["models"]}
        o = d["overall"]
        out[slug(d["text"])] = {"overall": o["score"] if o["totalRuns"] else None,
                                "runs": o["totalRuns"],
                                "models": {m: by.get(m) for m in MODEL_ORDER}}
    return out


def _cell(v):
    if v is None:
        return '<td style="text-align:center;color:#9AA7B8">&middot;</td>'
    c = "#0F9D58" if v >= 70 else ("#B45309" if v >= 40 else ("#C5221F" if v > 0 else "#8A94A3"))
    return f'<td style="text-align:center;font-family:monospace;font-weight:600;color:{c}">{v}</td>'


def matrix_rows_html(details):
    import html as _h
    rows = []
    for d in sorted(details, key=lambda x: -((x["overall"]["score"] or 0) if x["overall"]["totalRuns"] else -1)):
        t = _h.escape(d["text"][:72] + ("…" if len(d["text"]) > 72 else ""))
        by = {m["model"]: (m["score"] if m["totalRuns"] else None) for m in d["models"]}
        o = d["overall"]
        cells = "".join(_cell(by.get(m)) for m in MODEL_ORDER)
        overall = _cell(o["score"] if o["totalRuns"] else None)
        rows.append('<tr style="border-top:1px solid rgba(0,0,0,.07)"><td style="padding:5px 8px;line-height:1.3;font-size:12.5px">' + t + '</td>' + cells + overall + '</tr>')
    return "".join(rows)


def splice(path, start_marker, end_marker, content):
    p = pathlib.Path(path)
    src = p.read_text()
    a = src.index(start_marker) + len(start_marker)
    b = src.index(end_marker)
    p.write_text(src[:a] + content + src[b:])


# The measurement vendor's name must never appear in published client files.
# The upstream report generator reintroduces it (a JS fallback domain), so every
# run scrubs before commit and then verifies nothing slipped through.
# Pattern is written character-class style so this script does not itself contain
# the literal vendor name (scripts/ ships in the public repo).
_VENDOR = r"(?i)p[ea]{2}kaboo"
SCRUB_RULES = [
    (re.compile(r"(?i)ai" + r"p[ea]{2}kaboo" + r"\.com"), "telus.com"),
    (re.compile(_VENDOR), "visibility-tracker"),
]
SCRUB_GLOBS = ("*.html", "*.md", "archive/*.html", "data/*.md")
# Internal-only working docs where the vendor CAN be named (never published to
# Cloudflare per .assetsignore, never sent as a public deliverable).
SCRUB_EXCLUDE_PREFIXES = ("meeting-",)


def _skip_scrub(p):
    return p.name.startswith(SCRUB_EXCLUDE_PREFIXES)


def scrub_vendor_name():
    """Strip the vendor tool name from every publishable file. Returns files changed."""
    changed = []
    for pattern in SCRUB_GLOBS:
        for f in REPO.glob(pattern):
            if _skip_scrub(f):
                continue
            try:
                src = f.read_text()
            except (UnicodeDecodeError, OSError):
                continue
            out = src
            for rx, repl in SCRUB_RULES:
                out = rx.sub(repl, out)
            if out != src:
                f.write_text(out)
                changed.append(f.relative_to(REPO).as_posix())
    for rel in changed:
        print(f"scrubbed vendor name from {rel}")
    return changed


def verify_scrub():
    """Fail loudly rather than publish the vendor name."""
    hits = []
    for pattern in SCRUB_GLOBS:
        for f in REPO.glob(pattern):
            if _skip_scrub(f):
                continue
            try:
                if re.search(_VENDOR, f.read_text()):
                    hits.append(f.relative_to(REPO).as_posix())
            except (UnicodeDecodeError, OSError):
                continue
    if hits:
        print(f"ERROR: vendor name still present in {hits} — not pushing", file=sys.stderr)
    return not hits


def build_record(cfg, brand_id, ctx):
    vis = call_tool(cfg, "get_brand_visibility", {"brandId": brand_id, "timeRange": "30d"}, ctx)
    models = call_tool(cfg, "get_model_breakdown", {"brandId": brand_id, "days": 30}, ctx)
    prompts = call_tool(cfg, "list_prompts", {"brandId": brand_id, "days": 30}, ctx)
    comps = call_tool(cfg, "list_competitors", {"brandId": brand_id}, ctx)
    sources = call_tool(cfg, "list_top_sources", {"brandId": brand_id, "days": 30, "limit": 15}, ctx)
    series = call_tool(cfg, "get_visibility_timeseries",
                       {"brandId": brand_id, "days": 30, "includeCompetitors": False}, ctx)

    return {
        "date": datetime.date.today().isoformat(),
        "source": "api-pull (visibility tracking API, 30d window)",
        "api": {
            "visibility_score": vis.get("visibilityScore"),
            "runs": vis.get("runCount"),
            "trend": vis.get("trend"),
            "models": {
                m["label"].lower().replace(" ", "_"): {
                    "score": m["visibilityScore"],
                    "runs": m["runCount"],
                    "avg_position": m.get("averagePosition"),
                }
                for m in models.get("models", [])
            },
            "prompts": {
                slug(p["text"]): p["score"]
                for p in prompts.get("prompts", [])
                if p.get("score") is not None
            },
            "competitors": {
                c["name"]: c["visibilityScore"] for c in comps.get("competitors", [])
            },
            "top_sources": [
                {"domain": s["domain"], "citations": s["citationCount"],
                 "influence": s["influenceScore"]}
                for s in sources.get("sources", [])
            ],
            "citation_totals": {
                "domains": sources.get("totals", {}).get("totalDomains"),
                "citations": sources.get("totals", {}).get("totalCitations"),
            },
            "daily_scores": {
                d["date"]: d["score"]
                for d in series.get("brand", {}).get("series", [])
            },
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not CONFIG_PATH.exists():
        sys.exit(f"config not found: {CONFIG_PATH} — create it with api_base, api_key, brands")
    cfg = json.loads(CONFIG_PATH.read_text())
    globals()["CFG_CACHE"] = cfg  # expose anthropic_api_key to helpers
    brand_id = cfg["brands"].get(args.brand)
    if not brand_id:
        sys.exit(f"brand '{args.brand}' not in config brands map")

    ctx = _context()
    record = build_record(cfg, brand_id, ctx)
    details = pull_matrix(cfg, brand_id, ctx)
    record["api"]["prompt_matrix_7d"] = matrix_record(details)
    out = REPO / "data" / "longitudinal" / f"{args.brand}.jsonl"

    if args.dry_run:
        print(json.dumps(record, indent=2))
        return

    # skip if today's record already exists (idempotent for launchd retries)
    if out.exists():
        for line in out.read_text().splitlines():
            if line.strip() and json.loads(line)["date"] == record["date"]:
                print(f"record for {record['date']} already present — skipping")
                return
    with out.open("a") as f:
        f.write(json.dumps(record, separators=(",", ": ")) + "\n")
    print(f"appended {record['date']} → {out}")
    # regenerate report band + matrix between markers
    report = REPO / "full-report.html"
    vis7 = call_tool(cfg, "get_brand_visibility", {"brandId": brand_id, "timeRange": "7d"}, ctx)
    title = ('<div class="cc-title">API Snapshot &middot; Visibility Score ' + str(vis7["visibilityScore"]) + '/100 (7d)</div>'
             '<div class="cc-sub">7-day window ended ' + record["date"] + ' &middot; ' + str(vis7["runCount"]) + ' runs &middot; visibilityScore methodology</div>')
    splice(report, "<!-- BANDTITLE:START -->", "<!-- BANDTITLE:END -->", title)
    table = ('<div style="margin-top:14px;border-top:1px solid rgba(0,0,0,.08);padding-top:12px">'
             '<div class="cc-sub" style="margin-bottom:8px"><strong>Prompt &times; model matrix</strong> &middot; visibility score per surface, 7-day window ended ' + record["date"] + ' &middot; &ldquo;&middot;&rdquo; = no runs in window</div>'
             '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:12px">'
             '<thead><tr style="text-align:center"><th style="text-align:left;padding:5px 8px">Prompt</th><th>ChatGPT</th><th>Gemini</th><th>Perplexity</th><th>AIO</th><th>AI Mode</th><th>Overall</th></tr></thead>'
             '<tbody>' + matrix_rows_html(details) + '</tbody></table></div></div>')
    splice(report, "<!-- MATRIX:START -->", "<!-- MATRIX:END -->", table)
    # rebuild the trajectory page from the (now updated) store
    for builder, page in (("build_trajectory.py", "longitudinal.html"),
                          ("build_index.py", "index.html"),
                          ("build_scorecard.py", "scorecard.html"),
                          ("apply_shell.py", "shared shell — floating nav + GA credit")):
        try:
            subprocess.run([sys.executable, str(REPO / "scripts" / builder)],
                           cwd=REPO, check=True, capture_output=True, timeout=120)
            print(f"rebuilt {page}")
        except Exception as e:
            print(f"WARNING: {page} rebuild failed ({e}) — page left at prior version", file=sys.stderr)
    scrubbed = scrub_vendor_name()
    if not verify_scrub():
        sys.exit("aborting before push: vendor name present in publishable files")
    git_autopush("full-report.html", record["date"] + " report")
    git_autopush("longitudinal.html", record["date"] + " trajectory")
    git_autopush("index.html", record["date"] + " index")
    git_autopush("scorecard.html", record["date"] + " scorecard")
    git_autopush(str(out.relative_to(REPO)), record["date"])

    # -------- Weekly archive step (TELUS repo only) --------
    # Freeze this week's exec PDFs at /archive/{name}-{date}.pdf and add a
    # row to /history.html. Skipped on Rogers/Cogeco runs — they don't ship
    # exec-shaped PDFs from this repo.
    if args.brand == "telus":
        # 1) Splice fresh share-of-citation into Kevin/Rob/Jacob HTML.
        print("[sources] refreshing citation-source strips...")
        splice_sources(cfg, brand_id, record["date"], ctx)
        if not verify_scrub():
            sys.exit("aborting: vendor name present after sources splice")
        for name in SOURCES_TARGETS:
            git_autopush(name, record["date"] + " citation sources")
        git_autopush("data/longitudinal/sources-telus.jsonl",
                     record["date"] + " sources snapshot")

        # 2) Patch each exec HTML (version chip, pull count, dates, WoW band
        #    from prompt-matrix deltas) then re-render all 6 PDFs. Must run
        #    BEFORE stamp_archive so the dated /archive copies carry this
        #    week's numbers, not last week's rendered PDFs.
        print("[exec] patching exec HTMLs + re-rendering PDFs...")
        rerendered = refresh_exec_bands(record["date"],
                                        record["api"]["visibility_score"], out)
        if not verify_scrub():
            sys.exit("aborting: vendor name present after exec patch")
        # Push each patched HTML + its freshly-rendered PDF.
        for pdf_name in rerendered:
            html_name = pdf_name[:-4] + ".html"
            git_autopush(html_name, record["date"] + " exec band " + html_name)
            git_autopush(pdf_name,  record["date"] + " exec render " + pdf_name)

        # 3) Stamp current exec PDFs into /archive and prepend a history row.
        print("[archive] stamping exec PDFs + history row...")
        stamped = stamp_archive(record["date"])
        insert_history_row(record["date"], record["api"])
        for rel in stamped:
            git_autopush(f"archive/{rel}", record["date"] + " archive")
        git_autopush("history.html", record["date"] + " weekly archive row")

        # 4) Governance step: write editorial proposals for Rahul's review.
        #    This does NOT touch the published artifacts — it only produces a
        #    review file. If Rahul wants editorial headlines to ship, he edits
        #    the proposal and runs scripts/apply_editorial.py --date <date>.
        print("[editorial] writing proposal file for governance review...")
        proposal = write_editorial_proposals(record["date"], out)
        if proposal:
            git_autopush(str(proposal.relative_to(REPO)),
                         record["date"] + " editorial proposal")

    # Publish to the live gated Worker at telus-aeo.rahul-308.workers.dev.
    cloudflare_deploy()


if __name__ == "__main__":
    main()
