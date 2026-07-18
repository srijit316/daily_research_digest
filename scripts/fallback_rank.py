#!/usr/bin/env python3
"""Rule-based digest builder — the fallback when Claude curation is unavailable.

Ranks items by engagement (HN points / Reddit upvotes) and recency, then takes
the top N per category. Produces the same digest JSON shape as Claude curation,
minus per-item summaries.

Usable as a module (build_fallback_digest) or standalone:
    python scripts/fallback_rank.py --date YYYY-MM-DD
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SECTION_LIMITS = {"tech": 8, "cricket": 4, "football": 4, "nba": 4}
SECTION_TITLES = {"tech": "Tech", "cricket": "Cricket", "football": "Football", "nba": "NBA"}


def _rank_score(item: dict) -> float:
    """Engagement score with recency decay. RSS items (no score) rank on recency."""
    engagement = item.get("score") or 0
    hours_old = 12.0  # neutral default when timestamp is missing
    if item.get("published_at"):
        try:
            dt = datetime.fromisoformat(item["published_at"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            hours_old = max(
                0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600
            )
        except ValueError:
            pass
    recency = max(0.0, 1.0 - hours_old / 36)
    return engagement * (0.5 + recency) + recency * 50


def build_fallback_digest(raw: dict) -> dict:
    by_category: dict[str, list] = {}
    for item in raw["items"]:
        by_category.setdefault(item["category"], []).append(item)

    sections = []
    for category, title in SECTION_TITLES.items():
        items = sorted(
            by_category.get(category, []), key=_rank_score, reverse=True
        )[: SECTION_LIMITS[category]]
        sections.append(
            {
                "category": category,
                "title": title,
                "items": [
                    {
                        "title": i["title"],
                        "url": i["url"],
                        "source": i["source"],
                        "score": i.get("score"),
                        "summary": None,
                    }
                    for i in items
                ],
            }
        )

    return {
        "date": raw["date"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "fallback",
        "overview": (
            "Automated ranking by engagement and recency — AI curation was "
            "unavailable for this run, so items appear without summaries."
        ),
        "sections": sections,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d")
    )
    args = parser.parse_args()

    raw_path = REPO_ROOT / "data" / "raw" / f"{args.date}.json"
    raw = json.loads(raw_path.read_text())
    digest = build_fallback_digest(raw)

    out_dir = REPO_ROOT / "data" / "digest"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.date}.json"
    out_path.write_text(json.dumps(digest, indent=2))
    print(f"[done] fallback digest -> {out_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
