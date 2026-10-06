#!/usr/bin/env python3
"""Apply operator-approved editorial headlines from a weekly proposal file,
then re-render affected exec PDFs, re-stamp the dated archive, commit, push,
and re-deploy Cloudflare.

Usage:
  python3 scripts/apply_editorial.py --date 2026-10-12
  python3 scripts/apply_editorial.py --date 2026-10-12 --dry-run

The proposal file lives at data/editorial-proposals/{date}.md. Each exec
section has an `**editorial:** ...` line; whatever text follows "editorial:"
replaces the data-only headline in the `<div class="wow-h">...</div>` of
that exec's HTML.

Blank or `(Claude headline unavailable...)` editorial lines are treated as
"keep the data-only headline" — no change made for that exec.

Governance invariant: this script never INVENTS editorial. It only applies
what's in the proposal file, which Rahul owns and edits by hand before
running this.
"""
import argparse, pathlib, re, subprocess, sys

REPO = pathlib.Path(__file__).resolve().parent.parent
GIT_AUTHOR = ["-c", "user.name=Rahul Sharma", "-c", "user.email=rahul@growthautomated.ai"]
_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

EXEC_PDFS = [
    "katherine-smb.pdf", "kevin-cmo.pdf", "david-telco.pdf",
    "kim-channels.pdf", "rob-consumer-marcom.pdf", "jacob-organic.pdf",
]


def parse_proposal(path):
    """Return {exec_base: editorial_text or None}. None = keep data-only."""
    out = {}
    current = None
    SKIP_MARKERS = ("(Claude headline unavailable",)
    for line in path.read_text().splitlines():
        m = re.match(r'##\s+([a-z0-9-]+)\s*—', line)
        if m:
            current = m.group(1)
            out.setdefault(current, None)
            continue
        if current and line.startswith("**editorial:**"):
            text = line[len("**editorial:**"):].strip()
            if not text or any(text.startswith(s) for s in SKIP_MARKERS):
                out[current] = None
            else:
                out[current] = text
    return out


def splice_headline(html_path, editorial):
    """Replace the content of <div class="wow-h">...</div>. Idempotent — a
    repeat with the same editorial is a no-op write."""
    src = html_path.read_text()
    pattern = re.compile(r'(<div class="wow-h">)[^<]*(</div>)', re.DOTALL)
    new_src, n = pattern.subn(f'\\g<1>{editorial}\\g<2>', src, count=1)
    if n == 0:
        return False
    if new_src != src:
        html_path.write_text(new_src)
    return True


def render_pdf(basename):
    html = REPO / f"{basename}.html"
    pdf = REPO / f"{basename}.pdf"
    r = subprocess.run(
        [_CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer",
         f"--print-to-pdf={pdf}", f"file://{html}"],
        capture_output=True, text=True, timeout=60,
    )
    msg = (r.stdout + r.stderr).splitlines()
    return next((l for l in msg if "bytes written" in l), None)


def git_autopush(rel_path, msg):
    try:
        subprocess.run(["git", "add", rel_path], cwd=REPO, check=True, capture_output=True)
        diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO)
        if diff.returncode == 0:
            return
        subprocess.run(["git", *GIT_AUTHOR, "commit", "-m", msg],
                       cwd=REPO, check=True, capture_output=True)
        subprocess.run(["git", "push"], cwd=REPO, check=True, capture_output=True, timeout=120)
        print(f"  pushed: {rel_path}")
    except Exception as e:
        print(f"  WARNING: push failed for {rel_path} ({e})", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="YYYY-MM-DD of the proposal to apply")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show which headlines would change, don't write files")
    args = ap.parse_args()

    proposal = REPO / "data" / "editorial-proposals" / f"{args.date}.md"
    if not proposal.exists():
        sys.exit(f"proposal not found: {proposal}")

    decisions = parse_proposal(proposal)
    to_apply = {k: v for k, v in decisions.items() if v}
    print(f"Proposal: {proposal.relative_to(REPO)}")
    print(f"Found {len(decisions)} exec sections; "
          f"{len(to_apply)} have an editorial headline to apply.")
    for base, text in to_apply.items():
        print(f"  → {base}: {text}")

    if args.dry_run:
        print("[dry-run] no files written")
        return
    if not to_apply:
        print("Nothing to apply — the data-only headlines stay in place.")
        return

    changed = []
    for base, editorial in to_apply.items():
        html = REPO / f"{base}.html"
        if not html.exists():
            print(f"  [skip] {base}.html missing", file=sys.stderr)
            continue
        if not splice_headline(html, editorial):
            print(f"  [skip] {base}.html: wow-h pattern not matched", file=sys.stderr)
            continue
        msg = render_pdf(base)
        print(f"  [applied] {base}: {msg}")
        # Re-stamp the dated archive so the frozen URL carries the editorial.
        pdf = REPO / f"{base}.pdf"
        archive = REPO / "archive" / f"{base}-{args.date}.pdf"
        if archive.parent.exists():
            archive.write_bytes(pdf.read_bytes())
        changed.append(base)

    # Push each changed HTML, PDF, and archive.
    for base in changed:
        git_autopush(f"{base}.html", f"{args.date} editorial headline · {base}")
        git_autopush(f"{base}.pdf",  f"{args.date} editorial render · {base}")
        git_autopush(f"archive/{base}-{args.date}.pdf",
                     f"{args.date} editorial archive · {base}")

    # Re-deploy to Cloudflare so the gated worker serves the approved copy.
    try:
        env = {**__import__("os").environ, "PATH":
               "/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin"}
        r = subprocess.run(["/usr/local/bin/npx", "wrangler", "deploy"],
                           cwd=REPO, env=env, capture_output=True, text=True, timeout=180)
        if r.returncode == 0:
            print("[cloudflare] re-deployed with editorial applied")
            print("\n".join(r.stdout.strip().splitlines()[-3:]))
        else:
            print(f"WARNING: cloudflare deploy failed (rc={r.returncode})",
                  file=sys.stderr)
    except Exception as e:
        print(f"WARNING: cloudflare deploy raised ({e})", file=sys.stderr)


if __name__ == "__main__":
    main()
