"""Analyse sémantique d'une offre via Google Gemini. Fallback = None (scoring déterministe)."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

log = logging.getLogger("veille.llm")

_PROMPT = Path(__file__).parents[1] / "prompts" / "analyze_offer.md"
# Modèles par défaut (surchargés par config.yaml > thresholds.llm.models).
_MODELS = ("gemini-3.5-flash", "gemini-flash-lite-latest")
_DESC_LIMIT = 4000
_MIN_INTERVAL = 2.5     # secondes entre 2 appels (marge sous les limites free tier)
_HTTP_TIMEOUT_MS = 25000
_last_call = [0.0]

# Disjoncteur : au 1er signe de quota épuisé, on coupe le LLM pour tout le run.
_circuit_open = [False]
_dead_models: set[str] = set()   # modèles 404 pour ce run -> on ne les rappelle pas
_QUOTA_MARKERS = ("resource_exhausted", "429", "rate_limit", "quota exceeded",
                  "quota_exceeded", "exceeded your current quota")


def reset_circuit() -> None:
    _circuit_open[0] = False
    _last_call[0] = 0.0
    _dead_models.clear()


def _throttle() -> None:
    wait = _MIN_INTERVAL - (time.monotonic() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.monotonic()


def _is_quota_error(exc: Exception) -> bool:
    msg = f"{type(exc).__name__} {exc}".lower()
    return any(m in msg for m in _QUOTA_MARKERS)


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
    if _circuit_open[0]:
        return False
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
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw[raw.find("{"):raw.rfind("}") + 1]
    return LLMAnalysis.model_validate(json.loads(raw))


def _call_model(client, model: str, prompt: str) -> str:
    _throttle()
    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "response_schema": LLMAnalysis,   # force un JSON conforme au schéma
            "temperature": 0.2,
            "automatic_function_calling": {"disable": True},
        },
    )
    return resp.text


def analyze(offer: dict, api_key: str | None, models: tuple[str, ...] | None = None) -> dict | None:
    if not api_key or _circuit_open[0]:
        return None
    try:
        from google import genai
    except ImportError:
        log.warning("google-genai absent : analyse LLM désactivée")
        return None

    client = genai.Client(
        api_key=api_key,
        http_options={"timeout": _HTTP_TIMEOUT_MS},
    )
    prompt = _build_prompt(offer)

    for model in (models or _MODELS):
        if model in _dead_models:
            continue
        for attempt in (1, 2):   # 2e essai = transitoire (500/503)
            try:
                raw = _call_model(client, model, prompt)
                return _parse(raw).model_dump()
            except (ValidationError, json.JSONDecodeError) as e:
                log.warning("LLM %s: JSON invalide (essai %d): %s", model, attempt, e)
                continue
            except Exception as e:  # réseau, quota, timeout, modèle inconnu…
                emsg = str(e).lower()
                if _is_quota_error(e):
                    log.warning("LLM: quota atteint — LLM coupé pour ce run, "
                                "fallback déterministe pour le reste")
                    _circuit_open[0] = True
                    return None
                if "not_found" in emsg or "404" in emsg or "no longer available" in emsg:
                    log.warning("LLM: modèle %s indisponible (à mettre à jour dans config.yaml)", model)
                    _dead_models.add(model)
                    break
                if attempt == 1 and ("server" in emsg or "503" in emsg or "500" in emsg
                                     or "unavailable" in emsg or "timeout" in emsg):
                    time.sleep(3)
                    continue
                log.warning("LLM %s: échec (%s)", model, type(e).__name__)
                break
    log.info("Analyse LLM indisponible pour « %s » — score déterministe", offer.get("title"))
    return None
