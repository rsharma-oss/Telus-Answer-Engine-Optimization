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
    ("index.html",        "Overview",   "svg-home"),
    ("scorecard.html",    "Scorecard",  "svg-card"),
    ("full-report.html",  "Report",     "svg-report"),
    ("longitudinal.html", "Trajectory", "svg-trend"),
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
#ga-nav { position:fixed; right:20px; bottom:20px; z-index:9998;
  background:var(--ga-carbon); color:#fff; padding:6px; border-radius:999px;
  box-shadow:0 8px 28px rgba(18,18,18,.28), 0 2px 6px rgba(51,79,180,.25);
  display:flex; gap:2px; font-family:'Assistant','Inter',system-ui,-apple-system,sans-serif;
  font-size:12.5px; font-weight:600; letter-spacing:.02em; border:1px solid rgba(255,255,255,.06); }
#ga-nav a { color:rgba(255,255,255,.72); text-decoration:none; padding:8px 13px;
  border-radius:999px; display:inline-flex; align-items:center; gap:7px;
  transition:background .15s ease, color .15s ease; }
#ga-nav a:hover, #ga-nav a:focus-visible { color:#fff; background:rgba(255,255,255,.08); outline:none; }
#ga-nav a:focus-visible { box-shadow:0 0 0 2px var(--ga-green) inset; }
#ga-nav a.current { background:var(--ga-blue); color:#fff; }
#ga-nav a.current:hover { background:var(--ga-blue); }
#ga-nav svg { flex-shrink:0; }
@media (max-width:700px) {
  #ga-nav { right:12px; bottom:12px; padding:5px; font-size:0; }
  #ga-nav a { padding:9px; }
  #ga-nav a.current { font-size:12px; padding:9px 12px; }
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

def nav_html(current):
    items = []
    for href, label, icon_key in NAV_ITEMS:
        is_cur = (href == current)
        attrs = ' class="current" aria-current="page"' if is_cur else ""
        items.append(f'<a href="{href}"{attrs} aria-label="{label}">'
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
    src = apply_region(src, "NAV", nav_html(path), "</body>")
    if with_credit:
        src = apply_region(src, "CREDIT", credit_html(), "</body>")
    p.write_text(src)
    return path


if __name__ == "__main__":
    changed = []
    for path in FULL_PAGES:
        changed.append(apply_shell(path, with_credit=True))
    for path in NAV_ONLY:
        changed.append(apply_shell(path, with_credit=False))
    print("shell applied to:", ", ".join(changed))
