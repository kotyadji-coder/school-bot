import os
import uuid
from pathlib import Path

CONTENT_DIR = Path(__file__).parent / "content"
CONTENT_DIR.mkdir(exist_ok=True)


def save_explanation(
    image_bytes: bytes,
    explanation_text: str,
    server_url: str = "http://localhost:8000",
    tasks: str = "",
    methodologist_notes: str = "",
) -> str:
    """
    Сохраняет объяснение в HTML и картинку.
    Первая строка explanation_text становится заголовком.
    Возвращает content_id (UUID).
    """
    content_id = str(uuid.uuid4())[:8]

    # Сохраняем картинку
    image_path = CONTENT_DIR / f"{content_id}.png"
    with open(image_path, "wb") as f:
        f.write(image_bytes)

    # Извлекаем заголовок из первой непустой строки
    lines = [l.strip() for l in explanation_text.splitlines() if l.strip()]
    title = lines[0] if lines else "Объяснение"
    body_text = "\n".join(lines[1:]) if len(lines) > 1 else explanation_text

    # Генерируем HTML
    image_url = f"{server_url}/content/{content_id}.png"
    content_url = f"{server_url}/lesson/{content_id}"
    html_content = _generate_html(title, image_url, body_text, tasks, methodologist_notes, content_url)

    # Сохраняем HTML
    html_path = CONTENT_DIR / f"{content_id}.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    return content_id


def _generate_html(title: str, image_url: str, explanation_text: str, tasks: str = "", methodologist_notes: str = "", content_url: str = "") -> str:
    """Генерирует HTML-страницу с объяснением."""
    paragraphs = "".join(
        f"<p>{p.strip()}</p>" for p in explanation_text.split("\n") if p.strip()
    )
    description = explanation_text.strip()[:150].replace('"', '&quot;')
    if len(explanation_text.strip()) > 150:
        description += "…"

    tasks_html = ""
    if tasks:
        tasks_paragraphs = "".join(
            f"<p>{p.strip()}</p>" for p in tasks.split("\n") if p.strip()
        )
        tasks_html = f"""
            <div class="extra-section tasks">
                <h2>✏️ Задания</h2>
                {tasks_paragraphs}
            </div>"""

    notes_html = ""
    if methodologist_notes:
        notes_paragraphs = "".join(
            f"<p>{p.strip()}</p>" for p in methodologist_notes.split("\n") if p.strip()
        )
        notes_html = f"""
            <div class="extra-section methodologist-notes">
                <h2>📋 Рекомендации методиста</h2>
                {notes_paragraphs}
            </div>"""

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <meta property="og:type" content="article" />
    <meta property="og:title" content="{title}" />
    <meta property="og:description" content="{description}" />
    <meta property="og:image" content="{image_url}" />
    <meta property="og:url" content="{content_url}" />
    <meta name="twitter:card" content="summary_large_image" />
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800&family=Nunito+Sans:wght@400;600&display=swap" rel="stylesheet">
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: 'Nunito Sans', sans-serif;
            background-color: #EEF2FF;
            min-height: 100vh;
            padding: 40px 20px;
            color: #2D3561;
        }}

        .container {{
            max-width: 780px;
            margin: 0 auto;
            background: #ffffff;
            border-radius: 24px;
            box-shadow: 0 8px 32px rgba(45, 53, 97, 0.10), 0 2px 8px rgba(45, 53, 97, 0.06);
            overflow: hidden;
        }}

        .content {{
            padding: 48px 48px 48px;
        }}

        .lesson-title {{
            font-family: 'Nunito', sans-serif;
            font-size: 2em;
            font-weight: 800;
            color: #5B6FE8;
            line-height: 1.3;
            text-align: center;
            margin-bottom: 10px;
        }}

        .divider {{
            width: 60px;
            height: 4px;
            background: linear-gradient(90deg, #5B6FE8, #A78BFA);
            border-radius: 2px;
            margin: 0 auto 32px;
        }}

        .image-container {{
            text-align: center;
            margin: 0 0 36px;
        }}

        .image-container img {{
            max-width: 100%;
            height: auto;
            border-radius: 16px;
            box-shadow: 0 4px 20px rgba(45, 53, 97, 0.12);
            display: block;
            margin: 0 auto;
        }}

        .explanation-text {{
            line-height: 1.8;
            font-size: 1.05em;
            color: #2D3561;
        }}

        .explanation-text p {{
            margin-bottom: 1.2em;
        }}

        .explanation-text p:last-child {{
            margin-bottom: 0;
        }}

        .extra-section {{
            margin-top: 36px;
            padding: 28px 32px;
            border-radius: 16px;
        }}

        .extra-section h2 {{
            font-family: 'Nunito', sans-serif;
            font-size: 1.25em;
            font-weight: 800;
            margin-bottom: 16px;
        }}

        .extra-section p {{
            line-height: 1.7;
            font-size: 1em;
            margin-bottom: 0.8em;
        }}

        .extra-section p:last-child {{
            margin-bottom: 0;
        }}

        .tasks {{
            background: #F0F4FF;
            border-left: 4px solid #5B6FE8;
        }}

        .tasks h2 {{
            color: #5B6FE8;
        }}

        .methodologist-notes {{
            background: #F0FDF4;
            border-left: 4px solid #10B981;
        }}

        .methodologist-notes h2 {{
            color: #059669;
        }}

        .action-bar {{
            display: flex;
            justify-content: center;
            gap: 12px;
            margin-top: 40px;
            padding-top: 28px;
            border-top: 1px solid #E8ECFF;
        }}

        button {{
            background: #EEF2FF;
            color: #5B6FE8;
            border: none;
            padding: 12px 28px;
            border-radius: 50px;
            font-size: 0.95em;
            font-family: 'Nunito', sans-serif;
            cursor: pointer;
            transition: background 0.2s, transform 0.15s;
            font-weight: 700;
        }}

        button:hover {{
            background: #DDE3FF;
            transform: translateY(-1px);
        }}

        button:active {{
            transform: translateY(0);
        }}

        @media print {{
            body {{
                background: white;
                padding: 0;
            }}

            .container {{
                box-shadow: none;
                border-radius: 0;
                max-width: 100%;
            }}

            .content {{
                padding: 16px 24px 24px;
            }}

            .action-bar {{
                display: none;
            }}

            @page {{
                margin: 1.5cm;
            }}
        }}

        @media (max-width: 600px) {{
            body {{
                padding: 16px 12px;
            }}

            .lesson-title {{
                font-size: 1.5em;
            }}

            .content {{
                padding: 28px 24px 32px;
            }}

            .explanation-text {{
                font-size: 1em;
            }}

            .action-bar {{
                flex-direction: column;
                align-items: center;
            }}

            button {{
                width: 100%;
                max-width: 280px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="content">
            <h1 class="lesson-title">{title}</h1>
            <div class="divider"></div>

            <div class="image-container">
                <img src="{image_url}" alt="{title}" loading="lazy">
            </div>

            <div class="explanation-text">
                {paragraphs}
            </div>
            {tasks_html}
            {notes_html}

            <div class="action-bar" id="action-bar">
                <button id="print-btn" onclick="window.print()">Распечатать</button>
                <button id="new-lesson-btn" onclick="window.location.href = '/'">Новый урок</button>
                <p id="tg-hint" style="display:none; color:#888; font-size:0.9em; text-align:center;">
                    Для печати откройте страницу в браузере
                </p>
            </div>
        </div>
    </div>
    <script>
        if (/Telegram/i.test(navigator.userAgent) || window.TelegramWebviewProxy !== undefined) {{
            document.getElementById('print-btn').style.display = 'none';
            document.getElementById('tg-hint').style.display = 'block';
        }}
    </script>
</body>
</html>"""
