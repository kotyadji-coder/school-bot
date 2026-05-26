import json
import logging
import os
import re
import threading
import time

import httpx
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

LLM_DASHBOARD_URL = "http://5.42.101.215:8005/api/usage"


def _send_to_dashboard(model: str, response):
    try:
        input_tokens = getattr(getattr(response, "usage_metadata", None), "prompt_token_count", 0) or 0
        output_tokens = getattr(getattr(response, "usage_metadata", None), "candidates_token_count", 0) or 0
        if not (input_tokens or output_tokens):
            return
        httpx.post(LLM_DASHBOARD_URL, json={
            "project": "school-bot",
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }, timeout=5)
    except Exception:
        logger.debug("Failed to send usage to LLM dashboard", exc_info=True)

_last_backend = "unknown"

from prompts import (
    GENERATE_IMAGE_PROMPT_FALLBACK_PROMPT,
    GENERATE_IMAGE_PROMPT_PROMPT,
    METHODOLOGIST_PROMPT,
    TUTOR_GAMER_JSON_PROMPT,
)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
VERTEX_REGION = "global"

CHILD_SAFETY_SETTINGS = [
    types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_LOW_AND_ABOVE"),
    types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_LOW_AND_ABOVE"),
    types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_LOW_AND_ABOVE"),
    types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_LOW_AND_ABOVE"),
]

# Fallback chain: AI Studio Pro → AI Studio Flash → Vertex AI Pro
FALLBACK_CHAIN = [
    ("ai_studio", "gemini-3.5-flash"),
    ("vertex", "gemini-3.5-flash"),
]


def _get_ai_studio_client() -> genai.Client:
    return genai.Client(api_key=GEMINI_API_KEY)


def _get_vertex_client() -> genai.Client:
    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if credentials_path:
        from google.oauth2 import service_account
        credentials = service_account.Credentials.from_service_account_file(
            credentials_path,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        return genai.Client(
            vertexai=True,
            project=PROJECT_ID,
            location=VERTEX_REGION,
            credentials=credentials,
        )
    return genai.Client(
        vertexai=True,
        project=PROJECT_ID,
        location=VERTEX_REGION,
    )


def _call_with_fallback(contents, config=None):
    """Try each backend/model in FALLBACK_CHAIN. Retry 429s with backoff before moving on."""
    last_error = None

    for backend, model_name in FALLBACK_CHAIN:
        try:
            if backend == "ai_studio":
                if not GEMINI_API_KEY:
                    logger.info(f"Skipping AI Studio ({model_name}): no API key")
                    continue
                client = _get_ai_studio_client()
            else:
                client = _get_vertex_client()

            tag = f"{backend}/{model_name}"

            # Retry loop for rate limits (429)
            for attempt in range(4):  # 0, 1, 2, 3
                try:
                    logger.info(f"Calling {tag} (attempt {attempt + 1})")
                    response = client.models.generate_content(
                        model=model_name,
                        contents=contents,
                        config=config,
                    )
                    logger.info(f"Success from {tag}")
                    global _last_backend
                    _last_backend = tag
                    threading.Thread(target=_send_to_dashboard, args=(model_name, response), daemon=True).start()
                    return response
                except Exception as e:
                    error_str = str(e)
                    if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str.upper():
                        if attempt < 3:
                            wait = 2 ** attempt * 5
                            logger.warning(f"{tag} rate limit, retry {attempt + 1}/3 after {wait}s")
                            time.sleep(wait)
                            continue
                        logger.warning(f"{tag} rate limit exhausted, moving to next backend")
                        last_error = e
                        break
                    else:
                        raise

        except Exception as e:
            logger.warning(f"Failed {backend}/{model_name}: {e}")
            last_error = e
            continue

    raise last_error or RuntimeError("All backends failed")


def get_last_backend() -> str:
    return _last_backend


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
    safety_config = types.GenerateContentConfig(
        safety_settings=CHILD_SAFETY_SETTINGS,
        thinking_config=types.ThinkingConfig(thinking_level="MINIMAL"),
    )

    # Step 1: methodologist (plain text)
    step1_prompt = METHODOLOGIST_PROMPT.format(question=question)
    step1_response = _call_with_fallback(step1_prompt, config=safety_config)
    methodologist_output = step1_response.text.strip()

    # Step 2: tutor-gamer → strict JSON
    step2_prompt = TUTOR_GAMER_JSON_PROMPT.format(
        question=question,
        methodologist_output=methodologist_output,
    )
    json_config = types.GenerateContentConfig(
        response_mime_type="application/json",
        safety_settings=CHILD_SAFETY_SETTINGS,
        thinking_config=types.ThinkingConfig(thinking_level="MINIMAL"),
    )
    step2_response = _call_with_fallback(step2_prompt, config=json_config)
    lesson_dict = _extract_json(step2_response.text)

    return methodologist_output, lesson_dict


def generate_image_prompt(explanation: str) -> str:
    """Generates image prompt based on lesson text."""
    safety_config = types.GenerateContentConfig(
        safety_settings=CHILD_SAFETY_SETTINGS,
        thinking_config=types.ThinkingConfig(thinking_level="MINIMAL"),
    )
    prompt = GENERATE_IMAGE_PROMPT_PROMPT.format(story=explanation)
    response = _call_with_fallback(prompt, config=safety_config)
    return response.text.strip()


def generate_image_prompt_fallback(explanation: str) -> str:
    """Fallback image prompt (kids cosplay strategy) for IMAGE_PROHIBITED_CONTENT."""
    safety_config = types.GenerateContentConfig(
        safety_settings=CHILD_SAFETY_SETTINGS,
        thinking_config=types.ThinkingConfig(thinking_level="MINIMAL"),
    )
    prompt = GENERATE_IMAGE_PROMPT_FALLBACK_PROMPT.format(story=explanation)
    response = _call_with_fallback(prompt, config=safety_config)
    return response.text.strip()
