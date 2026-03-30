import os

import vertexai
from vertexai.generative_models import GenerativeModel

from prompts import GENERATE_IMAGE_PROMPT_PROMPT, METHODOLOGIST_PROMPT, TUTOR_GAMER_PROMPT

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
REGION = "global"
MODEL_NAME = "gemini-3-pro-preview"


def _get_model() -> GenerativeModel:
    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if credentials_path:
        from google.oauth2 import service_account
        credentials = service_account.Credentials.from_service_account_file(credentials_path)
        vertexai.init(project=PROJECT_ID, location=REGION, credentials=credentials)
    else:
        vertexai.init(project=PROJECT_ID, location=REGION)
    return GenerativeModel(MODEL_NAME)


def generate_explanation(question: str) -> tuple[str, str]:
    """
    Two-step chain:
      Step 1 — Methodologist: structured, factually accurate explanation.
      Step 2 — Tutor-Gamer: transforms Step 1 into a fun character-based story.

    Returns (methodologist_output, final_output).
    """
    model = _get_model()

    # Step 1: methodologist
    step1_prompt = METHODOLOGIST_PROMPT.format(question=question)
    step1_response = model.generate_content(step1_prompt)
    methodologist_output = step1_response.text.strip()

    # Step 2: tutor-gamer receives original question + Step 1 output
    step2_prompt = TUTOR_GAMER_PROMPT.format(
        question=question,
        methodologist_output=methodologist_output,
    )
    step2_response = model.generate_content(step2_prompt)
    final_output = step2_response.text.strip()

    return methodologist_output, final_output


def parse_response(tutor_output: str, methodologist_output: str) -> dict:
    """
    Разбивает финальный ответ тьютора-геймера на секции.
    Третья секция — рекомендации методиста — берётся напрямую из шага 1.

    Возвращает:
      explanation  — объяснение через вселенную + задания (вывод тьютора целиком)
      tasks        — только блок заданий из вывода тьютора
      methodologist_notes — теория из шага 1 (для родителя/педагога)
    """
    sections = {"explanation": "", "tasks": ""}
    markers = {
        "---ОБЪЯСНЕНИЕ---": "explanation",
        "---ЗАДАНИЯ---": "tasks",
    }

    current_key = None
    for line in tutor_output.splitlines():
        stripped = line.strip()
        if stripped in markers:
            current_key = markers[stripped]
        elif current_key is not None:
            sections[current_key] += line + "\n"

    return {
        "explanation": sections["explanation"].strip().replace("**", ""),
        "tasks": sections["tasks"].strip().replace("**", ""),
        "methodologist_notes": methodologist_output.strip().replace("**", ""),
    }


def generate_image_prompt(explanation: str) -> str:
    """Генерирует промт для иллюстрации на основе финального текста урока."""
    model = _get_model()
    prompt = GENERATE_IMAGE_PROMPT_PROMPT.format(story=explanation)
    response = model.generate_content(prompt)
    return response.text.strip()
