# TELUS AEO — Cloudflare Worker deploy guide

Same pattern as the Grace NDA site: a Cloudflare **Static Assets Worker**
gated by a shared password (HTTP Basic Auth). One `wrangler deploy`
publishes every page and PDF in the repo; setting the password secret
locks them all.

**What you get:** `https://telus-aeo.<your-account>.workers.dev` — every
scorecard, the proposal, the trajectory page, the interactive report,
and the tracking store, behind one shared password.

`growthautomated.ai` DNS stays at GoDaddy. No custom domain, no DNS
migration. Share the `workers.dev` URL directly.

---

## Step 1 — One-time Cloudflare login (~1 min)

```bash
cd /Users/rahulsharma/Telus-AnswerEngineOptimization
npx wrangler login
```

Opens a browser, sign in, click Allow. Credentials save to
`~/.wrangler/` and persist forever.

## Step 2 — First deploy (~2 min)

```bash
npx wrangler deploy
```

Wrangler prints the assigned URL, something like
`https://telus-aeo.<account>.workers.dev`. Open it — you should get a
**401 Restricted** response with a Basic Auth prompt. That's correct.
The Worker fails closed until the password secret is set.

## Step 3 — Set the shared password (~30 sec)

```bash
npx wrangler secret put TELUS_PASSWORD
```

Prompts for the password. Type it, hit Enter. The secret is stored
encrypted on Cloudflare's side; nothing lands in git.

Reload the workers.dev URL. Browser prompts for a login:
- **Username**: `telus`
- **Password**: whatever you just set

That's it — you're in. Every page under the URL uses the same login;
browsers cache the credentials for the tab session.

## Rotating the password later

```bash
npx wrangler secret put TELUS_PASSWORD
```

Type the new password. Instantly rotates. Old credentials stop
working on the next request. No redeploy needed.

## Deploying updates

Any time the site changes (Monday auto-pull, a new scorecard, a
proposal edit) run:

```bash
npx wrangler deploy
```

Everything in the repo except what's listed in `.assetsignore` gets
published. The password stays set.

## Turning off GitHub Pages

Once the Worker URL is verified and shared:

1. GitHub → the `Telus-Answer-Engine-Optimization` repo → **Settings**
   → **Pages** → set source to `None`.
2. Optionally delete `.github/workflows/pages.yml` from the repo.

The repo stays on GitHub as source-of-truth; only the hosting moves.

## Automating deploy from the Monday LaunchAgent (optional)

The LaunchAgent already pushes to GitHub on Monday 08:00. To also
push to Cloudflare in the same job, add a `wrangler deploy` step
at the end of `scripts/refresh_visibility.py`. Wrangler picks up
the token from `~/.wrangler/` non-interactively.

---

Built against the same pattern as `~/Documents/Claude/shopping-agent/nda-site/`
(Grace NDA site, live since 2026-09-18).
