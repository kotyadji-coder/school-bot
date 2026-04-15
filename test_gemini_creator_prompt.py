"""
Sandbox: upgraded TUTOR_GAMER_PROMPT → JSON output with 5 interactive tasks.
Does NOT modify prompts.py, gemini_client.py, or any live production file.

Generates:
  test_api_web.html   — interactive lesson (lesson.html)
  test_api_print.html — printable lesson  (lesson_print.html)
"""

import json
import os
import re
from pathlib import Path

# Load .env if present (same pattern as production)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import vertexai
from jinja2 import Environment, FileSystemLoader
from vertexai.generative_models import (
    GenerativeModel,
    HarmBlockThreshold,
    HarmCategory,
    SafetySetting,
)

# ── Constants (mirror production) ────────────────────────────────────────────
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
REGION     = "global"
MODEL_NAME = "gemini-3.1-pro-preview"   # same as production gemini_client.py

CHILD_SAFETY = [
    SafetySetting(category=HarmCategory.HARM_CATEGORY_HARASSMENT,        threshold=HarmBlockThreshold.BLOCK_LOW_AND_ABOVE),
    SafetySetting(category=HarmCategory.HARM_CATEGORY_HATE_SPEECH,       threshold=HarmBlockThreshold.BLOCK_LOW_AND_ABOVE),
    SafetySetting(category=HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=HarmBlockThreshold.BLOCK_LOW_AND_ABOVE),
    SafetySetting(category=HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=HarmBlockThreshold.BLOCK_LOW_AND_ABOVE),
]

# ── UPGRADED PROMPT ───────────────────────────────────────────────────────────
# Based on TUTOR_GAMER_PROMPT from prompts.py.
# All pedagogical rules are PRESERVED unchanged.
# Changes:
#   1) Output format: strict JSON instead of plain text.
#   2) Tasks: 5 interactive typed tasks instead of 3 paper tasks.
#   3) story_blocks: each block has an "emoji" anchor key.
#   4) Task questions: neutral, no UI verbs ("перетащи", "нажми", "кликни").
#   5) fill_in_the_blank example in question must be a WRONG answer (no spoilers).

TUTOR_GAMER_JSON_PROMPT = """РОЛЬ:
Ты — репетитор-геймер для детей и методист начальных классов РФ. Ты объясняешь школьные правила через механику любимых вселенных ребёнка так просто, чтобы было понятно ребенку 7-9 лет. Ты объясняешь логику школьного правила через логику мира, который ребёнок уже любит.

ВХОД (2 источника):
1) Запрос пользователя. Там в любом порядке: Имя ребёнка, Класс, Тема, Любимая Вселенная.
2) ДАННЫЕ ИЗ шага 1 (методист):
Это единственный источник школьного правила. Не меняй предмет, тему, правило, лайфхак и исключения.

ГЛАВНАЯ ЗАДАЧА:
Сгенерировать урок в формате строгого JSON (структура описана ниже).
Урок включает:
- Теорию: 3-4 блока объяснения через Вселенную ребёнка
- 5 интерактивных заданий строго разных типов

ВАЖНО:
1) Запрещены звёздочки. Никаких * или **.
2) Только простые предложения. Никаких деепричастных оборотов.
3) Никогда не используй LaTeX и знаки $
4) Вывод — ТОЛЬКО чистый JSON. Без markdown-обёрток (```json), без пояснений до или после JSON.

ПРАВИЛА ПРО ВСЕЛЕННУЮ:
1) Контент вселенной: все предметы, персонажи, примеры, названия — исключительно из выбранной вселенной. Никаких других франшиз и смешений.
2) Если вселенная неизвестна или ребёнок попросил странное, используй нейтральный режим: "игровой мир приключений" без чужих брендов.

КРИТИЧЕСКИЕ ПРАВИЛА (теория / story_blocks):
1) 3-4 блока. Каждый блок — отдельный смысловой шаг объяснения.
2) Первый блок: зацепи ребёнка сценой из вселенной, обратись к нему по имени.
3) Последний блок: кратко сформулируй правило и встрой лайфхак из шага 1.
4) Выбери ОДНУ главную метафору для объяснения темы. Используй её во всех блоках и заданиях. Не смешивай образы.
5) DIRECT MAPPING: всегда прямо сопоставляй школьные термины и элементы вселенной.
6) Терминология "Сэндвич": в одном предложении используй школьный термин и термин из вселенной.
7) Длина каждого блока: 2-5 предложений. Язык — понятный ребёнку 7-9 лет.
8) emoji: для каждого блока выбери одно эмодзи, отражающее смысл блока. Ставь его как отдельный ключ "emoji".

КРИТИЧЕСКИЕ ПРАВИЛА (задания / tasks):
1) Ровно 5 заданий. Каждый тип используется РОВНО ОДИН РАЗ.
   Порядок типов строго фиксирован: quiz → multiple_choice → drag_and_drop → fill_in_the_blank → ordering
2) Каждое задание — мини-сцена в той же метафоре и вселенной.
3) Вопросы нейтральные: без UI-подсказок ("перетащи", "нажми", "кликни", "выбери кнопкой").
4) fill_in_the_blank: пример в тексте вопроса ОБЯЗАН быть неправильным ответом.
   Никогда не используй правильный ответ как пример. Это спойлер.
5) Никаких подсказок, ответов и намёков в текстах вопросов.
6) Единицы измерения логичные. Нельзя делить на персонажей. Можно делить на команды, группы, отряды.

КРИТИЧЕСКОЕ ПРАВИЛО ДЛЯ drag_and_drop:
Количество элементов в "items", "zones" и "correct" ОБЯЗАНО быть одинаковым.
- items, zones и correct должны содержать ровно одинаковое количество записей (например, все по 3 или все по 4).
- Каждый элемент из items имеет ровно одну уникальную зону из zones.
- Каждая зона из zones упоминается в correct ровно один раз.
- НИКОГДА не создавай ситуацию, где элементов больше или меньше, чем зон.

КРИТИЧЕСКОЕ ПРАВИЛО ДЛЯ ВАРИАНТОВ ОТВЕТА (options / distractors):
Неправильные варианты (distractors) ОБЯЗАНЫ быть педагогически логичными, сложными и того же ТИПА ДАННЫХ, что и правильный ответ.
- Если вопрос про число (дробь, числитель, знаменатель, результат вычисления) — ВСЕ варианты ДОЛЖНЫ быть правдоподобными числами. Это типичные ошибки ученика: перепутанные числитель/знаменатель, соседние числа, результат неверной операции.
- НИКОГДА не используй слова из сюжета ("Торт", "Сундук", "Стив", "Крипер") как варианты ответа в математических или числовых вопросах.
- Тематические элементы вселенной уместны ТОЛЬКО в тексте вопроса. Варианты ответа должны оставаться учебно грамотными.
- Это правило применяется ко всем типам заданий: quiz, multiple_choice, drag_and_drop.

СПЕЦ-ПРАВИЛО ДЛЯ ДРОБЕЙ (применять только если тема про дроби/доли):
- Знаменатель = сколько равных частей всего. Пишут вниз.
- Числитель = сколько частей взяли/закрасили/съели. Пишут вверх.
- Если используешь "вверх/вниз", то вверх = числитель, вниз = знаменатель.

ВНУТРЕННИЙ КОНТРОЛЬ (не показывать пользователю):
- Извлеки из запроса: имя, вселенная, класс.
- Правило, лайфхак, исключения бери только из шага 1.
- Перед генерацией заданий вычисли правильные ответы внутри. Не печатай их в вопросах.
- Проверь: в fill_in_the_blank пример в вопросе — заведомо ложный ответ.
- Проверь: использованы ровно 5 разных типов в правильном порядке.
- Проверь: все варианты ответа (options) в quiz и multiple_choice — того же типа данных, что и правильный ответ. Если тема числовая — все варианты числа. Ноль тематических слов в options.
- Проверь: в drag_and_drop len(items) == len(zones) == len(correct). Если не так — исправь перед выводом.

СТРОГАЯ JSON-СТРУКТУРА ОТВЕТА:
{{
  "title": "<название урока — тема + отсылка к вселенной ребёнка>",
  "story_blocks": [
    {{"emoji": "<1 эмодзи>", "text": "<текст блока>"}},
    {{"emoji": "<1 эмодзи>", "text": "<текст блока>"}},
    {{"emoji": "<1 эмодзи>", "text": "<текст блока>"}}
  ],
  "tasks": [
    {{
      "type": "quiz",
      "question": "<вопрос>",
      "options": ["<вариант1>", "<вариант2>", "<вариант3>", "<вариант4>"],
      "correct": "<текст правильного варианта дословно, как в options>"
    }},
    {{
      "type": "multiple_choice",
      "question": "<вопрос>",
      "options": ["<вар1>", "<вар2>", "<вар3>", "<вар4>", "<вар5>"],
      "correct": ["<правильный1>", "<правильный2>"]
    }},
    {{
      "type": "drag_and_drop",
      "question": "<нейтральный вопрос — без слов 'перетащи', 'нажми', 'кликни'>",
      "items": ["<элемент1>", "<элемент2>", "<элемент3>"],
      "zones": ["<зона1>", "<зона2>", "<зона3>"],
      "correct": {{"<элемент1>": "<зона>", "<элемент2>": "<зона>", "<элемент3>": "<зона>"}}
    }},
    {{
      "type": "fill_in_the_blank",
      "question": "<вопрос с ложным примером, например: 'Запиши дробь (например: 1/4)' — где 1/4 заведомо неверный ответ>",
      "correct": "<правильный ответ>"
    }},
    {{
      "type": "ordering",
      "question": "<нейтральный вопрос — без слов 'перетащи', 'нажми'>",
      "items": ["<элементы в случайном перемешанном порядке>"],
      "correct_order": ["<элементы в правильном порядке>"]
    }}
  ]
}}

ЗАПРОС ПОЛЬЗОВАТЕЛЯ:
{question}

ДАННЫЕ ИЗ ШАГА 1 (методист):
{methodologist_output}"""


# ── Mock inputs ───────────────────────────────────────────────────────────────
MOCK_QUESTION = "Вася, 3 класс, тема: обыкновенные дроби (числитель и знаменатель), вселенная: Майнкрафт"

MOCK_METHODOLOGIST_OUTPUT = """1. Предмет: Математика. Тема: Обыкновенные дроби — числитель и знаменатель.

2. Правило:
Дробь — это запись части целого. Выглядит как два числа с горизонтальной чертой между ними.
Нижнее число — знаменатель — показывает, на сколько равных частей разделили целое.
Верхнее число — числитель — показывает, сколько таких частей взяли.
Пример: 3/8 значит "разделили на 8 частей и взяли 3".
Чем больше знаменатель, тем мельче каждая часть.

3. 💡 Лайфхак: "Знаменатель — Знизу, Числитель — Числим кусочки сверху."
Визуально: представь пиццу. Знаменатель — сколько кусков нарезали. Числитель — сколько ты съел.

4. Исключения: нет."""


# ── Vertex AI helper ──────────────────────────────────────────────────────────
def _get_model() -> GenerativeModel:
    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if creds_path:
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_file(creds_path)
        vertexai.init(project=PROJECT_ID, location=REGION, credentials=creds)
    else:
        vertexai.init(project=PROJECT_ID, location=REGION)
    return GenerativeModel(MODEL_NAME)


def call_gemini(prompt_text: str) -> str:
    model = _get_model()
    response = model.generate_content(prompt_text, safety_settings=CHILD_SAFETY)
    return response.text.strip()


# ── JSON extraction (handles markdown code fences) ────────────────────────────
def extract_json(raw: str) -> dict:
    # Strip ```json ... ``` or ``` ... ``` fences
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"```\s*$",          "", cleaned.strip(), flags=re.MULTILINE)
    cleaned = cleaned.strip()

    # If there's preamble text, find the first { ... } block
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        cleaned = match.group(0)

    return json.loads(cleaned)


# ── Template rendering ────────────────────────────────────────────────────────
def render_templates(lesson_data: dict) -> None:
    template_dir = Path(__file__).parent / "new_templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)))
    env.filters["tojson"] = json.dumps

    base = Path(__file__).parent

    web   = env.get_template("lesson.html")
    print_t = env.get_template("lesson_print.html")

    (base / "test_api_web.html").write_text(
        web.render(**lesson_data), encoding="utf-8"
    )
    (base / "test_api_print.html").write_text(
        print_t.render(**lesson_data), encoding="utf-8"
    )
    print(f"Web   → {base / 'test_api_web.html'}")
    print(f"Print → {base / 'test_api_print.html'}")


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("UPGRADED PROMPT (TUTOR_GAMER_JSON_PROMPT) — preview:")
    print("=" * 60)
    # Print only the sections that changed vs the original
    sections = [
        "ГЛАВНАЯ ЗАДАЧА",
        "КРИТИЧЕСКИЕ ПРАВИЛА (теория",
        "КРИТИЧЕСКИЕ ПРАВИЛА (задания",
        "СТРОГАЯ JSON-СТРУКТУРА",
    ]
    for line in TUTOR_GAMER_JSON_PROMPT.splitlines():
        if any(s in line for s in sections):
            print(f"\n>>> {line}")
    print("\n(Full prompt sent to API)\n")

    print("Calling Gemini API...")
    full_prompt = TUTOR_GAMER_JSON_PROMPT.format(
        question=MOCK_QUESTION,
        methodologist_output=MOCK_METHODOLOGIST_OUTPUT,
    )
    raw_response = call_gemini(full_prompt)

    print("\nRaw API response (first 400 chars):")
    print(raw_response[:400])
    print("...\n")

    # Save raw response for inspection
    raw_path = Path(__file__).parent / "test_api_raw_response.json"
    raw_path.write_text(raw_response, encoding="utf-8")
    print(f"Raw response saved → {raw_path}")

    # Parse JSON
    try:
        lesson_json = extract_json(raw_response)
    except json.JSONDecodeError as e:
        print(f"\nJSON parse error: {e}")
        print("Check test_api_raw_response.json for the full model output.")
        raise

    # Validate task types
    task_types = [t["type"] for t in lesson_json.get("tasks", [])]
    print(f"\nTask types generated ({len(task_types)}): {task_types}")
    expected = ["quiz", "multiple_choice", "drag_and_drop", "fill_in_the_blank", "ordering"]
    if task_types == expected:
        print("✓ All 5 task types correct and in the right order.")
    else:
        print(f"✗ Expected: {expected}")

    # Add runtime fields (not generated by LLM)
    lesson_json["bg_image_url"] = "https://picsum.photos/seed/minecraft/1600/900"
    lesson_json["print_url"]    = "test_api_print.html"

    # Save parsed JSON
    json_path = Path(__file__).parent / "test_api_lesson.json"
    json_path.write_text(json.dumps(lesson_json, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Parsed JSON saved → {json_path}")

    # Render templates
    render_templates(lesson_json)
    print("\nDone.")
