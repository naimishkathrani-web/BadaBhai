"""Explicitly opted-in Exotel SMS recaps. Disabled until an account is configured."""

import os

import httpx


def configuration(language):
    return {
        "api_key": os.getenv("EXOTEL_API_KEY", "").strip(),
        "api_token": os.getenv("EXOTEL_API_TOKEN", "").strip(),
        "account_sid": os.getenv("EXOTEL_ACCOUNT_SID", "").strip(),
        "sender": os.getenv("EXOTEL_SMS_FROM", "").strip(),
        "entity_id": os.getenv("EXOTEL_DLT_ENTITY_ID", "").strip(),
        "template_id": os.getenv(f"EXOTEL_DLT_TEMPLATE_{language.upper()}", "").strip(),
        "base_url": os.getenv("EXOTEL_SMS_BASE_URL", "https://api.in.exotel.com").rstrip("/"),
    }


def ready(language):
    cfg = configuration(language)
    return all(cfg[key] for key in ("api_key", "api_token", "account_sid", "sender", "entity_id", "template_id"))


async def send_recap(to, language, body):
    cfg = configuration(language)
    if not all(cfg[key] for key in ("api_key", "api_token", "account_sid", "sender", "entity_id", "template_id")):
        raise RuntimeError("Exotel SMS and DLT settings are incomplete")
    url = f"{cfg['base_url']}/v1/Accounts/{cfg['account_sid']}/Sms/send"
    data = {
        "From": cfg["sender"],
        "To": to,
        "Body": body,
        "DltEntityId": cfg["entity_id"],
        "DltTemplateId": cfg["template_id"],
        "SmsType": "transactional_opt_in",
    }
    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.post(url, auth=(cfg["api_key"], cfg["api_token"]), data=data)
        response.raise_for_status()
        payload = response.json()
    return payload.get("SMSMessage", {}).get("Status", "accepted")
