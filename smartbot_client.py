import json
import logging
import os

import httpx

SMARTBOT_URL = "https://api.smartbotpro.ru/blocks/execute"
ACCESS_TOKEN = os.getenv("SMARTBOT_ACCESS_TOKEN", "")

CHANNEL_CONFIGS = {
    os.getenv("SMARTBOT_TG_CHANNEL_ID", ""): {
        "block_success": os.getenv("SMARTBOT_TG_BLOCK_SUCCESS", ""),
        "block_error": os.getenv("SMARTBOT_TG_BLOCK_ERROR", ""),
    },
    os.getenv("SMARTBOT_VK_CHANNEL_ID", ""): {
        "block_success": os.getenv("SMARTBOT_VK_BLOCK_SUCCESS", ""),
        "block_error": os.getenv("SMARTBOT_VK_BLOCK_ERROR", ""),
    },
}
DEFAULT_CHANNEL_ID = os.getenv("SMARTBOT_TG_CHANNEL_ID", "")

logger = logging.getLogger("school-bot")


def send_message(
    peer_id: str,
    status: str = "success",
    channel_id: str | None = None,
    web_url: str | None = None,
    print_url: str | None = None,
    methodologist_notes: str | None = None,
) -> None:
    """Отправляет финальное сообщение пользователю через SmartBot Pro."""
    resolved_channel_id = channel_id or DEFAULT_CHANNEL_ID
    config = CHANNEL_CONFIGS.get(resolved_channel_id, CHANNEL_CONFIGS[DEFAULT_CHANNEL_ID])
    block_id = config["block_error"] if status == "error" else config["block_success"]
    logger.warning("SmartBot routing: channel_id=%s status=%s block_id=%s", resolved_channel_id, status, block_id)
    if web_url:
        notes_block = f"\n\n💡 Рекомендации методиста для родителей:\n{methodologist_notes}" if methodologist_notes else ""
        text = (
            f"🌟 Урок готов!\n\n"
            f"💻 Интерактивный урок: {web_url}\n\n"
            f"🖨 Версия для печати: {print_url}\n\n"
            f"Что внутри:\n"
            f"• Урок в стиле любимого героя\n"
            f"• Миссии (задания)\n\n"
            f"Вы можете распечатать урок или дать ребенку работать на планшете/компьютере."
            f"{notes_block}"
        )
        data = {"Messagetext": text}
    else:
        data = {}
    payload = {
        "access_token": ACCESS_TOKEN,
        "v": "0.0.1",
        "channel_id": resolved_channel_id,
        "block_id": block_id,
        "peer_id": peer_id,
        "data": data,
    }
    logger.warning("SmartBot payload: %s", json.dumps(payload, ensure_ascii=False))
    response = httpx.post(SMARTBOT_URL, json=payload, timeout=30)
    logger.warning("SmartBot response: status=%s body=%s", response.status_code, response.text)
    response.raise_for_status()
