import json
import uuid
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

CONTENT_DIR = Path(__file__).parent / "content"
CONTENT_DIR.mkdir(exist_ok=True)

_TEMPLATES_DIR = Path(__file__).parent / "new_templates"
_jinja_env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)))
_jinja_env.filters["tojson"] = json.dumps


def save_explanation(
    image_bytes: bytes | None,
    lesson_json: dict,
    server_url: str = "http://localhost:8000",
) -> str:
    """
    Renders lesson_json into interactive + print HTML pages using new_templates/.
    Saves the generated image (if any) and both HTML files under a shared content_id.
    Returns content_id (8-char UUID prefix).
    """
    content_id = str(uuid.uuid4())[:8]

    # Save image and build its public URL
    if image_bytes is not None:
        image_path = CONTENT_DIR / f"{content_id}.png"
        image_path.write_bytes(image_bytes)
        bg_image_url = f"{server_url}/content/{content_id}.png"
    else:
        bg_image_url = "https://picsum.photos/seed/kidion/1600/900"

    print_url = f"{server_url}/e/{content_id}_print"

    context = {
        **lesson_json,
        "bg_image_url": bg_image_url,
        "print_url": print_url,
    }

    # Render interactive lesson
    web_html = _jinja_env.get_template("lesson.html").render(**context)
    (CONTENT_DIR / f"{content_id}.html").write_text(web_html, encoding="utf-8")

    # Render printable lesson
    print_html = _jinja_env.get_template("lesson_print.html").render(**context)
    (CONTENT_DIR / f"{content_id}_print.html").write_text(print_html, encoding="utf-8")

    return content_id
