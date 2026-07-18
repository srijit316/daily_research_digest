# 📰 Daily Research Digest

An autonomous personal news agent. Every morning, a GitHub Actions pipeline fetches tech and sports news from free public sources, has **Claude Code curate and summarize it**, and publishes the result to a GitHub Pages site — no servers, no paid APIs.

**Live site:** `https://<username>.github.io/daily_research_digest/`

## How it works

```
GitHub Actions (cron, 9:00 AM ET daily)
│
├─ 1. fetch_news.py      Hacker News API · Reddit JSON · RSS feeds
│                        → data/raw/YYYY-MM-DD.json
│
├─ 2. curate.py          Claude Code (headless `claude -p`) dedupes, ranks,
│                        summarizes each pick + writes a daily overview
│                        → data/digest/YYYY-MM-DD.json
│                        (falls back to rule-based ranking if Claude fails)
│
└─ 3. commit + push      GitHub Pages serves site/ which renders the JSON
```

### Coverage

| Category | Sources |
|---|---|
| 💻 Tech | Hacker News, r/technology, r/programming, TechCrunch, The Verge, Ars Technica |
| 🏏 Cricket | ESPNcricinfo, r/Cricket |
| ⚽ Football | BBC Sport, r/soccer |
| 🏀 NBA | ESPN, r/nba |

Sources live in [scripts/sources.yaml](scripts/sources.yaml) — adding a feed is a config edit, not a code change.

### Why these choices

- **No X/Twitter** — the API free tier is unusable for reads and the paid tier costs $200/month; HN + Reddit + RSS surface the same stories reliably and for free.
- **Claude via Pro subscription, not API billing** — the workflow authenticates Claude Code with an OAuth token from `claude setup-token`, so curation runs on the existing Claude Pro plan.
- **Static front end** — vanilla HTML/CSS/JS on GitHub Pages. Nothing to deploy, nothing to break; the site is just a renderer over committed JSON, with a browsable archive of every past digest.
- **Graceful degradation** — every source is fetched independently, and if Claude curation fails the pipeline falls back to engagement/recency ranking. The digest always ships.

## Setup

1. **Create the GitHub repo and push:**

   ```bash
   gh repo create daily_research_digest --public --source . --push
   ```

2. **Add the Claude token secret** (uses your Claude Pro/Max subscription):

   ```bash
   claude setup-token        # follow the browser flow, copy the token
   gh secret set CLAUDE_CODE_OAUTH_TOKEN
   ```

3. **Enable GitHub Pages:** repo → Settings → Pages → Deploy from a branch → `main` / `/ (root)`.

4. **Trigger the first run:**

   ```bash
   gh workflow run digest.yml
   ```

The schedule is set in [.github/workflows/digest.yml](.github/workflows/digest.yml) (`0 13 * * *` UTC = 9:00 AM EDT).

## Run locally

```bash
pip install -r requirements.txt
python scripts/fetch_news.py                  # fetch today's raw items
python scripts/curate.py --mode auto          # Claude curation (or --mode fallback)
python -m http.server 8000                    # then open http://localhost:8000/site/
```

## Repo layout

```
.github/workflows/digest.yml   # daily cron + manual trigger
scripts/fetch_news.py          # source fetcher + normalizer
scripts/curate.py              # Claude Code curation + site data updates
scripts/fallback_rank.py       # rule-based ranking fallback
scripts/sources.yaml           # feed configuration
curation/prompt.md             # the curation prompt
data/                          # generated: raw snapshots, digests, index
site/                          # static front end (GitHub Pages)
```
