#!/usr/bin/env python3
"""Curate the day's raw items into a digest using Claude Code headless mode.

Runs `claude -p` with the curation prompt + today's items, expects strict JSON
back, and maps Claude's selections onto the fetched items. Any failure —
missing CLI, bad JSON, unknown ids — falls back to rule-based ranking so the
pipeline always produces a digest.

Also maintains data/latest.json and data/index.json for the front end.

Usage:
    python scripts/curate.py [--date YYYY-MM-DD] [--mode auto|claude|fallback]
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from fallback_rank import SECTION_LIMITS, SECTION_TITLES, build_fallback_digest

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = REPO_ROOT / "curation" / "prompt.md"
CLAUDE_TIMEOUT_S = 600


def run_claude(raw: dict) -> dict:
    """Invoke `claude -p` and return the parsed curation JSON. Raises on failure."""
    compact_items = [
        {
            "id": i["id"],
            "title": i["title"],
            "source": i["source"],
            "category": i["category"],
            "score": i.get("score"),
        }
        for i in raw["items"]
    ]
    prompt = (
        PROMPT_PATH.read_text()
        + "\n\nToday's items:\n"
        + json.dumps(compact_items, indent=1)
    )
    result = subprocess.run(
        ["claude", "-p", "--output-format", "text"],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=CLAUDE_TIMEOUT_S,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"claude exited {result.returncode}: "
            f"stderr={result.stderr[:400]!r} stdout={result.stdout[:400]!r}"
        )

    # Be tolerant of stray text/fences around the JSON object.
    text = result.stdout
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"no JSON object in claude output: {text[:300]!r}")
    curation = json.loads(text[start : end + 1])

    if "overview" not in curation or "selections" not in curation:
        raise ValueError("curation JSON missing 'overview' or 'selections'")
    return curation


def build_claude_digest(raw: dict, curation: dict) -> dict:
    items_by_id = {i["id"]: i for i in raw["items"]}
    sections = {
        cat: {"category": cat, "title": title, "items": []}
        for cat, title in SECTION_TITLES.items()
    }
    for sel in curation["selections"]:
        item = items_by_id.get(sel.get("id"))
        if item is None:
            continue  # Claude hallucinated an id; skip it
        section = sections.get(item["category"])
        if section is None or len(section["items"]) >= SECTION_LIMITS[item["category"]]:
            continue
        section["items"].append(
            {
                "title": item["title"],
                "url": item["url"],
                "source": item["source"],
                "score": item.get("score"),
                "summary": sel.get("summary"),
            }
        )
    if not any(s["items"] for s in sections.values()):
        raise ValueError("claude selections matched zero fetched items")
    return {
        "date": raw["date"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "claude",
        "overview": curation["overview"],
        "sections": list(sections.values()),
    }


def update_site_data(digest: dict) -> None:
    data_dir = REPO_ROOT / "data"
    (data_dir / "latest.json").write_text(json.dumps(digest, indent=2))

    index_path = data_dir / "index.json"
    index = {"dates": []}
    if index_path.exists():
        index = json.loads(index_path.read_text())
    if digest["date"] not in index["dates"]:
        index["dates"].append(digest["date"])
    index["dates"] = sorted(index["dates"], reverse=True)
    index_path.write_text(json.dumps(index, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d")
    )
    parser.add_argument(
        "--mode", choices=["auto", "claude", "fallback"], default="auto",
        help="auto: try claude, fall back on failure",
    )
    args = parser.parse_args()

    raw_path = REPO_ROOT / "data" / "raw" / f"{args.date}.json"
    raw = json.loads(raw_path.read_text())

    digest = None
    if args.mode in ("auto", "claude"):
        try:
            print(f"[info] running Claude curation on {raw['item_count']} items...")
            digest = build_claude_digest(raw, run_claude(raw))
            print("[ok]   Claude curation succeeded")
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] Claude curation failed: {exc}", file=sys.stderr)
            if args.mode == "claude":
                sys.exit(1)
    if digest is None:
        print("[info] using rule-based fallback ranking")
        digest = build_fallback_digest(raw)

    out_dir = REPO_ROOT / "data" / "digest"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.date}.json"
    out_path.write_text(json.dumps(digest, indent=2))
    update_site_data(digest)
    total = sum(len(s["items"]) for s in digest["sections"])
    print(
        f"[done] {digest['mode']} digest with {total} items -> "
        f"{out_path.relative_to(REPO_ROOT)}"
    )


if __name__ == "__main__":
    main()
