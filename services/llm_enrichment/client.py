"""
Cliente LLM: OpenRouter (API OpenAI) u Ollama local.
Selección via LLM_PROVIDER=openrouter|ollama (por defecto openrouter si hay API key).
"""
import os
import json
import logging
import time

import httpx

from llm_enrichment.prompt import build_messages

logger = logging.getLogger(__name__)

TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "120"))
LLM_MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", "4"))
LLM_RETRY_BASE_SEC = float(os.environ.get("LLM_RETRY_BASE_SEC", "15"))

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:70b-instruct-q4_K_M")

OPENROUTER_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get(
    "OPENROUTER_MODEL", "google/gemini-2.0-flash-001"
)
OPENROUTER_APP_NAME = os.environ.get("OPENROUTER_APP_NAME", "Triaje IA")
OPENROUTER_HTTP_REFERER = os.environ.get("OPENROUTER_HTTP_REFERER", "http://localhost")


def get_provider() -> str:
    explicit = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if explicit in ("openrouter", "ollama"):
        return explicit
    if OPENROUTER_API_KEY:
        return "openrouter"
    return "ollama"


def parse_json_response(raw: str) -> dict:
    clean = raw.strip()
    if clean.startswith("```"):
        clean = clean.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(clean)


def call_ollama(transcripcion: str) -> dict:
    messages = build_messages(transcripcion)
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "format": "json",
    }
    resp = httpx.post(
        f"{OLLAMA_BASE_URL}/api/chat",
        json=payload,
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    raw = resp.json()["message"]["content"]
    return parse_json_response(raw)


def _post_with_retry(url: str, *, json_payload: dict, headers: dict) -> httpx.Response:
    last_err = None
    for attempt in range(LLM_MAX_RETRIES):
        try:
            resp = httpx.post(url, json=json_payload, headers=headers, timeout=TIMEOUT)
            if resp.status_code == 429:
                wait = LLM_RETRY_BASE_SEC * (2 ** attempt)
                logger.warning(f"OpenRouter 429 — reintento {attempt + 1}/{LLM_MAX_RETRIES} en {wait:.0f}s")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as e:
            last_err = e
            if e.response.status_code == 429 and attempt < LLM_MAX_RETRIES - 1:
                wait = LLM_RETRY_BASE_SEC * (2 ** attempt)
                time.sleep(wait)
                continue
            raise
    raise last_err or RuntimeError("OpenRouter: agotados reintentos por rate limit (429)")


def call_openrouter(transcripcion: str) -> dict:
    if not OPENROUTER_API_KEY:
        raise ValueError(
            "OPENROUTER_API_KEY no está definida. "
            "Añádela al .env o usa LLM_PROVIDER=ollama."
        )

    messages = build_messages(transcripcion)
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": messages,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": OPENROUTER_HTTP_REFERER,
        "X-Title": OPENROUTER_APP_NAME,
    }

    resp = _post_with_retry(
        f"{OPENROUTER_BASE_URL}/chat/completions",
        json_payload=payload,
        headers=headers,
    )
    data = resp.json()
    raw = data["choices"][0]["message"]["content"]
    return parse_json_response(raw)


def call_llm(transcripcion: str) -> dict:
    provider = get_provider()
    logger.info(f"LLM provider={provider}")
    if provider == "openrouter":
        return call_openrouter(transcripcion)
    return call_ollama(transcripcion)
