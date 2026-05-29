"""
Shared pytest fixtures for backend and frontend tests.

Both tests/test_app.py and tests/test_frontend.py use the `client`
fixture below to spin up the Flask app against an in-memory SQLite
database with the Gemini SDK mocked out.
"""
import json
import os
import sys

import pytest

# Make `import backend.app` work from anywhere
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


MOCK_WARNINGS = {
    "disclaimer": "Gemini knowledge-based",
    "spoiler_free": {
        "violence_gore": {"severity": 2, "confidence": 1.0, "notes": "Drowning and injuries during sinking"},
        "self_harm_suicide": {"severity": 1, "confidence": 0.8, "notes": "Brief scene on the bow"},
        "miscarriage_pregnancy_loss": {"severity": 0, "confidence": 1.0, "notes": ""},
        "sexual_content_nudity": {"severity": 2, "confidence": 1.0, "notes": "Brief nudity in art scene"},
        "animal_abuse": {"severity": 0, "confidence": 1.0, "notes": ""},
        "substances": {"severity": 1, "confidence": 1.0, "notes": "Social drinking"},
        "language": {"severity": 1, "confidence": 1.0, "notes": "Some mild language"},
        "horror_intensity": {"severity": 1, "confidence": 1.0, "notes": "Intense disaster sequences"},
        "flashing_lights": {"severity": 1, "confidence": 1.0, "notes": "Brief flashing during sinking sequence"}
    },
    "spoiler_full": {
        "violence_gore": {"severity": 2, "confidence": 1.0, "notes": "Passengers drown when the Titanic sinks after striking an iceberg; Jack dies of hypothermia in the water"},
        "self_harm_suicide": {"severity": 1, "confidence": 0.8, "notes": "Rose contemplates jumping off the stern; Jack talks her down"},
        "miscarriage_pregnancy_loss": {"severity": 0, "confidence": 1.0, "notes": ""},
        "sexual_content_nudity": {"severity": 2, "confidence": 1.0, "notes": "Rose poses nude for Jack's drawing"},
        "animal_abuse": {"severity": 0, "confidence": 1.0, "notes": ""},
        "substances": {"severity": 1, "confidence": 1.0, "notes": "Champagne and cigars throughout the first-class scenes"},
        "language": {"severity": 1, "confidence": 1.0, "notes": "Mild language during the chase below decks"},
        "horror_intensity": {"severity": 1, "confidence": 1.0, "notes": "Sinking sequence with people falling, chaos, screaming"},
        "flashing_lights": {"severity": 1, "confidence": 1.0, "notes": "Brief flashing when the ship loses power and the lights flicker"}
    }
}


@pytest.fixture
def client(monkeypatch):
    """Create a Flask test client with mocked external dependencies."""
    monkeypatch.setenv("TMDB_API_KEY", "test_tmdb_key")
    monkeypatch.setenv("GEMINI_API_KEY", "test_gemini_key")
    monkeypatch.setenv("DB_PATH", ":memory:")

    import unittest.mock as mock
    mock_genai = mock.MagicMock()
    mock_model = mock.MagicMock()
    mock_model.generate_content.return_value.text = json.dumps(MOCK_WARNINGS)
    mock_genai.GenerativeModel.return_value = mock_model
    monkeypatch.setitem(sys.modules, 'google.generativeai', mock_genai)

    import importlib
    import backend.app as app_module
    importlib.reload(app_module)

    app_module.app.config['TESTING'] = True
    with app_module.app.test_client() as test_client:
        yield test_client
