"""
Frontend smoke tests.

Renders the single-page UI through the Flask test client and asserts
structural invariants — the page loads, the expected sections and
accessibility hooks are present, and every fetch('/api/...') call in
the JS resolves to a real backend route.

Run from project root:  python -m pytest tests/ -v
"""
import re


# ─── PAGE LOADS ───────────────────────────────────────────────
def test_index_renders(client):
    """GET / should return a 200 HTML page that mentions ReelShield."""
    res = client.get('/')
    assert res.status_code == 200
    body = res.data.decode('utf-8')
    assert '<title>ReelShield</title>' in body
    assert 'ReelShield' in body
    assert '<html' in body.lower()


# ─── CORE UI SECTIONS PRESENT ─────────────────────────────────
def test_index_has_required_sections(client):
    """All four primary user-facing sections must render."""
    body = client.get('/').data.decode('utf-8')
    required_ids = [
        'authBar',          # Login / register
        'discoverSection',  # Find Movies
        'groupSection',     # Group Watch Finder
        'watchlistSection', # Watchlist
        'epiBar',           # Photosensitive epilepsy banner
        'sensitivityModal', # Sensitivities editor modal
    ]
    for sid in required_ids:
        assert f'id="{sid}"' in body, f'Missing required section: id="{sid}"'


# ─── ACCESSIBILITY HOOKS ──────────────────────────────────────
def test_accessibility_hooks_present(client):
    """Page should carry the WCAG hooks promised in the style guide."""
    body = client.get('/').data.decode('utf-8')

    # Live regions for non-disruptive updates (search results, status messages)
    assert 'aria-live="polite"' in body

    # Epilepsy banner uses role="alert" for highest-priority announcement
    assert 'role="alert"' in body

    # Modal dialogs are marked correctly for screen readers
    assert 'role="dialog"' in body
    assert 'aria-modal="true"' in body

    # At least a handful of form controls carry aria-label
    aria_label_count = body.count('aria-label=')
    assert aria_label_count >= 5, (
        f'Expected at least 5 aria-label attributes, found {aria_label_count}'
    )


# ─── WARNING CATEGORIES STAY IN SYNC WITH BACKEND ─────────────
def test_warning_categories_render_in_ui(client):
    """All 9 backend warning categories should be reachable from the UI."""
    body = client.get('/').data.decode('utf-8').lower()
    expected_categories = [
        'violence',           # violence_gore
        'self-harm',          # self_harm_suicide
        'miscarriage',        # miscarriage_pregnancy_loss
        'sexual',             # sexual_content_nudity
        'animal',             # animal_abuse
        'substance',          # substances
        'language',
        'horror',             # horror_intensity
        'flashing',           # flashing_lights
    ]
    for term in expected_categories:
        assert term in body, f'Warning category term missing from UI: "{term}"'


# ─── FRONTEND ↔ BACKEND API CONTRACT ──────────────────────────
def test_frontend_api_calls_resolve_to_backend_routes(client):
    """
    Every URL the JS fetches via /api/... must correspond to a real
    backend route, so we never ship dead UI like the IMDb-import button
    again.
    """
    # The page + the extracted JS bundle together form the live UI surface;
    # search both for /api/... references.
    body = client.get('/').data.decode('utf-8')
    js = client.get('/static/js/app.js').data.decode('utf-8')
    surface = body + '\n' + js

    # Pull out every '/api/...' literal the JS references. Covers single
    # quotes, double quotes, and backtick template literals.
    api_urls = set(re.findall(r"""['"`](/api/[A-Za-z0-9_/{}$:.-]+)['"`]""", surface))
    assert api_urls, 'No /api/... URLs found in rendered page — selector broken?'

    # Backend's url_map; convert each rule into a regex that matches the
    # literal-with-placeholder URLs the JS uses (e.g. ${tmdb_id} or 597).
    import importlib
    import backend.app as app_module
    importlib.reload(app_module)
    backend_routes = [str(r) for r in app_module.app.url_map.iter_rules()]

    def matches_any_route(url):
        for rule in backend_routes:
            # Replace Flask <int:foo> / <foo> placeholders with a wildcard
            pattern = re.sub(r'<[^>]+>', r'[^/]+', rule)
            # The JS sometimes uses ${variable} or :id-style placeholders
            js_normalized = re.sub(r'\$\{[^}]+\}', 'X', url)
            if re.fullmatch(pattern, js_normalized):
                return True
        return False

    missing = [u for u in sorted(api_urls) if not matches_any_route(u)]
    assert not missing, (
        f'Frontend calls these API URLs that do not exist in the backend: {missing}'
    )


# ─── STYLE GUIDE — DARK THEME TOKENS APPLIED ──────────────────
def test_dark_theme_css_variables_present(client):
    """The style guide's CSS variables should be present in the static stylesheet."""
    # CSS now lives in /static/css/main.css; ensure the page links to it and
    # the file itself carries the documented design tokens.
    body = client.get('/').data.decode('utf-8')
    assert '/static/css/main.css' in body, 'Page does not link the extracted stylesheet'

    css = client.get('/static/css/main.css').data.decode('utf-8')
    expected_tokens = ['--bg', '--surf', '--text', '--accent', '--severe', '--moderate', '--mild']
    for token in expected_tokens:
        assert token in css, f'Style-guide token missing from stylesheet: "{token}"'
