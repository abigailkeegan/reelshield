"""
Backend Tests
Run from project root: python -m pytest tests/ -v

The `client` fixture is defined in tests/conftest.py.
"""
import json

from tests.conftest import MOCK_WARNINGS


# ─── HEALTH CHECK ─────────────────────────────────────────────
def test_health_check(client):
    """App should respond to health check."""
    res = client.get('/health')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data['status'] == 'ok'


# ─── SEARCH ENDPOINT ──────────────────────────────────────────
def test_search_empty_query(client):
    """Empty search should return empty list."""
    res = client.post('/api/search',
                      json={'query': ''},
                      content_type='application/json')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data == []


def test_search_missing_query(client):
    """Missing query key should return empty list gracefully."""
    res = client.post('/api/search',
                      json={},
                      content_type='application/json')
    assert res.status_code == 200


# ─── PROMPT ENDPOINT ──────────────────────────────────────────
def test_get_prompt(client):
    """GET /api/prompt should return the default prompt."""
    res = client.get('/api/prompt')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert 'prompt' in data
    assert '{title}' in data['prompt']
    assert '{year}' in data['prompt']


def test_set_prompt_valid(client):
    """Valid prompt with all required placeholders should save."""
    new_prompt = "Analyze {title} ({year}). Rating: {rating}. Genres: {genres}. Overview: {overview}. Keywords: {keywords}. Return JSON."
    res = client.post('/api/prompt',
                      json={'prompt': new_prompt},
                      content_type='application/json')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data['ok'] is True


def test_set_prompt_missing_placeholder(client):
    """Prompt missing required placeholders should return error."""
    bad_prompt = "Just tell me about the movie and return JSON."
    res = client.post('/api/prompt',
                      json={'prompt': bad_prompt},
                      content_type='application/json')
    assert res.status_code == 400
    data = json.loads(res.data)
    assert 'error' in data
    assert 'missing' in data['error'].lower()


def test_set_prompt_empty(client):
    """Empty prompt should return error."""
    res = client.post('/api/prompt',
                      json={'prompt': ''},
                      content_type='application/json')
    assert res.status_code == 400


def test_reset_prompt(client):
    """Reset should restore default prompt."""
    # First set a custom prompt
    new_prompt = "Custom {title} {year} {rating} {genres} {overview} {keywords}"
    client.post('/api/prompt', json={'prompt': new_prompt})

    # Now reset
    res = client.post('/api/prompt/reset')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data['ok'] is True
    assert 'You are a film content expert' in data['prompt']


# ─── CHAT ENDPOINT ────────────────────────────────────────────
def test_chat_no_movie_loaded(client):
    """Chat without a loaded movie should return 400."""
    res = client.post('/api/chat',
                      json={'message': 'Is this movie scary?', 'spoiler_mode': False},
                      content_type='application/json')
    assert res.status_code == 400
    data = json.loads(res.data)
    assert 'error' in data


# ─── WARNING STRUCTURE VALIDATION ─────────────────────────────
def test_warning_structure():
    """Warning JSON should contain all required categories."""
    required_categories = [
        'violence_gore', 'self_harm_suicide',
        'miscarriage_pregnancy_loss', 'sexual_content_nudity',
        'animal_abuse', 'substances', 'language',
        'horror_intensity', 'flashing_lights'
    ]
    warnings = MOCK_WARNINGS['spoiler_free']
    for cat in required_categories:
        assert cat in warnings, f"Missing category: {cat}"
        assert 'severity' in warnings[cat]
        assert 'confidence' in warnings[cat]
        assert 'notes' in warnings[cat]
        assert 0 <= warnings[cat]['severity'] <= 3
        assert 0.0 <= warnings[cat]['confidence'] <= 1.0


def test_severity_scale():
    """Severity values should be in valid range 0-3."""
    for cat, data in MOCK_WARNINGS['spoiler_free'].items():
        assert data['severity'] in [0, 1, 2, 3], \
            f"{cat} has invalid severity: {data['severity']}"


def test_confidence_scale():
    """Confidence values should be between 0 and 1."""
    for cat, data in MOCK_WARNINGS['spoiler_free'].items():
        assert 0.0 <= data['confidence'] <= 1.0, \
            f"{cat} has invalid confidence: {data['confidence']}"
