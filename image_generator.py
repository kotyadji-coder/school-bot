import logging
import os

from google import genai
from google.genai import types

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
logger = logging.getLogger("school-bot")


def generate_image(image_prompt: str) -> bytes:
    """
    Генерирует изображение через Gemini 2.5 Flash Image и возвращает байты PNG.
    """
    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if credentials_path:
        from google.oauth2 import service_account
        credentials = service_account.Credentials.from_service_account_file(
            credentials_path,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        client = genai.Client(
            vertexai=True,
            project=PROJECT_ID,
            location="us-central1",
            credentials=credentials,
        )
    else:
        client = genai.Client(
            vertexai=True,
            project=PROJECT_ID,
            location="us-central1",
        )

    response = client.models.generate_content(
        model="gemini-2.5-flash-image",
        contents=[image_prompt],
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(
                aspect_ratio="16:9"
            )
        )
    )

    candidates = response.candidates
    if not candidates:
        logger.warning("IMAGE_RESPONSE: no candidates. prompt_feedback=%s", getattr(response, "prompt_feedback", None))
        raise ValueError("No candidates in image response")

    candidate = candidates[0]
    finish_reason = getattr(candidate, "finish_reason", "unknown")
    safety_ratings = getattr(candidate, "safety_ratings", None)
    logger.warning(
        "IMAGE_RESPONSE: finish_reason=%s safety_ratings=%s has_content=%s",
        finish_reason,
        safety_ratings,
        candidate.content is not None,
    )

    if candidate.content is None or candidate.content.parts is None:
        raise ValueError(f"Image response has no content (finish_reason={finish_reason})")

    for part in candidate.content.parts:
        if part.inline_data is not None:
            return part.inline_data.data

    raise ValueError("No image data in response parts")
