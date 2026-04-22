import json
import logging
import os
import re
import time

import vertexai
from google.api_core.exceptions import ResourceExhausted
from vertexai.generative_models import GenerationConfig, GenerativeModel, HarmBlockThreshold, HarmCategory, SafetySetting

logger = logging.getLogger(__name__)

from prompts import (
    GENERATE_IMAGE_PROMPT_FALLBACK_PROMPT,
    GENERATE_IMAGE_PROMPT_PROMPT,
    METHODOLOGIST_PROMPT,
    TUTOR_GAMER_JSON_PROMPT,
)

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
REGION = "global"
MODEL_NAME = "gemini-3.1-pro-preview"
FALLBACK_MODEL_NAME = "gemini-2.5-pro"

CHILD_SAFETY_SETTINGS = [
    SafetySetting(
        category=HarmCategory.HARM_CATEGORY_HARASSMENT,
        threshold=HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
    ),
    SafetySetting(
        category=HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        threshold=HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
    ),
    SafetySetting(
        category=HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        threshold=HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
    ),
    SafetySetting(
        category=HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        threshold=HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
    ),
]


def _get_model(model_name: str = MODEL_NAME) -> GenerativeModel:
    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if credentials_path:
        from google.oauth2 import service_account
        credentials = service_account.Credentials.from_service_account_file(credentials_path)
        vertexai.init(project=PROJECT_ID, location=REGION, credentials=credentials)
    else:
        vertexai.init(project=PROJECT_ID, location=REGION)
    return GenerativeModel(model_name)


def _call_with_retry(model, *args, max_retries=3, **kwargs):
    """Call model.generate_content with retry on 429, fallback to gemini-2.5-pro."""
    for attempt in range(max_retries + 1):
        try:
            return model.generate_content(*args, **kwargs)
        except ResourceExhausted:
            if attempt == max_retries:
                break
            wait = 2 ** attempt * 5  # 5s, 10s, 20s
            logger.warning(f"Gemini 429 rate limit, retry {attempt + 1}/{max_retries} after {wait}s")
            time.sleep(wait)

    # All retries exhausted — fallback to stable model
    logger.warning(f"Retries exhausted for {MODEL_NAME}, falling back to {FALLBACK_MODEL_NAME}")
    fallback_model = _get_model(FALLBACK_MODEL_NAME)
    return fallback_model.generate_content(*args, **kwargs)


def _extract_json(raw: str) -> dict:
    """Strip markdown fences and extract the JSON object from the model response."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"```\s*$", "", cleaned.strip(), flags=re.MULTILINE)
    cleaned = cleaned.strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        cleaned = match.group(0)
    return json.loads(cleaned)


def generate_explanation(question: str) -> tuple[str, dict]:
    """
    Two-step chain:
      Step 1 — Methodologist: structured rule + mnemonic.
      Step 2 — Tutor-Gamer: returns strict JSON lesson with story_blocks + 5 tasks.

    Returns (methodologist_output, lesson_dict).
    """
    model = _get_model()

    # Step 1: methodologist (plain text)
    step1_prompt = METHODOLOGIST_PROMPT.format(question=question)
    step1_response = _call_with_retry(model, step1_prompt, safety_settings=CHILD_SAFETY_SETTINGS)
    methodologist_output = step1_response.text.strip()

    # Step 2: tutor-gamer → strict JSON
    step2_prompt = TUTOR_GAMER_JSON_PROMPT.format(
        question=question,
        methodologist_output=methodologist_output,
    )
    step2_response = _call_with_retry(
        model, step2_prompt,
        generation_config=GenerationConfig(response_mime_type="application/json"),
        safety_settings=CHILD_SAFETY_SETTINGS,
    )
    lesson_dict = _extract_json(step2_response.text)

    return methodologist_output, lesson_dict


def generate_image_prompt(explanation: str) -> str:
    """Генерирует промт для иллюстрации на основе финального текста урока."""
    model = _get_model()
    prompt = GENERATE_IMAGE_PROMPT_PROMPT.format(story=explanation)
    response = _call_with_retry(model, prompt, safety_settings=CHILD_SAFETY_SETTINGS)
    return response.text.strip()


def generate_image_prompt_fallback(explanation: str) -> str:
    """Запасной промт (kids cosplay стратегия) — используется при IMAGE_PROHIBITED_CONTENT."""
    model = _get_model()
    prompt = GENERATE_IMAGE_PROMPT_FALLBACK_PROMPT.format(story=explanation)
    response = _call_with_retry(model, prompt, safety_settings=CHILD_SAFETY_SETTINGS)
    return response.text.strip()
