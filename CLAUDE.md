# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An autonomous daily news digest agent. GitHub Actions runs on a cron schedule, fetches tech/cricket/football/NBA news from free sources, curates it with Claude Code in headless mode, and publishes a static site via GitHub Pages. No servers, no paid APIs — Claude curation runs on the repo owner's Claude Pro plan via an OAuth token secret, not API billing.

Live site: https://srijit316.github.io/daily_research_digest/
Repo: https://github.com/srijit316/daily_research_digest

## Pipeline (in execution order)

1. **`scripts/fetch_news.py`** — reads `scripts/sources.yaml`, fetches Hacker News (Firebase API), Reddit (RSS endpoint — the JSON API 403s unauthenticated clients), and RSS feeds. Writes `data/raw/<date>.json`. Every source is fetched independently and a failing source is logged and skipped, not fatal.
2. **`scripts/curate.py`** — runs `claude -p` headless with `curation/prompt.md` + the day's raw items, expects strict JSON (`{overview, selections}`) back, maps selected ids onto full item data, and writes `data/digest/<date>.json`. Also updates `data/latest.json` and `data/index.json` (the site's data feed). On any failure (auth, timeout, bad JSON) it falls back to `scripts/fallback_rank.py`'s rule-based ranking (engagement + recency, no summaries) — the digest always ships.
3. **`.github/workflows/digest.yml`** — orchestrates the above on a cron (`0 13 * * *` = 9:00 AM Eastern; note GitHub cron is fixed UTC and doesn't shift for DST) and on `workflow_dispatch`, then commits `data/` back to `main` as `github-actions[bot]`. That push auto-triggers GitHub's Pages rebuild.
4. **`scripts/send_email.py`** — reads the day's `data/digest/<date>.json` and emails it to a Gmail inbox as multipart HTML + plain text. Stdlib only (`smtplib`/`email.message`), no new dependencies. Runs last in the workflow, after the commit/push, under `continue-on-error: true`.
5. **`site/`** — static vanilla HTML/CSS/JS front end. `app.js` fetches `../data/index.json` and `../data/digest/<date>.json` at runtime; there is no build step and the HTML never changes day to day, only the JSON data does.

## Key architectural decisions

- **Reddit uses RSS, not the JSON API.** `.../top/.rss?t=day` works with a descriptive User-Agent; `.../top.json` returns 403. Requests are throttled (`REDDIT_DELAY_S` in `fetch_news.py`) with retry-on-429, since the RSS endpoint has strict per-IP rate limits.
- **Claude auth is an OAuth token, not an API key.** The workflow reads `CLAUDE_CODE_OAUTH_TOKEN` from repo secrets (generated locally via `claude setup-token`), so curation draws from the Pro subscription's usage rather than metered API billing.
- **Email uses Gmail SMTP with an app password, not an API.** `GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD` are repo secrets; the app password comes from myaccount.google.com/apppasswords and requires 2-Step Verification on the account. Sending from the address to itself sidesteps SPF/DKIM and spam filtering. If either secret is missing the script exits 0 without sending, so local runs and forks don't fail.
- **Fallback is not optional.** `curate.py --mode auto` always tries Claude first and drops to `fallback_rank.py` on any exception — this is what keeps the daily pipeline from going dark on a transient auth or API failure. `--mode claude` / `--mode fallback` force one path (useful for local testing).
- **`sources.yaml` is the extension point.** Adding/removing a feed (tech, cricket, football, or nba) is a config edit — no code changes. Categories and per-category selection caps live in `SECTION_LIMITS` / `SECTION_TITLES` in `fallback_rank.py` (shared by `curate.py`).
- **Root `index.html` is a redirect, not the app.** GitHub Pages serves the repo root (needed so `site/` and `data/` are both reachable), so `index.html` immediately forwards to `./site/`. The real app is `site/index.html`.
- **Digests are permanent and addressable.** Every `data/digest/<date>.json` is committed and kept — the site's date picker/archive nav reads `data/index.json` for the list of available dates. Nothing is overwritten except `latest.json`.

## Local development

Python deps aren't on the system `python3` (3.9) — the working interpreter with `requests`/`feedparser`/`PyYAML` installed is Homebrew's 3.11:

```bash
/opt/homebrew/bin/python3.11 scripts/fetch_news.py                  # fetch today's raw items → data/raw/<date>.json
/opt/homebrew/bin/python3.11 scripts/curate.py --mode auto           # curate (Claude, falls back on failure) → data/digest/, latest.json, index.json
/opt/homebrew/bin/python3.11 scripts/curate.py --mode fallback       # force rule-based ranking, no Claude call
/opt/homebrew/bin/python3.11 scripts/send_email.py --dry-run /tmp/d.html  # render the email to a file, no send
/opt/homebrew/bin/python3.11 scripts/send_email.py                   # send (no-ops unless GMAIL_ADDRESS/GMAIL_APP_PASSWORD are set)
/opt/homebrew/bin/python3.11 -m http.server 8000                     # serve locally, then open http://localhost:8000/site/
```

Manually trigger the production workflow: `gh workflow run digest.yml`, watch with `gh run watch <run-id>`.

## Git workflow note

The CI bot commits `data/` to `main` on every scheduled run. Local `main` drifts behind quickly — always `git pull --rebase` before pushing local changes to avoid rejected pushes.
