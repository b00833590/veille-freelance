"""Analyse sémantique d'une offre via Google Gemini. Fallback = None (scoring déterministe)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

log = logging.getLogger("veille.llm")

_PROMPT = Path(__file__).parents[1] / "prompts" / "analyze_offer.md"
_MODELS = ("gemini-2.5-flash", "gemini-2.5-flash-lite")
_DESC_LIMIT = 4000


class LLMAnalysis(BaseModel):
    category: str = "none"
    category_confidence: float = 0.0
    profile_fit: int = 0
    schedule_compatibility: int = 0
    technical_level_required: str = "moderate"
    ai_business_interest: int = 0
    professional_interest: int = 0
    red_flags: list[str] = Field(default_factory=list)
    student_arrangement_mentioned: bool = False
    score_adjustment: int = 0
    reasoning: str = ""


def should_analyze(offer: dict, cfg: dict) -> bool:
    if offer.get("excluded") or offer.get("llm_analysis") is not None:
        return False
    return offer.get("pre_score", 0) >= cfg["thresholds"]["llm"]["min_prescore"]


def _build_prompt(offer: dict) -> str:
    tpl = _PROMPT.read_text(encoding="utf-8")
    repl = {
        "{{TITLE}}": str(offer.get("title", "")),
        "{{COMPANY}}": str(offer.get("company", "") or "n/a"),
        "{{LOCATION}}": str(offer.get("location", "") or "n/a"),
        "{{CONTRACT}}": str(offer.get("contract_type", "") or "n/a"),
        "{{DESCRIPTION}}": str(offer.get("description", "") or "")[:_DESC_LIMIT],
    }
    for k, v in repl.items():
        tpl = tpl.replace(k, v)
    return tpl


def _parse(raw: str) -> LLMAnalysis:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw[raw.find("{"):raw.rfind("}") + 1]
    return LLMAnalysis.model_validate(json.loads(raw))


def _call_model(client, model: str, prompt: str) -> str:
    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "temperature": 0.2,
            "automatic_function_calling": {"disable": True},
        },
    )
    return resp.text


def analyze(offer: dict, api_key: str | None) -> dict | None:
    if not api_key:
        return None
    try:
        from google import genai
    except ImportError:
        log.warning("google-genai absent : analyse LLM désactivée")
        return None

    client = genai.Client(api_key=api_key)
    prompt = _build_prompt(offer)

    for model in _MODELS:
        for attempt in (1, 2):
            try:
                raw = _call_model(client, model, prompt)
                return _parse(raw).model_dump()
            except (ValidationError, json.JSONDecodeError) as e:
                log.warning("LLM %s: réponse invalide (essai %d): %s", model, attempt, e)
            except Exception as e:  # réseau, quota, etc.
                log.warning("LLM %s: échec (essai %d): %s", model, attempt, type(e).__name__)
                break  # on passe au modèle suivant
    log.error("Analyse LLM impossible pour '%s' — fallback déterministe", offer.get("title"))
    return None
