"""
Daily eval report — sends a Telegram summary of yesterday's lesson evaluations.
Run via cron: 0 9 * * * cd /opt/school-bot && .venv/bin/python daily_report.py
"""

import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

DB_PATH = Path(__file__).parent / "evaluations.db"
BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN", "")
CHAT_ID = os.getenv("ADMIN_CHAT_ID", "")
SERVER_URL = os.getenv("SERVER_URL", "https://edtale.ru")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")


def get_yesterday_stats():
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    today = datetime.now().strftime("%Y-%m-%d")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        """SELECT * FROM evaluations
           WHERE created_at >= ? AND created_at < ?
           ORDER BY total_score ASC""",
        (yesterday, today)
    ).fetchall()

    if not rows:
        conn.close()
        return None

    evals = [dict(r) for r in rows]
    total = len(evals)
    scores = [e["total_score"] for e in evals]
    avg_score = sum(scores) / total
    min_score = min(scores)
    max_score = max(scores)
    critical_total = sum(e["critical_count"] for e in evals)
    perfect = sum(1 for e in evals if e["critical_count"] == 0 and e["failed"] == 0)

    # Worst lessons (score < 90)
    worst = [e for e in evals if e["total_score"] < 90]

    # New open recommendations from yesterday
    open_recs = conn.execute(
        """SELECT COUNT(*) FROM recommendations
           WHERE created_at >= ? AND created_at < ? AND status IN ('open', 'reopened')""",
        (yesterday, today)
    ).fetchone()[0]

    # Reopened recommendations
    reopened = conn.execute(
        """SELECT COUNT(*) FROM recommendations
           WHERE created_at >= ? AND created_at < ? AND status = 'reopened'""",
        (yesterday, today)
    ).fetchone()[0]

    conn.close()

    return {
        "date": yesterday,
        "total": total,
        "avg_score": round(avg_score, 1),
        "min_score": min_score,
        "max_score": max_score,
        "critical_total": critical_total,
        "perfect": perfect,
        "worst": worst[:5],
        "open_recs": open_recs,
        "reopened": reopened,
    }


def send_report():
    stats = get_yesterday_stats()

    if not stats:
        # No lessons yesterday — send short message
        httpx.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": f"📊 <b>EdTale Daily Report</b>\n\nВчера уроков не было.",
                "parse_mode": "HTML",
            },
            timeout=10,
        )
        return

    # Score emoji
    if stats["avg_score"] >= 95:
        score_emoji = "🟢"
    elif stats["avg_score"] >= 80:
        score_emoji = "🟡"
    else:
        score_emoji = "🔴"

    lines = [
        f"📊 <b>EdTale Daily Report — {stats['date']}</b>",
        "",
        f"📚 Уроков: <b>{stats['total']}</b>",
        f"{score_emoji} Средняя оценка: <b>{stats['avg_score']}/100</b>  (min {stats['min_score']}, max {stats['max_score']})",
        f"✅ Идеальных: <b>{stats['perfect']}</b> из {stats['total']}",
    ]

    if stats["critical_total"] > 0:
        lines.append(f"❌ Критических ошибок: <b>{stats['critical_total']}</b>")

    if stats["open_recs"] > 0:
        lines.append(f"📋 Новых рекомендаций: <b>{stats['open_recs']}</b>")

    if stats["reopened"] > 0:
        lines.append(f"🔄 Повторных ошибок: <b>{stats['reopened']}</b>")

    if stats["worst"]:
        lines.append("")
        lines.append("⚠️ <b>Требуют внимания:</b>")
        for w in stats["worst"]:
            lines.append(
                f"  • <a href=\"{SERVER_URL}/e/{w['content_id']}\">{w['content_id']}</a>"
                f" — {w['total_score']}/100 ({w['critical_count']} крит.)"
            )

    if ADMIN_PASSWORD:
        lines.append("")
        lines.append(f"📊 <a href=\"{SERVER_URL}/admin/evals?password={ADMIN_PASSWORD}\">Открыть дашборд</a>")

    text = "\n".join(lines)

    httpx.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=10,
    )
    print(f"Report sent: {stats['total']} lessons, avg {stats['avg_score']}")


if __name__ == "__main__":
    send_report()
