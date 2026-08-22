"""
Cliente de IA compatible con OpenAI.

Usa el SDK oficial `openai` con base_url personalizada.
Soporta:
- chat normal (no stream)
- chat con streaming (generador)
- Conteo de tokens aproximado
"""
from __future__ import annotations

import logging
from typing import Iterator

from openai import OpenAI
from openai import APIError, APIConnectionError, RateLimitError, APITimeoutError

from .config import settings

log = logging.getLogger(__name__)


class AIClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ):
        self.api_key = api_key or settings.ai_api_key
        self.base_url = base_url or settings.ai_api_base
        self.model = model or settings.ai_model
        if not self.api_key:
            raise RuntimeError("AI_API_KEY no configurado")
        self._client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=60.0)

    def chat(self, messages: list[dict], temperature: float = 0.7, max_tokens: int | None = None) -> str:
        """Llamada bloqueante. Devuelve el texto completo."""
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=False,
            )
            return (resp.choices[0].message.content or "").strip()
        except (APIError, APIConnectionError, APITimeoutError, RateLimitError) as e:
            log.error("Error en chat IA: %s", e)
            raise

    def chat_stream(
        self, messages: list[dict], temperature: float = 0.7, max_tokens: int | None = None
    ) -> Iterator[str]:
        """Generador que yield fragmentos de texto a medida que llegan."""
        try:
            stream = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                piece = getattr(delta, "content", None)
                if piece:
                    yield piece
        except (APIError, APIConnectionError, APITimeoutError, RateLimitError) as e:
            log.error("Error en stream IA: %s", e)
            raise

    def list_models(self) -> list[str]:
        try:
            resp = self._client.models.list()
            return [m.id for m in resp.data]
        except Exception as e:
            log.error("Error listando modelos: %s", e)
            return []
