#!/usr/bin/env python3
"""Email the day's digest to a Gmail inbox via SMTP.

Reads data/digest/<date>.json — the same file the site renders — and sends it as
a multipart HTML + plain-text email. Stdlib only: no new dependencies.

Auth is a Gmail app password (requires 2-Step Verification on the account), read
from the environment. If the credentials aren't configured the script exits 0
without sending, so local runs and forks don't fail.

Usage:
    python scripts/send_email.py [--date YYYY-MM-DD] [--dry-run PATH]

Environment:
    GMAIL_ADDRESS       sender address, also the default recipient
    GMAIL_APP_PASSWORD  16-char app password from myaccount.google.com/apppasswords
    DIGEST_RECIPIENT    optional override for the recipient
"""

from __future__ import annotations

import argparse
import json
import os
import smtplib
import ssl
import sys
from datetime import datetime, timezone
from email.message import EmailMessage
from html import escape
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE_URL = "https://srijit316.github.io/daily_research_digest/"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465

# Mirrors SECTION_ICONS in site/app.js so the email reads like the site.
SECTION_ICONS = {"tech": "💻", "cricket": "🏏", "football": "⚽", "nba": "🏀"}

# Email clients strip <style> blocks, so every rule is an inline attribute.
BODY_STYLE = (
    "margin:0;padding:24px 12px;background:#f4f5f7;"
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"
)
CARD_STYLE = (
    "max-width:600px;margin:0 auto;background:#ffffff;border-radius:12px;"
    "padding:28px 24px;"
)
TITLE_STYLE = (
    "color:#1a4fd6;text-decoration:none;font-size:16px;font-weight:600;"
    "line-height:1.35;"
)
SUMMARY_STYLE = "margin:6px 0 0;color:#3c4149;font-size:14px;line-height:1.55;"
META_STYLE = "margin:6px 0 0;color:#8a9099;font-size:12px;"
HEADING_STYLE = (
    "margin:32px 0 12px;padding-bottom:8px;border-bottom:2px solid #e6e8eb;"
    "color:#14181d;font-size:19px;"
)
ITEM_STYLE = "margin:0 0 18px;"


def format_date(iso: str) -> str:
    """2026-07-18 -> Saturday, July 18, 2026 (falls back to the raw string)."""
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%A, %B %-d, %Y")
    except ValueError:
        return iso


def mode_label(mode: str) -> str:
    return "AI curated" if mode == "claude" else "auto-ranked"


def render_html(digest: dict) -> str:
    parts = [
        f'<div style="{BODY_STYLE}"><div style="{CARD_STYLE}">',
        f'<p style="margin:0;color:#8a9099;font-size:12px;'
        f'text-transform:uppercase;letter-spacing:.08em;">Daily Digest &middot; '
        f"{escape(mode_label(digest['mode']))}</p>",
        f'<h1 style="margin:6px 0 20px;color:#14181d;font-size:22px;">'
        f"{escape(format_date(digest['date']))}</h1>",
        f'<p style="margin:0;padding:16px;background:#f4f5f7;border-radius:8px;'
        f'color:#3c4149;font-size:14px;line-height:1.6;">'
        f"{escape(digest.get('overview') or '')}</p>",
    ]

    for section in digest.get("sections", []):
        items = section.get("items") or []
        if not items:
            continue  # a source can fail and leave a category empty
        icon = SECTION_ICONS.get(section.get("category"), "📌")
        parts.append(
            f'<h2 style="{HEADING_STYLE}">{icon} {escape(section.get("title", ""))}</h2>'
        )
        for item in items:
            parts.append(f'<div style="{ITEM_STYLE}">')
            parts.append(
                f'<a href="{escape(item.get("url") or "", quote=True)}" '
                f'style="{TITLE_STYLE}">{escape(item.get("title") or "")}</a>'
            )
            if item.get("summary"):
                parts.append(
                    f'<p style="{SUMMARY_STYLE}">{escape(item["summary"])}</p>'
                )
            meta = escape(item.get("source") or "")
            if item.get("score") is not None:
                meta += f" &nbsp;&middot;&nbsp; &#9650; {item['score']}"
            parts.append(f'<p style="{META_STYLE}">{meta}</p>')
            parts.append("</div>")

    parts.append(
        f'<p style="margin:32px 0 0;padding-top:16px;border-top:1px solid #e6e8eb;'
        f'color:#8a9099;font-size:12px;line-height:1.6;">'
        f'<a href="{SITE_URL}" style="color:#1a4fd6;">Browse the archive</a><br>'
        f"Generated {escape(digest.get('generated_at', ''))} &middot; "
        f"mode: {escape(digest.get('mode', ''))}</p>"
    )
    parts.append("</div></div>")
    return "".join(parts)


def render_text(digest: dict) -> str:
    lines = [
        f"DAILY DIGEST — {format_date(digest['date'])} ({mode_label(digest['mode'])})",
        "",
        digest.get("overview") or "",
    ]
    for section in digest.get("sections", []):
        items = section.get("items") or []
        if not items:
            continue
        lines += ["", f"== {section.get('title', '')} ==", ""]
        for item in items:
            lines.append(f"* {item.get('title') or ''}")
            lines.append(f"  {item.get('url') or ''}")
            if item.get("summary"):
                lines.append(f"  {item['summary']}")
            meta = item.get("source") or ""
            if item.get("score") is not None:
                meta += f" · ▲ {item['score']}"
            lines += [f"  {meta}", ""]
    lines += ["", f"Archive: {SITE_URL}"]
    return "\n".join(lines)


def build_message(digest: dict, sender: str, recipient: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"Daily Digest — {format_date(digest['date'])}"
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(render_text(digest))
    msg.add_alternative(render_html(digest), subtype="html")
    return msg


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d")
    )
    parser.add_argument(
        "--dry-run",
        metavar="PATH",
        help="write the rendered HTML here instead of sending",
    )
    args = parser.parse_args()

    digest_path = REPO_ROOT / "data" / "digest" / f"{args.date}.json"
    if not digest_path.exists():
        print(f"[warn] no digest at {digest_path}, nothing to send", file=sys.stderr)
        sys.exit(1)
    digest = json.loads(digest_path.read_text())

    if args.dry_run:
        out = Path(args.dry_run)
        out.write_text(render_html(digest))
        print(f"[done] rendered preview -> {out}")
        return

    sender = os.environ.get("GMAIL_ADDRESS")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not sender or not password:
        print("[info] GMAIL_ADDRESS/GMAIL_APP_PASSWORD not set — skipping email")
        return
    recipient = os.environ.get("DIGEST_RECIPIENT") or sender

    # App passwords are displayed in space-separated groups of four.
    password = password.replace(" ", "")

    msg = build_message(digest, sender, recipient)
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as smtp:
        smtp.login(sender, password)
        smtp.send_message(msg)

    total = sum(len(s.get("items") or []) for s in digest.get("sections", []))
    print(f"[done] emailed {args.date} digest ({total} items) -> {recipient}")


if __name__ == "__main__":
    main()
