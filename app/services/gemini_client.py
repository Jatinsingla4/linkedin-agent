"""Thin wrapper around the Gemini SDK.

Owns model configuration, quota-aware fallback to alternate models, retry, and
JSON extraction. The content writer builds prompts; this client just runs them.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import Settings

logger = logging.getLogger(__name__)

# Tried in order if the primary model hits a quota error. Keep these to
# currently-available models (the 2.0-flash family was retired by Google).
FALLBACK_MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-flash-latest"]

_CODE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def strip_code_fences(raw: str) -> str:
    """Remove markdown ```json fences the model sometimes adds."""
    return _CODE_FENCE.sub("", raw.strip())


class GeminiClient:
    def __init__(self, settings: Settings):
        self._settings = settings
        genai.configure(api_key=settings.gemini_api_key)
        self._primary = settings.gemini_model

    @staticmethod
    def _is_quota_error(err: Exception) -> bool:
        text = str(err).lower()
        return "resourceexhausted" in text or "quota" in text or "429" in text

    async def _run(self, model_name: str, prompt: str, *, temperature: float, max_tokens: int) -> str:
        model = genai.GenerativeModel(model_name)
        response = await model.generate_content_async(
            prompt,
            generation_config=genai.GenerationConfig(
                temperature=temperature,
                top_p=0.92,
                max_output_tokens=max_tokens,
            ),
        )
        return response.text.strip()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=60, max=120))
    async def generate_text(
        self, prompt: str, *, temperature: float = 0.85, max_tokens: int = 4096
    ) -> str:
        """Generate raw text, falling back across models on quota errors."""
        try:
            return await self._run(
                self._primary, prompt, temperature=temperature, max_tokens=max_tokens
            )
        except Exception as e:
            if not self._is_quota_error(e):
                raise
            for fallback in FALLBACK_MODELS:
                if fallback == self._primary:
                    continue
                try:
                    logger.warning("Primary model quota hit — trying fallback: %s", fallback)
                    return await self._run(
                        fallback, prompt, temperature=temperature, max_tokens=max_tokens
                    )
                except Exception as fe:
                    logger.warning("Fallback %s failed: %s", fallback, fe)
            raise

    async def generate_json(
        self, prompt: str, *, temperature: float = 0.85, max_tokens: int = 4096
    ) -> Any:
        """Generate and parse a JSON response (object or array)."""
        raw = await self.generate_text(prompt, temperature=temperature, max_tokens=max_tokens)
        clean = strip_code_fences(raw)
        try:
            return json.loads(clean)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse Gemini JSON: %s\nRaw: %s", e, raw[:500])
            raise ValueError(f"Gemini returned invalid JSON: {e}") from e
