import json

import pytest

from pipeline import llm_analyze
from pipeline.llm_analyze import analyze, should_analyze

VALID = {
    "category": "A", "category_confidence": 0.9, "profile_fit": 82,
    "schedule_compatibility": 75, "technical_level_required": "light",
    "ai_business_interest": 88, "professional_interest": 70, "red_flags": [],
    "student_arrangement_mentioned": True, "score_adjustment": 6,
    "reasoning": "Bon match généraliste IA/business.",
}


class _Resp:
    def __init__(self, text):
        self.text = text


class _FakeModels:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = 0

    def generate_content(self, **kw):
        self.calls += 1
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return _Resp(out)


class _FakeClient:
    def __init__(self, outputs):
        self.models = _FakeModels(outputs)


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch):
    monkeypatch.setattr(llm_analyze, "_MIN_INTERVAL", 0.0)


@pytest.fixture
def patched(monkeypatch):
    holder = {}

    def factory(outputs):
        client = _FakeClient(outputs)
        holder["client"] = client
        fake_genai = type("g", (), {"Client": staticmethod(lambda **kw: client)})
        monkeypatch.setattr(llm_analyze, "genai", fake_genai, raising=False)
        import sys
        mod = type(sys)("google")
        mod.genai = fake_genai
        monkeypatch.setitem(sys.modules, "google", mod)
        monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
        return client

    return factory


def test_no_api_key_returns_none_without_call():
    assert analyze({"title": "x"}, None) is None


def test_valid_json_parsed(patched):
    patched([json.dumps(VALID)])
    res = analyze({"title": "Founder Associate", "description": "..."}, "k")
    assert res["category"] == "A"
    assert res["score_adjustment"] == 6


def test_broken_json_retries_then_fallback(patched):
    client = patched(["not json", "still {bad", "{oops", "{oops"])
    res = analyze({"title": "x", "description": "y"}, "k")
    assert res is None
    assert client.models.calls >= 2


def test_markdown_fenced_json_is_recovered(patched):
    patched(["```json\n" + json.dumps(VALID) + "\n```"])
    assert analyze({"title": "x", "description": "y"}, "k")["profile_fit"] == 82


def test_should_analyze_gates(cfg):
    thr = cfg["thresholds"]["llm"]["min_prescore"]
    assert should_analyze({"pre_score": thr + 5, "excluded": False, "llm_analysis": None}, cfg)
    assert not should_analyze({"pre_score": thr - 5, "excluded": False, "llm_analysis": None}, cfg)
    assert not should_analyze({"pre_score": 90, "excluded": True, "llm_analysis": None}, cfg)
    assert not should_analyze({"pre_score": 90, "excluded": False, "llm_analysis": {}}, cfg)
