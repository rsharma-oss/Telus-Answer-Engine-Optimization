#!/usr/bin/env python3
"""Apply operator-approved Actions-tab JSON from the weekly proposal file:
   data/editorial-proposals/actions-{date}.md

Reads the LAST ```json block in the file (so you can insert commentary
above it without breaking the parser), writes it to /tmp/telus-actions.json,
runs telus-rebuild.py --phase finalize to inject the actions into the
dashboard, scrubs any residual vendor name, swaps the finalized report into
the repo, re-applies the GA shell, pushes, and re-deploys Cloudflare.

Usage:
  python3 scripts/apply_actions.py --date 2026-10-12
  python3 scripts/apply_actions.py --date 2026-10-12 --dry-run

Governance invariant: this never INVENTS actions. It only applies what's in
the proposal file (which Rahul owns and edits by hand before running).
"""
import argparse, json, pathlib, re, subprocess, sys

REPO = pathlib.Path(__file__).resolve().parent.parent
GIT_AUTHOR = ["-c", "user.name=Rahul Sharma", "-c", "user.email=rahul@growthautomated.ai"]
TELUS_REBUILD = pathlib.Path.home() / ".claude" / "scripts" / "telus-rebuild.py"
HOME_OUT = pathlib.Path.home() / "telus-full-report.html"
ACTIONS_JSON = pathlib.Path("/tmp/telus-actions.json")


def parse_proposal(path):
    """Return the parsed actions list from the LAST ```json block in the file."""
    text = path.read_text()
    blocks = re.findall(r'```json\s*\n(.*?)\n\s*```', text, re.DOTALL)
    if not blocks:
        sys.exit(f"ERROR: no ```json block found in {path}")
    final = blocks[-1].strip()
    if not final or final == "[]":
        sys.exit("Proposal is empty — nothing to apply. Hand-craft 6 action "
                 "objects in the last ```json block, then re-run.")
    try:
        actions = json.loads(final)
    except json.JSONDecodeError as e:
        sys.exit(f"ERROR: JSON parse failed at line {e.lineno}: {e.msg}")
    if not isinstance(actions, list):
        sys.exit(f"ERROR: expected JSON array, got {type(actions).__name__}")
    if len(actions) != 6:
        sys.exit(f"ERROR: expected 6 actions, got {len(actions)}")
    return actions


def scrub(path):
    """Scrub vendor name from a file in-place. Returns True if the file is
    clean after scrub, False if residue remains (deploy must abort)."""
    src = path.read_text()
    new, n1 = re.subn(r'aip[ea]{2}kaboo\.com', 'telus.com', src, flags=re.IGNORECASE)
    new, n2 = re.subn(r'p[ea]{2}kaboo', 'measurement-platform', new, flags=re.IGNORECASE)
    if n1 or n2:
        path.write_text(new)
        print(f"  scrubbed: {n1} aipeekaboo.com + {n2} peekaboo")
    return not re.search(r'p[ea]{2}kaboo', path.read_text(), flags=re.IGNORECASE)


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
    ap.add_argument("--dry-run", action="store_true", help="Preview, don't apply")
    args = ap.parse_args()

    proposal = REPO / "data" / "editorial-proposals" / f"actions-{args.date}.md"
    if not proposal.exists():
        sys.exit(f"proposal not found: {proposal}")

    actions = parse_proposal(proposal)
    print(f"Proposal: {proposal.relative_to(REPO)}")
    print(f"Parsed {len(actions)} actions:")
    for a in actions:
        print(f"  - [{a.get('priority','?')}/{a.get('cat','?')}] {a.get('title','?')[:80]}")

    if args.dry_run:
        print("[dry-run] no files written")
        return

    # 1) Stage the actions JSON where telus-rebuild expects it.
    ACTIONS_JSON.write_text(json.dumps(actions, indent=2, ensure_ascii=False))
    print(f"wrote {ACTIONS_JSON}")

    # 2) Run phase=finalize to inject actions into the fetched report.
    r = subprocess.run(
        [sys.executable, str(TELUS_REBUILD), "--phase", "finalize"],
        capture_output=True, text=True, timeout=120,
    )
    if r.returncode != 0:
        sys.exit(f"finalize failed (rc={r.returncode}):\n{r.stderr}")
    if not HOME_OUT.exists():
        sys.exit(f"finalize did not write {HOME_OUT}")
    print(f"finalize ok: {HOME_OUT}")

    # 3) Scrub vendor name before anything touches the deployed tree.
    if not scrub(HOME_OUT):
        sys.exit("ABORT: vendor name still present after scrub")

    # 4) Back up current deployed full-report then swap.
    live = REPO / "full-report.html"
    if live.exists():
        (REPO / f"full-report.html.bak-{args.date}-pre-actions-apply").write_bytes(live.read_bytes())
    live.write_bytes(HOME_OUT.read_bytes())
    print(f"swapped: {HOME_OUT.name} → {live.name}")

    # 5) Re-apply shell (nav + brandbar).
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "apply_shell.py")],
                       cwd=REPO, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        print(f"WARNING: apply_shell failed (rc={r.returncode}):\n{r.stderr}",
              file=sys.stderr)

    # 6) Second scrub on the deployed file (defense in depth after shell apply).
    if not scrub(live):
        sys.exit("ABORT: vendor name present after shell apply")

    # 7) Push + Cloudflare deploy.
    git_autopush("full-report.html", f"{args.date} actions applied from proposal")

    try:
        import os
        env = {**os.environ, "PATH": "/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin"}
        r = subprocess.run(["/usr/local/bin/npx", "wrangler", "deploy"],
                           cwd=REPO, env=env, capture_output=True, text=True, timeout=180)
        if r.returncode == 0:
            print("[cloudflare] re-deployed with actions applied")
            print("\n".join(r.stdout.strip().splitlines()[-3:]))
        else:
            print(f"WARNING: cloudflare deploy failed (rc={r.returncode})",
                  file=sys.stderr)
    except Exception as e:
        print(f"WARNING: cloudflare deploy raised ({e})", file=sys.stderr)


if __name__ == "__main__":
    main()
