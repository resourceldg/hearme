"""Proveedor LLM local vía Ollama.

Degrada con elegancia: si Ollama no está corriendo, `is_available()` devuelve
False y el modo estudio se marca no disponible sin tumbar el resto del pipeline.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

import httpx

from hearme.config import settings

logger = logging.getLogger(__name__)


class OllamaProvider:
    name = "ollama"

    def __init__(self, *, url: str | None = None, model: str | None = None) -> None:
        self.url = (url or settings.ollama_url).rstrip("/")
        self.model = model or settings.ollama_model

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                response = await client.get(f"{self.url}/api/tags")
                return response.status_code == 200
        except (httpx.HTTPError, OSError):
            return False

    async def models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{self.url}/api/tags")
            response.raise_for_status()
            return [m["name"] for m in response.json().get("models", [])]

    def _payload(self, prompt: str, system: str | None, *, stream: bool) -> dict:
        payload: dict = {
            "model": self.model,
            "prompt": prompt,
            "stream": stream,
            # Temperatura baja: en modo estudio se explica el texto, no se inventa.
            "options": {"temperature": 0.3, "num_ctx": 8192},
        }
        if system:
            payload["system"] = system
        return payload

    async def complete(self, prompt: str, *, system: str | None = None) -> str:
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(
                f"{self.url}/api/generate", json=self._payload(prompt, system, stream=False)
            )
            response.raise_for_status()
            return response.json().get("response", "").strip()

    async def stream(self, prompt: str, *, system: str | None = None) -> AsyncIterator[str]:
        async with (
            httpx.AsyncClient(timeout=300) as client,
            client.stream(
                "POST", f"{self.url}/api/generate", json=self._payload(prompt, system, stream=True)
            ) as response,
        ):
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if token := chunk.get("response"):
                    yield token
                if chunk.get("done"):
                    return
