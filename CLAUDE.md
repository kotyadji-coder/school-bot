# School Bot — Project Context

## What this is
A Telegram/VK bot that explains school topics through favorite cartoon characters.
Built on the same architecture as the `tales` (ProTale) bot.

## Flow
1. User sends: class/age + school topic + favorite cartoon character
2. Gemini generates an explanation using that character as the main actor
3. Gemini generates an image prompt → image is created
4. HTML page is saved with explanation + tasks + fun fact
5. SmartBot sends the page link back to the user

## Key files
- `main.py` — FastAPI server, `/generate` endpoint, `/lesson/{id}` viewer, admin panel
- `gemini_client.py` — Vertex AI calls: `generate_explanation()`, `parse_response()`, `generate_image_prompt()`
- `image_generator.py` — Gemini 2.5 Flash Image, returns PNG bytes
- `smartbot_client.py` — sends result back via SmartBot Pro API
- `content_generator.py` — saves HTML + PNG, returns content_id (like tale_generator.py in tales)
- `prompts.py` — two prompts: GENERATE_EXPLANATION_PROMPT and GENERATE_IMAGE_PROMPT_PROMPT
- `db_logger.py` — SQLite logging, same structure as tales

## Output sections (parsed from Gemini response)
- `---ОБЪЯСНЕНИЕ---` → explanation text (title on first line)
- `---ЗАДАНИЯ---` → 2-3 practice tasks
- `---ИНТЕРЕСНЫЙ ФАКТ---` → one fun fact

## Environment variables needed
See `.env.example`

## Start
```
uvicorn main:app --host 0.0.0.0 --port 8000
```

## Admin panel
- `/admin/logs?password=...` — last 100 log entries
- `/admin/stats?password=...` — today's lessons and errors
