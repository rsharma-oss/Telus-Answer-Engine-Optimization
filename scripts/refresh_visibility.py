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
import argparse, datetime, json, pathlib, ssl, subprocess, sys, urllib.error, urllib.request

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


def _context():
    try:
        ctx = ssl.create_default_context()
        ctx.load_default_certs()
        return ctx
    except Exception:
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
    _id[0] += 1
    body = json.dumps({"jsonrpc": "2.0", "id": _id[0], "method": "tools/call",
                       "params": {"name": name, "arguments": arguments}}).encode()
    try:
        raw = _post(cfg, body, ctx)
    except urllib.error.URLError as e:
        if "CERTIFICATE_VERIFY_FAILED" in str(e.reason):
            raw = _post(cfg, body, ssl.create_default_context(cafile="/etc/ssl/cert.pem"))
        else:
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
    brand_id = cfg["brands"].get(args.brand)
    if not brand_id:
        sys.exit(f"brand '{args.brand}' not in config brands map")

    record = build_record(cfg, brand_id, _context())
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
    git_autopush(str(out.relative_to(REPO)), record["date"])


if __name__ == "__main__":
    main()
