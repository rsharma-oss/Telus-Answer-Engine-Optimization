#!/usr/bin/env python3
"""Inject a shared floating nav + GA branding into every public page.

Runs after all four builders in the weekly job. Markers keep it idempotent:
each region between <!-- SHELL:CSS/START --> ... <!-- SHELL:CSS/END --> etc. is
replaced on each run; if a marker is missing on a page, we insert it once and
subsequent runs update in place.

Design principles:
  · Growth Automated palette (Growth Blue #334FB4, Carbon Black #121212,
    Success Green #2D9C56) applied ONLY to the shell, not the page bodies —
    the pages keep their existing per-topic colour language.
  · Floating pill nav bottom-right, current page highlighted, keyboard reachable,
    hidden on print. Same nav on all four pages so any deep link is one hop
    from any other view.
  · GA credit strip at the bottom of every page: wordmark, "Pragmatic AEO",
    booking CTA — so the branding is present without displacing the client-facing
    Telus content in the hero.
"""
import pathlib, re

REPO = pathlib.Path(__file__).resolve().parent.parent

# Pages that get the shell. The interactive report is 7.4MB with its own dashboard
# chrome, so we give it a lighter treatment (nav only, no credit strip).
FULL_PAGES = ["index.html", "scorecard.html", "longitudinal.html"]
NAV_ONLY   = ["full-report.html"]

NAV_ITEMS = [
    ("index.html",        "Overview",   "svg-home", None),
    ("scorecard.html",    "Scorecard",  "svg-card", [
        ("scorecard.html",       "Aggregate scorecard",        "SCORECARD"),
        ("katherine-smb.pdf",    "Katherine · SMB read",       "PDF"),
        ("david-telco.pdf",      "David · Telco Division",     "PDF"),
        ("kevin-cmo.pdf",        "Kevin · Brand narrative",    "PDF"),
        ("kim-channels.pdf",     "Kim · Channel-specific",     "PDF"),
        ("rob-consumer-marcom.pdf", "Rob · Consumer Marcom",     "PDF"),
        ("jacob-organic.pdf",    "Jacob · Head of Organic",    "PDF"),
        ("ip-map.pdf",           "What's proprietary · IP map","PDF"),
        ("platform.pdf",         "What's proprietary · Platform","PDF"),
        ("history.html",         "Weekly refresh · archive",   "HISTORY"),
    ]),
    # Report is unlocked — any viewer past the Cloudflare pw gate reaches
    # full-report.html directly. (The underlying Cloudflare Basic Auth still
    # protects the whole site; this just removes the in-site NDA-modal detour.)
    ("full-report.html",  "Report",     "svg-report", None),
    ("longitudinal.html", "Trajectory", "svg-trend", None),
]

ICONS = {
"svg-home":   '<svg viewBox="0 0 20 20" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 8.5L10 3l7 5.5V16a1 1 0 0 1-1 1h-3v-5H8v5H5a1 1 0 0 1-1-1V8.5z"/></svg>',
"svg-card":   '<svg viewBox="0 0 20 20" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="4" width="14" height="12" rx="2"/><path d="M6 8h8M6 11h5"/></svg>',
"svg-report": '<svg viewBox="0 0 20 20" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M5 3h7l3 3v11a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/><path d="M12 3v3h3M7 10h6M7 13h6"/></svg>',
"svg-trend":  '<svg viewBox="0 0 20 20" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M3 15l4-4 3 3 7-8"/><path d="M13 6h4v4"/></svg>',
}

SHELL_CSS = """
:root { --ga-blue:#334FB4; --ga-carbon:#121212; --ga-green:#2D9C56; --ga-cloud:#F3F3F3; }
@media print { #ga-nav, #ga-credit { display:none !important; } }
body { padding-top:0; }

#ga-brandbar { background:#334FB4; color:#fff; padding:14px 40px; display:flex;
  align-items:center; justify-content:space-between; gap:16px; flex-wrap:wrap;
  font-family:'Assistant','Inter',system-ui,-apple-system,sans-serif;
  border-bottom:3px solid #2D9C56; }
#ga-brandbar .gb-cobrand { display:flex; align-items:center; gap:14px; min-height:36px; }
#ga-brandbar .gb-ga { height:28px; width:auto; display:block; }
#ga-brandbar .gb-client-official { height:34px; width:auto; display:block; }
#ga-brandbar .gb-client-card { display:inline-flex; flex-direction:column; align-items:flex-start;
  padding:5px 12px; border:1px solid rgba(255,255,255,.28); border-radius:8px;
  background:rgba(255,255,255,.05); line-height:1; }
#ga-brandbar .gb-client-card .gb-client-kicker { font-family:'DM Mono','JetBrains Mono',monospace;
  font-size:8.5px; font-weight:700; letter-spacing:.20em; text-transform:uppercase;
  color:rgba(255,255,255,.62); margin-bottom:3px; }
#ga-brandbar .gb-client-card .gb-client-name { font-family:'Assistant','Helvetica Neue',system-ui,sans-serif;
  font-weight:800; font-size:18px; letter-spacing:.10em; color:#fff; }
#ga-brandbar .gb-sub { font-size:10.5px; font-weight:600; letter-spacing:.14em; text-transform:uppercase;
  color:rgba(255,255,255,.62); padding-left:12px; margin-left:4px;
  border-left:1px solid rgba(255,255,255,.20); }
#ga-brandbar .gb-right { display:flex; align-items:center; gap:14px; font-size:11.5px;
  color:rgba(255,255,255,.85); font-family:'DM Mono',monospace; }
#ga-brandbar .gb-chip { background:rgba(255,255,255,.08); border:1px solid rgba(255,255,255,.16);
  padding:5px 10px; border-radius:20px; letter-spacing:.06em; }
@media (max-width:820px) { #ga-brandbar .gb-sub { display:none; } }
@media (max-width:700px) { #ga-brandbar { padding:10px 18px; }
  #ga-brandbar .gb-right { font-size:10.5px; gap:8px; }
  #ga-brandbar .gb-client { height:28px; } #ga-brandbar .gb-ga { height:22px; } }

#ga-nav { position:fixed; top:76px; left:50%; transform:translateX(-50%); z-index:9998;
  background:var(--ga-carbon); color:#fff; padding:5px; border-radius:999px;
  box-shadow:0 6px 22px rgba(18,18,18,.32), 0 2px 6px rgba(51,79,180,.25);
  display:flex; gap:2px; font-family:'Assistant','Inter',system-ui,-apple-system,sans-serif;
  font-size:12.5px; font-weight:600; letter-spacing:.02em; border:1px solid rgba(255,255,255,.08); }
#ga-nav a { color:rgba(255,255,255,.72); text-decoration:none; padding:8px 13px;
  border-radius:999px; display:inline-flex; align-items:center; gap:7px;
  transition:background .15s ease, color .15s ease; }
#ga-nav a:hover, #ga-nav a:focus-visible { color:#fff; background:rgba(255,255,255,.08); outline:none; }
#ga-nav a:focus-visible { box-shadow:0 0 0 2px var(--ga-green) inset; }
#ga-nav a.current { background:var(--ga-blue); color:#fff; }
#ga-nav a.current:hover { background:var(--ga-blue); }
#ga-nav svg { flex-shrink:0; }
#ga-nav a.locked .lock-glyph { font-size:10px; margin-left:2px; opacity:.72; }
#ga-nav a.locked:hover { background:rgba(180,83,9,.24); color:#fff; }
#ga-nav .caret { opacity:.55; margin-left:1px; transition:transform .15s ease; pointer-events:none; }
#ga-nav .nav-group { position:relative; display:inline-flex; }
#ga-nav .nav-group > a { cursor:pointer; }
#ga-nav .nav-group.current > a { background:var(--ga-blue); color:#fff; }
#ga-nav .nav-group:hover .caret, #ga-nav .nav-group:focus-within .caret { transform:rotate(180deg); opacity:1; }
/* Dropdown sits 8px below trigger — invisible ::before bridges the gap so hover survives cursor traversal */
#ga-nav .nav-dropdown { position:absolute; top:calc(100% + 8px); left:50%; transform:translateX(-50%) translateY(-6px);
  min-width:280px; background:#1B1B24; color:#fff; border-radius:12px; padding:6px;
  box-shadow:0 20px 40px rgba(0,0,0,.4), 0 4px 12px rgba(0,0,0,.2);
  border:1px solid rgba(255,255,255,.08);
  opacity:0; visibility:hidden; pointer-events:none;
  transition:opacity .15s ease, transform .15s ease, visibility .15s ease;
  display:flex; flex-direction:column; gap:1px; }
#ga-nav .nav-dropdown::before { content:""; position:absolute; left:0; right:0; top:-10px; height:10px; background:transparent; }
#ga-nav .nav-group:hover .nav-dropdown, #ga-nav .nav-group:focus-within .nav-dropdown {
  opacity:1; visibility:visible; transform:translateX(-50%) translateY(0); pointer-events:auto; }
#ga-nav .nav-dropdown a { padding:9px 14px; border-radius:8px;
  display:flex; align-items:center; justify-content:space-between; gap:14px;
  color:rgba(255,255,255,.82); font-size:12.5px; font-weight:600; }
#ga-nav .nav-dropdown a:hover { background:rgba(255,255,255,.08); color:#fff; }
#ga-nav .nav-dropdown a .lbl { flex:1; text-align:left; }
#ga-nav .nav-dropdown a .kind { font-family:'DM Mono',monospace; font-size:9.5px;
  color:var(--ga-green); background:rgba(45,156,86,.12); border:1px solid rgba(45,156,86,.28);
  padding:2px 7px; border-radius:4px; letter-spacing:.08em; font-weight:800; }
#ga-nav .nav-dropdown a.primary .kind { color:#7C93E0; background:rgba(51,79,180,.14); border-color:rgba(51,79,180,.32); }
@media (max-width:700px) {
  #ga-nav { top:62px; padding:4px; font-size:0; }
  #ga-nav a { padding:8px; }
  #ga-nav a.current { font-size:12px; padding:8px 11px; }
}
#ga-credit { margin-top:0; background:var(--ga-carbon); color:rgba(255,255,255,.78);
  padding:22px 40px; display:flex; align-items:center; justify-content:space-between; gap:24px;
  font-family:'Assistant','Inter',system-ui,-apple-system,sans-serif; font-size:13px;
  border-top:2px solid var(--ga-blue); flex-wrap:wrap; }
#ga-credit .ga-brand { display:flex; align-items:center; gap:14px; }
#ga-credit .ga-mark { height:26px; width:auto; display:block; filter:brightness(1.05); }
#ga-credit .ga-tag { font-weight:600; color:#fff; letter-spacing:.02em; }
#ga-credit .ga-tag small { display:block; font-weight:400; color:rgba(255,255,255,.55);
  font-size:11px; letter-spacing:.06em; text-transform:uppercase; margin-top:2px; }
#ga-credit a.ga-cta { color:#fff; background:var(--ga-blue); padding:9px 16px; border-radius:8px;
  text-decoration:none; font-weight:600; transition:background .15s ease; }
#ga-credit a.ga-cta:hover { background:#4560c8; }
#ga-credit a.ga-cta:focus-visible { outline:2px solid var(--ga-green); outline-offset:2px; }
"""


def brandbar_html(current):
    label_by_page = {
        "index.html":        ("Overview",   "Client engagement · report hub"),
        "scorecard.html":    ("Scorecard",  "One-page executive read"),
        "longitudinal.html": ("Trajectory", "Longitudinal view"),
        "full-report.html":  ("Report",     "Interactive AI visibility report"),
    }
    label, sub = label_by_page.get(current, ("", ""))
    # If assets/telus-official.svg exists, use it (client-supplied official mark).
    # Otherwise render a neutral "PREPARED FOR" text card — no fabricated corporate mark.
    telus_official = (REPO / "assets" / "telus-official.svg")
    if telus_official.exists():
        client_html = f'<img class="gb-client-official" src="assets/telus-official.svg" alt="TELUS">'
    else:
        client_html = (
            '<span class="gb-client-card" aria-label="Prepared for TELUS">'
            '<span class="gb-client-kicker">Prepared for</span>'
            '<span class="gb-client-name">TELUS</span>'
            '</span>'
        )
    return (
        '<div id="ga-brandbar" role="banner">'
        '<div class="gb-cobrand">'
        '<img class="gb-ga" src="assets/ga-logo-white.svg" alt="Growth Automated">'
        f'{client_html}'
        '<span class="gb-sub" aria-hidden="true">Panel engagement · report hub</span>'
        '</div>'
        '<div class="gb-right">'
        f'<span class="gb-chip">{label}</span>'
        f'<span>{sub}</span>'
        '</div>'
        '</div>'
    )


def nav_html(current):
    items = []
    for href, label, icon_key, extra in NAV_ITEMS:
        is_cur = (href == current) or (extra and isinstance(extra, list) and any(current == c[0] for c in extra))
        classes = ["current"] if is_cur else []
        if extra == "LOCKED":
            classes.append("locked")
        if isinstance(extra, list):
            classes.append("has-children")
        cls_attr = f' class="{" ".join(classes)}"' if classes else ""
        cur_attr = ' aria-current="page"' if is_cur else ""

        if extra == "LOCKED":
            # Report nav — navigate to landing and open modal on arrival
            link = (f'<a href="{href}"{cls_attr}{cur_attr} aria-label="{label} (NDA required)">'
                    f'{ICONS[icon_key]}<span>{label}</span>'
                    f'<span class="lock-glyph" aria-hidden="true">🔒</span></a>')
            items.append(link)
        elif isinstance(extra, list):
            # Dropdown parent + children
            child_items = "".join(
                f'<a class="{"pdf" if kind == "PDF" else "primary"}" href="{chref}"'
                f'{" target=\"_blank\"" if kind == "PDF" else ""}>'
                f'<span class="lbl">{clabel}</span>'
                f'<span class="kind">{kind}</span></a>'
                for chref, clabel, kind in extra
            )
            link = (f'<div class="nav-group{" current" if is_cur else ""}">'
                    f'<a href="{href}"{cls_attr}{cur_attr} aria-label="{label}" aria-haspopup="true">'
                    f'{ICONS[icon_key]}<span>{label}</span>'
                    f'<svg class="caret" viewBox="0 0 12 12" width="9" height="9" fill="currentColor"><path d="M2 4l4 4 4-4z"/></svg>'
                    f'</a>'
                    f'<div class="nav-dropdown" role="menu">{child_items}</div>'
                    f'</div>')
            items.append(link)
        else:
            items.append(f'<a href="{href}"{cls_attr}{cur_attr} aria-label="{label}">'
                         f'{ICONS[icon_key]}<span>{label}</span></a>')
    return '<nav id="ga-nav" role="navigation" aria-label="Report sections">' + "".join(items) + '</nav>'


def credit_html():
    return ('<footer id="ga-credit" role="contentinfo">'
            '<div class="ga-brand">'
            '<img class="ga-mark" src="assets/ga-logo-white.svg" alt="Growth Automated">'
            '<span class="ga-tag">Pragmatic AEO<small>Growth Automated · growthautomated.ai</small></span>'
            '</div>'
            '<a class="ga-cta" href="https://seo-for-ai.growthautomated.ai/book_time" '
            'target="_blank" rel="noopener">Book time with Rahul</a>'
            '</footer>')


def apply_region(src, name, content, before_close):
    """Idempotent inject: if markers exist, replace between them; else insert before given tag."""
    start = f"<!-- SHELL:{name}/START -->"
    end   = f"<!-- SHELL:{name}/END -->"
    block = f"{start}{content}{end}"
    if start in src and end in src:
        return re.sub(re.escape(start) + r".*?" + re.escape(end), block, src, count=1, flags=re.S)
    # first-time insert immediately before the given closing tag
    idx = src.rfind(before_close)
    if idx == -1:
        return src + "\n" + block
    return src[:idx] + block + src[idx:]


def apply_shell(path, with_credit=True):
    p = REPO / path
    src = p.read_text()
    style_block = f"<style>{SHELL_CSS}</style>"
    src = apply_region(src, "CSS", style_block, "</head>")
    src = apply_region(src, "HEADER", brandbar_html(path), "</body>")
    src = apply_region(src, "NAV", nav_html(path), "</body>")
    if with_credit:
        src = apply_region(src, "CREDIT", credit_html(), "</body>")
    p.write_text(src)
    _hoist_header(path)
    return path




def _hoist_header(path):
    """Move the header block to immediately after <body>, once per file."""
    import re
    p = pathlib.Path(path); s = p.read_text()
    m = re.search(r"<!-- SHELL:HEADER/START -->.*?<!-- SHELL:HEADER/END -->", s, flags=re.S)
    if not m: return
    block = m.group(0)
    # remove existing
    s = s.replace(block, "")
    # insert immediately after <body...>
    s = re.sub(r"(<body[^>]*>)", r"\1\n" + block.replace("\\", "\\\\"), s, count=1)
    # regex escaping got weird — use string form
    p.write_text(s)

if __name__ == "__main__":
    changed = []
    for path in FULL_PAGES:
        changed.append(apply_shell(path, with_credit=True))
    for path in NAV_ONLY:
        changed.append(apply_shell(path, with_credit=False))
    print("shell applied to:", ", ".join(changed))
