#!/usr/bin/env python3
"""Fetch news items from all configured sources and write a raw JSON snapshot.

Usage:
    python scripts/fetch_news.py [--date YYYY-MM-DD] [--sources scripts/sources.yaml]

Output: data/raw/<date>.json
Each item: {id, title, url, source, category, score, published_at}

Every source is fetched independently; a failing source is logged and skipped
so one dead feed never kills the digest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import requests
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
USER_AGENT = "daily-research-digest/1.0 (github.com personal news agent)"
MAX_AGE_HOURS = 36  # drop items older than this when a timestamp is available
REDDIT_DELAY_S = 12  # minimum spacing between unauthenticated Reddit requests
REDDIT_RETRY_DELAY_S = 30


def item_id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:12]


def make_item(title, url, source, category, score=None, published_at=None):
    return {
        "id": item_id(url),
        "title": title.strip(),
        "url": url,
        "source": source,
        "category": category,
        "score": score,
        "published_at": published_at,
    }


def is_fresh(published_at: str | None) -> bool:
    if not published_at:
        return True  # keep items with no timestamp; ranking handles the rest
    try:
        dt = datetime.fromisoformat(published_at)
    except ValueError:
        return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - dt < timedelta(hours=MAX_AGE_HOURS)


def fetch_hackernews(cfg, category):
    limit = cfg.get("limit", 30)
    ids = requests.get(
        "https://hacker-news.firebaseio.com/v0/topstories.json",
        headers={"User-Agent": USER_AGENT},
        timeout=15,
    ).json()[:limit]
    items = []
    for sid in ids:
        try:
            story = requests.get(
                f"https://hacker-news.firebaseio.com/v0/item/{sid}.json",
                headers={"User-Agent": USER_AGENT},
                timeout=15,
            ).json()
        except requests.RequestException:
            continue
        if not story or story.get("type") != "story" or not story.get("title"):
            continue
        url = story.get("url") or f"https://news.ycombinator.com/item?id={sid}"
        published = datetime.fromtimestamp(
            story.get("time", 0), tz=timezone.utc
        ).isoformat()
        item = make_item(
            story["title"], url, cfg["name"], category,
            score=story.get("score"), published_at=published,
        )
        if is_fresh(item["published_at"]):
            items.append(item)
    return items


_last_reddit_fetch = 0.0


def fetch_reddit(cfg, category):
    # Reddit's JSON API 403s unauthenticated clients, but the RSS endpoint
    # still serves descriptive user agents — with strict per-IP rate limits,
    # so space requests out and retry once on 429. No scores in RSS; ranking
    # falls back to recency for these items.
    global _last_reddit_fetch
    limit = cfg.get("limit", 15)
    url = f"https://www.reddit.com/r/{cfg['subreddit']}/top/.rss?t=day&limit={limit}"
    for attempt in range(3):
        wait = REDDIT_DELAY_S - (time.monotonic() - _last_reddit_fetch)
        if wait > 0:
            time.sleep(wait)
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
        _last_reddit_fetch = time.monotonic()
        if resp.status_code != 429 or attempt == 2:
            break
        time.sleep(REDDIT_RETRY_DELAY_S)
    resp.raise_for_status()
    feed = feedparser.parse(resp.text)
    items = []
    for entry in feed.entries[:limit]:
        if not entry.get("title") or not entry.get("link"):
            continue
        published = None
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        if parsed:
            published = datetime.fromtimestamp(
                time.mktime(parsed), tz=timezone.utc
            ).isoformat()
        items.append(
            make_item(
                entry["title"], entry["link"], cfg["name"], category,
                published_at=published,
            )
        )
    return items


def fetch_rss(cfg, category):
    limit = cfg.get("limit", 15)
    feed = feedparser.parse(cfg["url"], agent=USER_AGENT)
    items = []
    for entry in feed.entries[:limit]:
        if not entry.get("title") or not entry.get("link"):
            continue
        published = None
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        if parsed:
            published = datetime.fromtimestamp(
                time.mktime(parsed), tz=timezone.utc
            ).isoformat()
        item = make_item(
            entry["title"], entry["link"], cfg["name"], category,
            published_at=published,
        )
        if is_fresh(item["published_at"]):
            items.append(item)
    return items


FETCHERS = {"hackernews": fetch_hackernews, "reddit": fetch_reddit, "rss": fetch_rss}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    parser.add_argument("--sources", default=str(REPO_ROOT / "scripts" / "sources.yaml"))
    args = parser.parse_args()

    with open(args.sources) as f:
        sources = yaml.safe_load(f)

    all_items, seen_urls = [], set()
    for category, cfgs in sources.items():
        for cfg in cfgs:
            try:
                items = FETCHERS[cfg["type"]](cfg, category)
            except Exception as exc:  # noqa: BLE001 — one bad source must not kill the run
                print(f"[warn] {cfg['name']} ({category}) failed: {exc}", file=sys.stderr)
                continue
            fresh = 0
            for item in items:
                if item["url"] in seen_urls:
                    continue
                seen_urls.add(item["url"])
                all_items.append(item)
                fresh += 1
            print(f"[ok]   {cfg['name']} ({category}): {fresh} items")

    if not all_items:
        print("[fatal] no items fetched from any source", file=sys.stderr)
        sys.exit(1)

    out_dir = REPO_ROOT / "data" / "raw"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.date}.json"
    snapshot = {
        "date": args.date,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "item_count": len(all_items),
        "items": all_items,
    }
    out_path.write_text(json.dumps(snapshot, indent=2))
    print(f"[done] {len(all_items)} items -> {out_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
