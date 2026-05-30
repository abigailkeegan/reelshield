"""
Tests for the pure logic in backend/backfill_spoiler_full.py: eligibility
detection and the additive spoiler_full construction. No Gemini or DB needed.
"""
from backend.backfill_spoiler_full import (
    build_spoiler_full,
    needs_backfill,
    parse_gemini_json,
)


def _sf_block():
    """A populated spoiler_free block: one present category, the rest absent."""
    return {
        "violence_gore": {"severity": 2, "confidence": 0.9, "notes": "Intense fights"},
        "self_harm_suicide": {"severity": 0, "confidence": 1.0, "notes": ""},
        "miscarriage_pregnancy_loss": {"severity": 0, "confidence": 1.0, "notes": ""},
        "sexual_content_nudity": {"severity": 0, "confidence": 1.0, "notes": ""},
        "animal_abuse": {"severity": 0, "confidence": 1.0, "notes": ""},
        "substances": {"severity": 1, "confidence": 0.8, "notes": "Social drinking"},
        "language": {"severity": 0, "confidence": 1.0, "notes": ""},
        "horror_intensity": {"severity": 0, "confidence": 1.0, "notes": ""},
        "flashing_lights": {"severity": 0, "confidence": 1.0, "notes": ""},
    }


def test_needs_backfill_true_when_only_spoiler_free():
    assert needs_backfill({"spoiler_free": _sf_block()}) is True


def test_needs_backfill_false_when_spoiler_full_populated():
    w = {"spoiler_free": _sf_block(), "spoiler_full": _sf_block()}
    assert needs_backfill(w) is False


def test_needs_backfill_false_when_no_usable_spoiler_free():
    empty = {c: {"severity": 0, "confidence": 0.3, "notes": ""} for c in _sf_block()}
    assert needs_backfill({"spoiler_free": empty}) is False


def test_build_spoiler_full_copies_severity_and_uses_gemini_notes():
    sf = _sf_block()
    notes = {"violence_gore": "Vincent shoots Marvin in the car after the diner robbery."}
    full = build_spoiler_full(sf, notes)
    # Severity and confidence are copied verbatim from spoiler_free.
    assert full["violence_gore"]["severity"] == 2
    assert full["violence_gore"]["confidence"] == 0.9
    # Gemini's spoiler-full note is used where provided.
    assert "Vincent" in full["violence_gore"]["notes"]
    # Missing categories fall back to the spoiler_free note (here, empty).
    assert full["self_harm_suicide"]["notes"] == ""
    # Every category is present.
    assert set(full) == set(sf)


def test_build_spoiler_full_falls_back_when_gemini_note_empty():
    """An empty/whitespace Gemini note must fall back to the spoiler_free note,
    so spoiler_full is never blanker than spoiler_free (the all-empty-response case)."""
    sf = _sf_block()  # violence_gore has a real note; substances too
    notes = {"violence_gore": "", "substances": "   "}  # Gemini returned blanks
    full = build_spoiler_full(sf, notes)
    assert full["violence_gore"]["notes"] == "Intense fights"
    assert full["substances"]["notes"] == "Social drinking"


def test_parse_gemini_json_strips_code_fences():
    raw = '```json\n{"violence_gore": "x"}\n```'
    assert parse_gemini_json(raw) == {"violence_gore": "x"}
