# Telus — Answer Engine Optimization

Growth Automated's AEO engagement repo for **Telus**: ongoing AI visibility tracking via our AI visibility tracking API, tracked since **June 2026**. Measures how Telus surfaces across 5 AI answer engines (Google AI Mode, Google AI Overview, Gemini, ChatGPT, Perplexity) on 20 ICP queries, versus category competitors.

## File map

| Path | What it is |
|---|---|
| `index.html` | Landing page linking to everything below |
| `scorecard.html` | One-page executive AI Visibility Scorecard (current) |
| `full-report.html` | Interactive AI Visibility Report — per-prompt, sentiment, competitors, citations, actions (current) |
| `data/` | Dated raw data pulls (source of truth for each refresh) |
| `data/visibility-data-2026-07-17.md` | Latest pull — 30d window 2026-06-17 → 2026-07-17 |
| `archive/` | Superseded page versions, dated by their data date |

## Data-refresh convention

- Each refresh starts with a **dated visibility-data pull** saved into `data/` (e.g. `visibility-data-YYYY-MM-DD.md`).
- Before `scorecard.html` / `full-report.html` are updated, the outgoing versions are copied into `archive/` with their prior data date in the filename (e.g. `telus-scorecard-2026-07-13.html`).
- Figures that use a different methodology than the API visibility score (e.g. prompt-coverage %, run-level analysed chats) keep their original date stamps rather than being overwritten.

## Current headline — as of 2026-07-17 (30d window)

- **Visibility: 71/100** · 1,961 runs · stable but softening (daily 74–79 late June → 65–76 last week)
- **By model:** Google AI Mode 80 · Gemini 73 · ChatGPT 72 · Google AIO 70 · Perplexity 61 (weakest surface, but avg position 1.2 when present)
- **Competitors:** Bell 39 · Rogers 31 · Freedom 11 · Vidéotron 2 · Cogeco 0 — Telus leads Bell roughly 2:1
- **Weak prompts (all unbranded commercial-intent):** flexible monthly data plans 2 · home-office wireline 6 · SMB wireless 36 · price-sensitive families 38 · rural reliability prompt = 100
- **Top source:** reddit.com (2,449 citations, influence 85); own properties telus.com + forum.telus.com ≈ 2,270 combined

## Longitudinal tracking

`data/longitudinal/telus.jsonl` is the append-only trajectory store — one record per pull date, seeded with five checkpoints backfilled from the archived scorecards (Jun 27 → Jul 13) plus the July 17 API pull. Two metric families are kept deliberately separate and must never be charted as one series:

- `manual_analysis` — coverage % and avg-score-among-mentions from the dated manual snapshots
- `api` — the tracking API's visibility score (0–100, share-of-answer weighted), per-model/per-prompt/competitor detail, and day-grain daily scores

**Weekly refresh:** `scripts/refresh_visibility.py --brand telus` appends the current 30-day pull (idempotent per date). It reads `~/.config/aeo-tracker/config.json` (api_base, api_key, brand ids) — the key never enters this repo. `scripts/com.growthautomated.aeo-refresh.plist` is a LaunchAgent template for Mondays 08:00. The API only looks back 90 days, so this store is the durable memory.

---
Growth Automated · Pragmatic AEO · rahul@growthautomated.ai
