"""
Lesson Evaluator — автоматическая проверка качества уроков.

Анализирует JSON урока по ~20 параметрам, считает скоринг,
сохраняет результаты в SQLite и отправляет уведомления в Telegram
при критических ошибках.
"""

import hashlib
import json
import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import httpx

logger = logging.getLogger("school-bot.evaluator")

DB_PATH = Path(__file__).parent / "evaluations.db"

VOWELS = set("аоуыэяеёюиАОУЫЭЯЕЁЮИ")


def _get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_id TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            total_score REAL NOT NULL,
            passed INTEGER NOT NULL,
            failed INTEGER NOT NULL,
            warnings INTEGER NOT NULL DEFAULT 0,
            critical_count INTEGER NOT NULL DEFAULT 0,
            checks_json TEXT NOT NULL,
            notified INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_id TEXT,
            eval_id INTEGER,
            category TEXT NOT NULL,
            check_name TEXT NOT NULL,
            description TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'warning',
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            fixed_at TEXT,
            pattern_hash TEXT,
            FOREIGN KEY (eval_id) REFERENCES evaluations(id)
        );

        CREATE INDEX IF NOT EXISTS idx_rec_status ON recommendations(status);
        CREATE INDEX IF NOT EXISTS idx_rec_pattern ON recommendations(pattern_hash);
        CREATE INDEX IF NOT EXISTS idx_eval_content ON evaluations(content_id);
        CREATE INDEX IF NOT EXISTS idx_eval_created ON evaluations(created_at);
    """)
    conn.close()


# ── Check result ──────────────────────────────────────────────────────────────

class CheckResult:
    def __init__(self, name: str, category: str, passed: bool,
                 severity: str = "warning", detail: str = "",
                 display_name: str = ""):
        self.name = name
        self.category = category
        self.passed = passed
        self.severity = severity  # "critical", "warning", "info"
        self.detail = detail
        self.display_name = display_name or name

    def to_dict(self):
        return {
            "name": self.name,
            "display_name": self.display_name,
            "category": self.category,
            "passed": self.passed,
            "severity": self.severity,
            "detail": self.detail,
        }


# ── Helper functions ──────────────────────────────────────────────────────────

def _count_syllables(word: str) -> int:
    """Count syllables in a Russian word (= number of vowels)."""
    return sum(1 for c in word if c in VOWELS)


def _is_numeric_option(text: str) -> bool:
    """Check if text looks like a numeric answer (including negative, fractions)."""
    cleaned = text.strip().replace(" ", "").replace(",", ".")
    return bool(re.match(r'^[+-]?[\d./]+$', cleaned))


# ── Evaluation checks ────────────────────────────────────────────────────────

CHECK_DISPLAY_NAMES = {
    "title_exists": "Заголовок урока",
    "story_blocks_count": "Количество блоков теории (3-4)",
    "tasks_count": "Количество заданий (5)",
    "task_types_order": "Порядок типов заданий",
    "required_fields": "Обязательные поля заданий",
    "quiz_correct_in_options": "Quiz: ответ есть в вариантах",
    "mc_correct_in_options": "Multiple choice: ответы в вариантах",
    "dnd_mapping_valid": "Drag&drop: маппинг корректен",
    "fitb_correct_nonempty": "Fill in blank: ответ не пустой",
    "fitb_no_answer_leak": "Fill in blank: ответ не в вопросе",
    "ordering_items_match": "Ordering: элементы совпадают",
    "no_asterisks": "Нет звёздочек (**) в тексте",
    "no_latex": "Нет LaTeX ($) в тексте",
    "blocks_not_empty": "Блоки теории содержательные",
    "questions_not_empty": "Вопросы заданий содержательные",
    "distractors_same_type": "Дистракторы одного типа данных",
    "name_in_first_block": "Обращение по имени (1й блок)",
    "emoji_in_blocks": "Эмодзи в блоках теории",
    "dnd_syllable_check": "Drag&drop: подсчёт слогов верный",
    "mc_syllable_check": "Multiple choice: подсчёт слогов верный",
    "quiz_syllable_check": "Quiz: подсчёт слогов верный",
}


def evaluate_lesson(lesson_json: dict) -> list[CheckResult]:
    """Run all checks on a lesson JSON and return list of CheckResult."""
    results = []
    title = lesson_json.get("title", "")
    blocks = lesson_json.get("story_blocks", [])
    tasks = lesson_json.get("tasks", [])

    # Detect topic hints for specialized checks
    full_text_lower = json.dumps(lesson_json, ensure_ascii=False).lower()
    title_lower = title.lower()
    is_syllable_topic = any(w in title_lower for w in ["слог", "слога", "слогов", "слоги"]) or \
        (any(w in full_text_lower for w in ["блок-слог", "блока-слога", "блоков-слогов"]) and
         "слог" in full_text_lower)
    is_math_topic = any(w in full_text_lower for w in [
        "делени", "умножен", "сложен", "вычитан", "дроб", "числител", "знаменател",
        "уравнен", "выражен", "пример",
    ])

    # ══════════════════════════════════════════════════════════════════════════
    # STRUCTURE
    # ══════════════════════════════════════════════════════════════════════════

    results.append(CheckResult(
        "title_exists", "structure",
        bool(title and len(title.strip()) > 3),
        "critical",
        f"«{title[:60]}»" if title else "Заголовок отсутствует",
        CHECK_DISPLAY_NAMES.get("title_exists"),
    ))

    results.append(CheckResult(
        "story_blocks_count", "structure",
        3 <= len(blocks) <= 4,
        "warning",
        f"Найдено {len(blocks)} (ожидалось 3-4)",
        CHECK_DISPLAY_NAMES.get("story_blocks_count"),
    ))

    results.append(CheckResult(
        "tasks_count", "structure",
        len(tasks) == 5,
        "critical",
        f"Найдено {len(tasks)} (ожидалось 5)",
        CHECK_DISPLAY_NAMES.get("tasks_count"),
    ))

    expected_order = ["quiz", "multiple_choice", "drag_and_drop", "fill_in_the_blank", "ordering"]
    actual_order = [t.get("type") for t in tasks]
    results.append(CheckResult(
        "task_types_order", "structure",
        actual_order == expected_order,
        "warning",
        f"Порядок: {' → '.join(actual_order)}",
        CHECK_DISPLAY_NAMES.get("task_types_order"),
    ))

    # Required fields per task type
    required_fields_map = {
        "quiz": ["question", "options", "correct"],
        "multiple_choice": ["question", "options", "correct"],
        "drag_and_drop": ["question", "items", "zones", "correct"],
        "fill_in_the_blank": ["question", "correct"],
        "ordering": ["question", "items", "correct_order"],
    }
    all_fields_ok = True
    field_details = []
    for i, task in enumerate(tasks):
        ttype = task.get("type", "unknown")
        req = required_fields_map.get(ttype, [])
        missing = [f for f in req if f not in task or not task[f]]
        if missing:
            all_fields_ok = False
            field_details.append(f"Задание {i+1} ({ttype}): нет {missing}")
    results.append(CheckResult(
        "required_fields", "structure",
        all_fields_ok,
        "critical",
        "; ".join(field_details) if field_details else "Все поля на месте",
        CHECK_DISPLAY_NAMES.get("required_fields"),
    ))

    # ══════════════════════════════════════════════════════════════════════════
    # ANSWERS
    # ══════════════════════════════════════════════════════════════════════════

    for i, task in enumerate(tasks):
        ttype = task.get("type", "unknown")

        if ttype == "quiz":
            opts = task.get("options", [])
            corr = task.get("correct", "")
            ok = corr in opts
            results.append(CheckResult(
                "quiz_correct_in_options", "answers", ok, "critical",
                f"«{corr}» {'✓ найден' if ok else '✗ НЕ найден'} в вариантах",
                CHECK_DISPLAY_NAMES.get("quiz_correct_in_options"),
            ))

            # Syllable check for quiz
            if is_syllable_topic and corr and re.match(r'^\d+$', corr.strip()):
                q = task.get("question", "")
                # Try to extract the word being asked about
                word_match = re.search(r'(?:слов[оае]\s+)?[«"\']([\w]+)[»"\']', q)
                if not word_match:
                    word_match = re.search(r'(?:слов[оае]\s+)([\w]+)', q)
                if word_match:
                    word = word_match.group(1)
                    expected = _count_syllables(word)
                    actual_answer = int(corr.strip())
                    ok = expected == actual_answer
                    results.append(CheckResult(
                        "quiz_syllable_check", "answers", ok, "critical",
                        f"«{word}»: {expected} слогов (гласных), ответ: {actual_answer}",
                        CHECK_DISPLAY_NAMES.get("quiz_syllable_check"),
                    ))

        elif ttype == "multiple_choice":
            opts = task.get("options", [])
            corr = task.get("correct", [])
            all_in = all(c in opts for c in corr)
            ok = all_in and len(corr) > 0
            results.append(CheckResult(
                "mc_correct_in_options", "answers", ok, "critical",
                f"Правильные: {corr}" + ("" if ok else " — не все в вариантах!"),
                CHECK_DISPLAY_NAMES.get("mc_correct_in_options"),
            ))

            # Syllable check for multiple_choice
            if is_syllable_topic:
                q = task.get("question", "")
                # Extract target syllable count from question
                target_match = re.search(r'(\d+)\s*(?:блок|слог)', q.lower())
                if target_match:
                    target_count = int(target_match.group(1))
                    wrong_items = []
                    for c in corr:
                        actual = _count_syllables(c)
                        if actual != target_count:
                            wrong_items.append(f"«{c}»={actual}")
                    # Also check that non-correct options are indeed wrong
                    missed_items = []
                    for o in opts:
                        if o not in corr and _count_syllables(o) == target_count:
                            missed_items.append(f"«{o}»={_count_syllables(o)}")
                    ok = len(wrong_items) == 0 and len(missed_items) == 0
                    detail_parts = []
                    if wrong_items:
                        detail_parts.append(f"Неверно помечены как правильные: {', '.join(wrong_items)}")
                    if missed_items:
                        detail_parts.append(f"Пропущены верные: {', '.join(missed_items)}")
                    if not detail_parts:
                        detail_parts.append(f"Все {target_count}-слоговые слова определены верно")
                    results.append(CheckResult(
                        "mc_syllable_check", "answers", ok, "critical",
                        "; ".join(detail_parts),
                        CHECK_DISPLAY_NAMES.get("mc_syllable_check"),
                    ))

        elif ttype == "drag_and_drop":
            items = task.get("items", [])
            zones = task.get("zones", [])
            correct = task.get("correct", {})
            all_mapped = all(item in correct for item in items)
            zones_valid = all(z in zones for z in correct.values())
            ok = all_mapped and zones_valid
            results.append(CheckResult(
                "dnd_mapping_valid", "answers", ok, "critical",
                f"Маппинг: {'корректен' if ok else 'ОШИБКА — элементы или зоны не совпадают'}",
                CHECK_DISPLAY_NAMES.get("dnd_mapping_valid"),
            ))

            # Syllable check for drag_and_drop
            if is_syllable_topic:
                wrong_mappings = []
                for item, zone in correct.items():
                    actual_syllables = _count_syllables(item)
                    # Try to extract number from zone name
                    zone_num_match = re.search(r'(\d+)', zone)
                    if zone_num_match:
                        expected_syllables = int(zone_num_match.group(1))
                        if actual_syllables != expected_syllables:
                            wrong_mappings.append(
                                f"«{item}»={actual_syllables} слогов → зона «{zone}»"
                            )
                if wrong_mappings or (is_syllable_topic and correct):
                    results.append(CheckResult(
                        "dnd_syllable_check", "answers",
                        len(wrong_mappings) == 0,
                        "critical",
                        "; ".join(wrong_mappings) if wrong_mappings else "Все слова в правильных зонах",
                        CHECK_DISPLAY_NAMES.get("dnd_syllable_check"),
                    ))

        elif ttype == "fill_in_the_blank":
            corr = task.get("correct", "")
            results.append(CheckResult(
                "fitb_correct_nonempty", "answers",
                bool(corr and corr.strip()),
                "critical",
                f"Ответ: «{corr}»" if corr else "Ответ пустой!",
                CHECK_DISPLAY_NAMES.get("fitb_correct_nonempty"),
            ))
            q = task.get("question", "")
            # Check answer not leaked (exact match in question)
            leaked = False
            if corr and corr.strip():
                # Check if answer appears in question outside of example context
                answer_lower = corr.strip().lower()
                q_lower = q.lower()
                # Remove the example hint part (e.g., "(например: X)")
                q_no_example = re.sub(r'\(например[^)]*\)', '', q_lower)
                if answer_lower in q_no_example and len(answer_lower) > 1:
                    leaked = True
            results.append(CheckResult(
                "fitb_no_answer_leak", "answers",
                not leaked,
                "warning",
                f"Ответ «{corr}» найден в тексте вопроса!" if leaked else "Ответ не раскрыт",
                CHECK_DISPLAY_NAMES.get("fitb_no_answer_leak"),
            ))

        elif ttype == "ordering":
            items = set(task.get("items", []))
            order = set(task.get("correct_order", []))
            ok = items == order and len(items) > 0
            results.append(CheckResult(
                "ordering_items_match", "answers", ok, "critical",
                "Наборы совпадают" if ok else f"items: {items}, correct_order: {order}",
                CHECK_DISPLAY_NAMES.get("ordering_items_match"),
            ))

    # ══════════════════════════════════════════════════════════════════════════
    # CONTENT QUALITY
    # ══════════════════════════════════════════════════════════════════════════

    text_content = title + " " + " ".join(b.get("text", "") for b in blocks)
    text_content += " " + " ".join(t.get("question", "") for t in tasks)

    results.append(CheckResult(
        "no_asterisks", "content",
        "**" not in text_content,
        "warning",
        "Найдены ** в тексте" if "**" in text_content else "Чисто",
        CHECK_DISPLAY_NAMES.get("no_asterisks"),
    ))

    results.append(CheckResult(
        "no_latex", "content",
        "$" not in text_content,
        "warning",
        "Найден $ в тексте" if "$" in text_content else "Чисто",
        CHECK_DISPLAY_NAMES.get("no_latex"),
    ))

    short_blocks = [i+1 for i, b in enumerate(blocks) if len(b.get("text", "").strip()) < 20]
    results.append(CheckResult(
        "blocks_not_empty", "content",
        len(short_blocks) == 0,
        "warning",
        f"Короткие блоки: {short_blocks}" if short_blocks else "Все блоки содержательные",
        CHECK_DISPLAY_NAMES.get("blocks_not_empty"),
    ))

    short_questions = [i+1 for i, t in enumerate(tasks) if len(t.get("question", "").strip()) < 10]
    results.append(CheckResult(
        "questions_not_empty", "content",
        len(short_questions) == 0,
        "warning",
        f"Короткие вопросы: {short_questions}" if short_questions else "Все вопросы содержательные",
        CHECK_DISPLAY_NAMES.get("questions_not_empty"),
    ))

    # ══════════════════════════════════════════════════════════════════════════
    # DISTRACTORS
    # ══════════════════════════════════════════════════════════════════════════

    for i, task in enumerate(tasks):
        ttype = task.get("type")
        if ttype in ("quiz", "multiple_choice"):
            opts = task.get("options", [])
            corr = task.get("correct") if ttype == "quiz" else (task.get("correct", []) or [""])[0]
            if corr and opts and _is_numeric_option(str(corr)):
                non_numeric = [o for o in opts if not _is_numeric_option(str(o))]
                if non_numeric:  # only add check if there's an issue
                    results.append(CheckResult(
                        "distractors_same_type", "distractors",
                        False,
                        "warning",
                        f"Задание {i+1}: нечисловые варианты в числовом вопросе: {non_numeric}",
                        CHECK_DISPLAY_NAMES.get("distractors_same_type"),
                    ))

    # ══════════════════════════════════════════════════════════════════════════
    # PEDAGOGY
    # ══════════════════════════════════════════════════════════════════════════

    if blocks:
        first_text = blocks[0].get("text", "").lower()
        # Check for common name patterns (Привет/Здравствуй + comma + name)
        has_name = bool(re.search(r'(привет|здравствуй|добро пожаловать|приветствую|дорог[ойая])\s*[,!]?\s*\w+', first_text))
        results.append(CheckResult(
            "name_in_first_block", "pedagogy",
            has_name,
            "info",
            "Есть приветствие по имени" if has_name else "Нет обращения по имени в первом блоке",
            CHECK_DISPLAY_NAMES.get("name_in_first_block"),
        ))

    has_emoji = all(b.get("emoji") for b in blocks)
    results.append(CheckResult(
        "emoji_in_blocks", "pedagogy",
        has_emoji,
        "info",
        "Все блоки с эмодзи" if has_emoji else "Некоторые блоки без эмодзи",
        CHECK_DISPLAY_NAMES.get("emoji_in_blocks"),
    ))

    return results


# ── Scoring ───────────────────────────────────────────────────────────────────

def score_results(results: list[CheckResult]) -> tuple[float, int, int, int]:
    """Returns (score 0-100, passed, failed, critical_count)."""
    if not results:
        return 0.0, 0, 0, 0

    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    critical = sum(1 for r in results if not r.passed and r.severity == "critical")

    score = (passed / len(results)) * 100
    # Extra penalty for critical errors
    score = max(0, score - critical * 5)
    return round(score, 1), passed, failed, critical


# ── Persistence ───────────────────────────────────────────────────────────────

def save_evaluation(content_id: str, results: list[CheckResult]) -> int:
    """Save evaluation to DB, create/reopen recommendations. Returns eval_id."""
    score, passed, failed, critical = score_results(results)
    warnings = sum(1 for r in results if not r.passed and r.severity == "warning")

    conn = _get_conn()
    cur = conn.execute(
        """INSERT INTO evaluations
           (content_id, total_score, passed, failed, warnings, critical_count, checks_json)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (content_id, score, passed, failed, warnings, critical,
         json.dumps([r.to_dict() for r in results], ensure_ascii=False))
    )
    eval_id = cur.lastrowid

    for r in results:
        if r.passed:
            continue
        pattern_hash = hashlib.md5(
            f"{r.name}:{r.detail}".encode()
        ).hexdigest()[:12]

        existing = conn.execute(
            """SELECT id, status FROM recommendations
               WHERE pattern_hash = ? AND status IN ('fixed','archived')
               ORDER BY id DESC LIMIT 1""",
            (pattern_hash,)
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE recommendations
                   SET status='reopened', content_id=?, eval_id=?, created_at=datetime('now')
                   WHERE id=?""",
                (content_id, eval_id, existing["id"])
            )
        else:
            conn.execute(
                """INSERT INTO recommendations
                   (content_id, eval_id, category, check_name, description, severity, pattern_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (content_id, eval_id, r.category, r.name, r.detail, r.severity, pattern_hash)
            )

    conn.commit()
    conn.close()
    return eval_id


# ── Telegram notification ─────────────────────────────────────────────────────

def notify_telegram(content_id: str, results: list[CheckResult],
                    bot_token: str, chat_id: str, server_url: str) -> None:
    """Send Telegram alert for critical errors."""
    critical = [r for r in results if not r.passed and r.severity == "critical"]
    if not critical or not bot_token or not chat_id:
        return

    score, passed, failed, _ = score_results(results)
    total = passed + failed

    lines = [
        f"⚠️ <b>Урок {content_id}</b> — оценка <b>{score}/100</b> ({passed}/{total})",
        f"🔗 {server_url}/e/{content_id}",
        f"📊 {server_url}/admin/evals?password=ADMIN",
        "",
    ]
    for r in critical:
        lines.append(f"❌ <b>{r.display_name}</b>")
        lines.append(f"    {r.detail}")

    warns = [r for r in results if not r.passed and r.severity == "warning"]
    if warns:
        lines.append(f"\n⚠️ + {len(warns)} предупреждений")

    try:
        httpx.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": "\n".join(lines), "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception:
        logger.exception("Failed to send eval notification to Telegram")


# ── Main entry point ──────────────────────────────────────────────────────────

def run_evaluation(content_id: str, lesson_json: dict,
                   bot_token: str = "", chat_id: str = "",
                   server_url: str = "") -> dict:
    """Full pipeline: evaluate → score → save → notify."""
    results = evaluate_lesson(lesson_json)
    score, passed, failed, critical = score_results(results)
    eval_id = save_evaluation(content_id, results)

    if critical > 0:
        notify_telegram(content_id, results, bot_token, chat_id, server_url)

    return {
        "eval_id": eval_id,
        "score": score,
        "passed": passed,
        "failed": failed,
        "critical": critical,
    }


# ── Query helpers (for dashboard) ─────────────────────────────────────────────

def get_recent_evaluations(limit: int = 50) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        """SELECT id, content_id, created_at, total_score, passed, failed,
                  warnings, critical_count
           FROM evaluations ORDER BY created_at DESC LIMIT ?""",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_evaluation_detail(eval_id: int) -> dict | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM evaluations WHERE id = ?", (eval_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_evaluation_by_content(content_id: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM evaluations WHERE content_id = ? ORDER BY id DESC LIMIT 1",
        (content_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_recommendations(status_filter: str = "open") -> list[dict]:
    conn = _get_conn()
    if status_filter == "all":
        rows = conn.execute(
            "SELECT * FROM recommendations ORDER BY created_at DESC LIMIT 200"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM recommendations WHERE status = ? ORDER BY created_at DESC LIMIT 200",
            (status_filter,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_recommendation_status(rec_id: int, new_status: str) -> bool:
    conn = _get_conn()
    fixed_at = datetime.now().isoformat() if new_status in ("fixed", "archived") else None
    conn.execute(
        "UPDATE recommendations SET status = ?, fixed_at = ? WHERE id = ?",
        (new_status, fixed_at, rec_id)
    )
    conn.commit()
    conn.close()
    return True


def get_stats_summary() -> dict:
    conn = _get_conn()
    total = conn.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0]
    avg_score = conn.execute("SELECT COALESCE(AVG(total_score), 0) FROM evaluations").fetchone()[0]
    total_critical = conn.execute("SELECT COALESCE(SUM(critical_count), 0) FROM evaluations").fetchone()[0]
    perfect = conn.execute("SELECT COUNT(*) FROM evaluations WHERE critical_count = 0 AND failed = 0").fetchone()[0]
    open_recs = conn.execute("SELECT COUNT(*) FROM recommendations WHERE status IN ('open','reopened')").fetchone()[0]

    # Score distribution
    buckets = {"0-20": 0, "21-40": 0, "41-60": 0, "61-80": 0, "81-100": 0}
    rows = conn.execute("SELECT total_score FROM evaluations").fetchall()
    for r in rows:
        s = r[0]
        if s <= 20: buckets["0-20"] += 1
        elif s <= 40: buckets["21-40"] += 1
        elif s <= 60: buckets["41-60"] += 1
        elif s <= 80: buckets["61-80"] += 1
        else: buckets["81-100"] += 1

    # Daily scores (last 30 days)
    daily = conn.execute(
        """SELECT DATE(created_at) as day, AVG(total_score) as avg_score, COUNT(*) as cnt
           FROM evaluations
           WHERE created_at >= datetime('now', '-30 days')
           GROUP BY DATE(created_at) ORDER BY day"""
    ).fetchall()

    # Most common failures
    common_fails = conn.execute(
        """SELECT check_name, COUNT(*) as cnt
           FROM recommendations WHERE status IN ('open','reopened')
           GROUP BY check_name ORDER BY cnt DESC LIMIT 10"""
    ).fetchall()

    conn.close()
    return {
        "total_lessons": total,
        "avg_score": round(avg_score, 1),
        "total_critical": total_critical,
        "perfect_lessons": perfect,
        "open_recommendations": open_recs,
        "score_distribution": buckets,
        "daily_scores": [{"day": d[0], "avg": round(d[1], 1), "count": d[2]} for d in daily],
        "common_failures": [{"check": f[0], "count": f[1]} for f in common_fails],
    }
