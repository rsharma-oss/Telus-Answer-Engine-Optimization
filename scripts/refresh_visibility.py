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
    git_autopush("full-report.html", record["date"] + " report")
    git_autopush(str(out.relative_to(REPO)), record["date"])


if __name__ == "__main__":
    main()
