#!/usr/bin/env python3
"""Weekly AI-visibility pull → append one dated record to data/longitudinal/<brand>.jsonl.

Reads config from ~/.config/aeo-tracker/config.json (NEVER committed — keep keys out
of this public repo). Expected shape:

{
  "api_base": "https://<tracking-platform-host>/api",
  "api_key": "<key>",
  "auth_header": "Authorization",          // or "X-API-Key"
  "auth_prefix": "Bearer ",                 // "" when using X-API-Key
  "brands": { "telus": "<brand-uuid>" }
}

NOTE: endpoint paths below mirror the platform's MCP tool semantics
(get_brand_visibility, get_model_breakdown, list_prompts, list_competitors,
list_top_sources, get_visibility_timeseries). Verify the exact REST paths once
against the platform's API docs and adjust ENDPOINTS if they differ — the JSON
fields consumed here match what the platform returns through MCP.

Usage:
  python3 scripts/refresh_visibility.py --brand telus
  python3 scripts/refresh_visibility.py --brand telus --dry-run
"""
import argparse, datetime, json, pathlib, sys, urllib.parse, urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
CONFIG_PATH = pathlib.Path.home() / ".config" / "aeo-tracker" / "config.json"

ENDPOINTS = {
    "visibility": "/visibility?brandId={bid}&timeRange=30d",
    "models": "/model-breakdown?brandId={bid}&days=30",
    "prompts": "/prompts?brandId={bid}&days=30",
    "competitors": "/competitors?brandId={bid}",
    "sources": "/top-sources?brandId={bid}&days=30&limit=15",
    "timeseries": "/visibility-timeseries?brandId={bid}&days=30&includeCompetitors=false",
}


def get(cfg, path):
    url = cfg["api_base"].rstrip("/") + path
    req = urllib.request.Request(url)
    req.add_header(cfg.get("auth_header", "Authorization"),
                   cfg.get("auth_prefix", "Bearer ") + cfg["api_key"])
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def slug(text, limit=40):
    s = "".join(c if c.isalnum() else "-" for c in text.lower())
    while "--" in s:
        s = s.replace("--", "-")
    return s.strip("-")[:limit]


def build_record(cfg, brand_id):
    vis = get(cfg, ENDPOINTS["visibility"].format(bid=brand_id))
    models = get(cfg, ENDPOINTS["models"].format(bid=brand_id))
    prompts = get(cfg, ENDPOINTS["prompts"].format(bid=brand_id))
    comps = get(cfg, ENDPOINTS["competitors"].format(bid=brand_id))
    sources = get(cfg, ENDPOINTS["sources"].format(bid=brand_id))
    series = get(cfg, ENDPOINTS["timeseries"].format(bid=brand_id))

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

    record = build_record(cfg, brand_id)
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


if __name__ == "__main__":
    main()
