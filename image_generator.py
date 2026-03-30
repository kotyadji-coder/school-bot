import os

from google import genai
from google.genai import types

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")


def generate_image(image_prompt: str) -> bytes:
    """
    Генерирует изображение через Gemini 2.5 Flash Image и возвращает байты PNG.
    """
    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if credentials_path:
        client = genai.Client(
            vertexai=True,
            project=PROJECT_ID,
            location="us-central1",
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

    for part in response.candidates[0].content.parts:
        if part.inline_data is not None:
            return part.inline_data.data

    raise ValueError("No image data in response")
