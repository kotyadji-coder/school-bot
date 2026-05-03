import logging
import os

from google import genai
from google.genai import types

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
logger = logging.getLogger("school-bot")

# Image generation fallback chain: AI Studio → Vertex AI
IMAGE_BACKENDS = [
    "ai_studio",
    "vertex",
]
IMAGE_MODEL = "gemini-2.5-flash-image"


def _get_client(backend: str) -> genai.Client:
    if backend == "ai_studio":
        if not GEMINI_API_KEY:
            raise ValueError("No GEMINI_API_KEY")
        return genai.Client(api_key=GEMINI_API_KEY)

    # vertex
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
            location="us-central1",
            credentials=credentials,
        )
    return genai.Client(
        vertexai=True,
        project=PROJECT_ID,
        location="us-central1",
    )


def generate_image(image_prompt: str) -> bytes:
    """
    Generates image via Gemini Flash Image, returns PNG bytes.
    Falls back from AI Studio to Vertex AI.
    """
    last_error = None

    for backend in IMAGE_BACKENDS:
        try:
            logger.info(f"Image generation via {backend}/{IMAGE_MODEL}")
            client = _get_client(backend)

            response = client.models.generate_content(
                model=IMAGE_MODEL,
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
                    logger.info(f"Image generated via {backend}")
                    return part.inline_data.data

            raise ValueError("No image data in response parts")

        except Exception as e:
            logger.warning(f"Image generation failed via {backend}: {e}")
            last_error = e
            continue

    raise last_error or RuntimeError("All image backends failed")
