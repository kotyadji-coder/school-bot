import asyncio
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db_logger
from gemini_client import generate_explanation, generate_image_prompt, generate_image_prompt_fallback
from image_generator import generate_image
from smartbot_client import send_message
from content_generator import save_explanation

# TODO: Replace with your actual admin credentials
ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN", "")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change_me")

SERVER_URL = os.getenv("SERVER_URL", "http://localhost:8000")
CONTENT_DIR = Path(__file__).parent / "content"

logger = logging.getLogger("school-bot")


_UNSAFE_KEYWORDS = re.compile(
    r"\b("
    # weapons
    r"оружи[ея]|пистолет|нож|ножи|меч|мечи|ружь[её]|автомат|пулемёт|граната|бомб[аы]|взрывчатк[аи]|топор"
    r"|gun|pistol|rifle|sword|knife|bomb|grenade|weapon|cannon|axe"
    # violence / blood
    r"|насили[ея]|убийств[ао]|убийц[аы]|драк[аи]|убить|убивать|кров[иь]|ран[еёи]ни[ея]|смерт[иь]|мёртв"
    r"|violence|murder|kill|killing|blood|death|dead|dying|gore"
    # horror
    r"|ужас|монстр|призрак|череп|скелет|демон|дьявол|зомби"
    r"|horror|monster|ghost|skull|skeleton|demon|devil|zombie"
    # adult
    r"|секс|порно|голый|голая|нагой"
    r"|sex|porn|nude|naked"
    # alcohol / drugs / smoking
    r"|алкоголь|пиво|водк[аи]|вин[оа]|наркотик|куритель|сигарет"
    r"|alcohol|beer|vodka|drug|drugs|smoking|cigarette"
    r")\b",
    re.IGNORECASE,
)

_SAFE_UNIVERSE_REPLACEMENT = "нейтральный мир приключений"


def _sanitize_question(question: str) -> str:
    """Replace dangerous keywords with a safe universe to protect child content."""
    if _UNSAFE_KEYWORDS.search(question):
        # Remove only the unsafe universe/character part by replacing it with a safe alternative.
        # Strategy: keep everything up to the known structure keywords (class, topic) and swap the universe.
        sanitized = _UNSAFE_KEYWORDS.sub(_SAFE_UNIVERSE_REPLACEMENT, question)
        return sanitized
    return question


def _check_password(password: str):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=403, detail="Forbidden")


def _notify_admin(error_message: str, user_id: str) -> None:
    if not ADMIN_BOT_TOKEN or not ADMIN_CHAT_ID:
        return
    text = f"❌ Ошибка: {error_message}, user: {user_id}"
    try:
        httpx.post(
            f"https://api.telegram.org/bot{ADMIN_BOT_TOKEN}/sendMessage",
            json={"chat_id": ADMIN_CHAT_ID, "text": text},
            timeout=10,
        )
    except Exception:
        logger.exception("Не удалось отправить уведомление администратору")


class GenerateRequest(BaseModel):
    user_id: str
    question: str
    channel_id: str
    callback_url: str | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    CONTENT_DIR.mkdir(exist_ok=True)
    yield


app = FastAPI(lifespan=lifespan)

app.mount("/content", StaticFiles(directory=str(CONTENT_DIR)), name="content")
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


def _generate_and_send(user_id: str, question: str, channel_id: str, callback_url: str | None = None) -> None:
    """Вся тяжёлая работа — в отдельном потоке, чтобы не блокировать HTTP-ответ."""
    try:
        # 0. Sanitize input
        sanitized_question = _sanitize_question(question)
        if sanitized_question != question:
            db_logger.log("WARNING", "INPUT_SANITIZED", "Запрос содержал небезопасные ключевые слова — заменены", user_id=user_id, channel_id=channel_id)
        question = sanitized_question

        # 1. Двухшаговая цепочка: методист → тьютор-геймер (JSON)
        db_logger.log("INFO", "STEP1_START", "Шаг 1: методист", user_id=user_id, channel_id=channel_id)
        methodologist_output, lesson_json = generate_explanation(question)
        db_logger.log("INFO", "STEP1_RESULT", methodologist_output[:500], user_id=user_id, channel_id=channel_id)
        db_logger.log("INFO", "STEP2_RESULT", lesson_json.get("title", "")[:200], user_id=user_id, channel_id=channel_id)

        # Build plain text from story_blocks for image prompt generation
        story_text = "\n".join(b["text"] for b in lesson_json.get("story_blocks", []))

        # 2. Генерируем изображение
        db_logger.log("INFO", "IMAGE_START", "Генерация изображения начата", user_id=user_id, channel_id=channel_id)
        img_prompt = generate_image_prompt(story_text)
        db_logger.log("INFO", "IMAGE_PROMPT", img_prompt[:500], user_id=user_id, channel_id=channel_id)

        try:
            image_bytes = generate_image(img_prompt)
            db_logger.log("INFO", "IMAGE_DONE", "Изображение сгенерировано", user_id=user_id, channel_id=channel_id)
        except Exception as img_err:
            db_logger.log("ERROR", "IMAGE_ERROR", f"Ошибка генерации изображения: {img_err}", user_id=user_id, channel_id=channel_id)
            if "IMAGE_PROHIBITED_CONTENT" in str(img_err):
                db_logger.log("INFO", "IMAGE_FALLBACK", "Пробуем запасной промт (kids cosplay)", user_id=user_id, channel_id=channel_id)
                try:
                    img_prompt_fallback = generate_image_prompt_fallback(story_text)
                    db_logger.log("INFO", "IMAGE_PROMPT_FALLBACK", img_prompt_fallback[:500], user_id=user_id, channel_id=channel_id)
                    image_bytes = generate_image(img_prompt_fallback)
                    db_logger.log("INFO", "IMAGE_DONE", "Изображение сгенерировано (fallback)", user_id=user_id, channel_id=channel_id)
                except Exception as fallback_err:
                    db_logger.log("ERROR", "IMAGE_ERROR_FALLBACK", f"Ошибка fallback генерации: {fallback_err}", user_id=user_id, channel_id=channel_id)
                    image_bytes = None
            else:
                image_bytes = None

        # 3. Рендерим и сохраняем HTML-страницы (web + print)
        content_id = save_explanation(
            image_bytes=image_bytes,
            lesson_json=lesson_json,
            server_url=SERVER_URL,
        )
        db_logger.log("INFO", "EXPLANATION_DONE", f"Урок сохранён: {content_id}", user_id=user_id, channel_id=channel_id)

        # 4. Отправляем через SmartBot
        web_url   = f"{SERVER_URL}/e/{content_id}"
        print_url = f"{SERVER_URL}/e/{content_id}_print"

        try:
            send_message(peer_id=user_id, status="success", channel_id=channel_id, web_url=web_url, print_url=print_url)
            db_logger.log("INFO", "CALLBACK_SENT", f"Ответ отправлен в SmartBot, content_id={content_id}", user_id=user_id, channel_id=channel_id)
        except Exception as cb_err:
            db_logger.log("ERROR", "CALLBACK_ERROR", f"Ошибка отправки в SmartBot: {cb_err}", user_id=user_id, channel_id=channel_id)
            raise

    except Exception as e:
        error_message = str(e)
        db_logger.log("ERROR", "ERROR", f"Необработанная ошибка: {error_message}", user_id=user_id, channel_id=channel_id)
        logger.exception("Ошибка при генерации объяснения для user_id=%s", user_id)
        send_message(peer_id=user_id, status="error", channel_id=channel_id)
        _notify_admin(error_message=error_message, user_id=user_id)
        if callback_url:
            try:
                httpx.post(
                    callback_url,
                    json={"status": "error", "user_id": user_id, "error_message": error_message},
                    timeout=10,
                )
            except Exception:
                logger.exception("Не удалось отправить callback об ошибке")


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = Path(__file__).parent / "templates" / "index.html"
    return html_path.read_text(encoding="utf-8")


@app.post("/generate")
async def generate(request: Request):
    """Принимает запрос и сразу возвращает 200. Генерация идёт в фоне."""
    body_bytes = await request.body()
    body_str = body_bytes.decode("utf-8")
    body_str = re.sub(
        r'("question":\s*"[^"]*)',
        lambda m: m.group(0).replace("\n", " "),
        body_str,
    )
    data = json.loads(body_str)
    req = GenerateRequest(**data)
    db_logger.log(
        "INFO",
        "REQUEST",
        f"Запрос получен: {req.question[:50]}",
        user_id=req.user_id,
        channel_id=req.channel_id,
    )
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _generate_and_send, req.user_id, req.question, req.channel_id, req.callback_url)
    return {"status": "ok"}


@app.get("/e/{content_id}", response_class=HTMLResponse)
async def get_lesson(content_id: str):
    html_path = CONTENT_DIR / f"{content_id}.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="Урок не найден")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()


@app.get("/admin/logs", response_class=HTMLResponse)
async def admin_logs(password: str = Query(...)):
    _check_password(password)
    rows = db_logger.get_recent_logs(100)

    level_colors = {"INFO": "#2ecc71", "ERROR": "#e74c3c", "WARNING": "#f39c12"}

    rows_html = ""
    for r in rows:
        color = level_colors.get(r["level"], "#aaa")
        rows_html += (
            f'<tr>'
            f'<td>{r["timestamp"]}</td>'
            f'<td style="color:{color};font-weight:bold">{r["level"]}</td>'
            f'<td>{r["action"] or ""}</td>'
            f'<td>{r["user_id"] or ""}</td>'
            f'<td>{r["channel_id"] or ""}</td>'
            f'<td style="word-break:break-word">{r["message"]}</td>'
            f'</tr>\n'
        )

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Logs — School Bot Admin</title>
  <meta http-equiv="refresh" content="30">
  <style>
    body {{ font-family: monospace; background: #111; color: #eee; padding: 20px; }}
    h1 {{ color: #fff; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
    th {{ background: #222; color: #aaa; padding: 8px; text-align: left; }}
    td {{ padding: 6px 8px; border-bottom: 1px solid #222; vertical-align: top; }}
    tr:hover td {{ background: #1a1a1a; }}
    .meta {{ color: #666; font-size: 12px; margin-bottom: 12px; }}
    a {{ color: #aaa; }}
  </style>
</head>
<body>
  <h1>Logs</h1>
  <div class="meta">Последние 100 записей · Обновление каждые 30 сек · <a href="/admin/stats?password={password}">Stats</a></div>
  <table>
    <tr><th>Время</th><th>Уровень</th><th>Действие</th><th>User ID</th><th>Channel ID</th><th>Сообщение</th></tr>
    {rows_html}
  </table>
</body>
</html>"""
    return html


@app.get("/admin/stats", response_class=HTMLResponse)
async def admin_stats(password: str = Query(...)):
    _check_password(password)
    stats = db_logger.get_stats_today()

    last_error_html = "—"
    if stats["last_error"]:
        last_error_html = (
            f'<span style="color:#e74c3c">{stats["last_error"]["message"]}</span>'
            f'<br><small style="color:#666">{stats["last_error"]["timestamp"]}</small>'
        )

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Stats — School Bot Admin</title>
  <meta http-equiv="refresh" content="30">
  <style>
    body {{ font-family: monospace; background: #111; color: #eee; padding: 20px; }}
    h1 {{ color: #fff; }}
    .card {{ background: #1a1a1a; border-radius: 8px; padding: 20px; margin: 12px 0; display: inline-block; min-width: 200px; }}
    .card .val {{ font-size: 48px; font-weight: bold; }}
    .green {{ color: #2ecc71; }}
    .red {{ color: #e74c3c; }}
    .meta {{ color: #666; font-size: 12px; margin-bottom: 12px; }}
    a {{ color: #aaa; }}
  </style>
</head>
<body>
  <h1>Stats</h1>
  <div class="meta">Сегодня · Обновление каждые 30 сек · <a href="/admin/logs?password={password}">Logs</a></div>
  <div class="card">
    <div class="green val">{stats["explanations_today"]}</div>
    <div>Уроков сегодня</div>
  </div>
  &nbsp;
  <div class="card">
    <div class="red val">{stats["errors_today"]}</div>
    <div>Ошибок сегодня</div>
  </div>
  <br><br>
  <div>
    <b>Последняя ошибка:</b><br>
    {last_error_html}
  </div>
</body>
</html>"""
    return html


@app.get("/favicon.ico")
async def favicon():
    return FileResponse("static/favicon.ico")


@app.get("/health")
async def health():
    return {"status": "ok"}
