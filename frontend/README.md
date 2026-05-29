# Frontend

ReelShield's UI is a **single Jinja-rendered page** served by Flask at
`GET /`. Every screen the user touches (search, movie-loaded, chat,
discover, group watch, watchlist, reviews, sensitivities modal,
prompt editor) lives in `templates/index.html` and is shown or hidden
via JS.

```
frontend/
├── templates/
│   └── index.html        # markup only — links to /static/css/main.css and /static/js/app.js
└── static/
    ├── css/main.css      # design tokens + all component styles (~340 lines)
    └── js/app.js         # auth, search, chat, discover, group, watchlist, reviews, content twins, sensitivities (~950 lines)
```

## Why one page, three files

This is a deliberate choice, not a missing build step:

- **No router, no framework.** The UI is one page with modals and
  conditionally-rendered sections. Adding React/Vite/etc. would
  pay a build pipeline cost we don't get any benefit from.
- **No bundler.** CSS and JS are plain files served directly by
  Flask's static handler. The browser hits three URLs (`/`,
  `/static/css/main.css`, `/static/js/app.js`) and renders. No
  build step, no source maps, no JS framework runtime.
- **One reader at a time.** Two devs aren't editing the frontend
  in parallel. The capstone scope makes a small fan-out easier to
  reason about than a 20-component component tree.

If any of those stops being true (multi-page nav, second dev,
framework adoption, JS past ~3000 lines), the next step is to break
the body into Jinja includes and split `app.js` by section.

## File map

`templates/index.html` is organized top-to-bottom in this order:

| Section | What's there |
|---|---|
| `<head>` | Meta, title, `<link>` to `/static/css/main.css` |
| Sensitivity modal | `id="sensitivityModal"`. Opens from the gear button. |
| Epilepsy banner | `id="epiBar"`. `role="alert"`, always renders above the fold. |
| Header + auth | `id="authBar"`. Login/register, current user badge. |
| Search | `<main>`. Search box, results grid, movie-loaded layout. |
| Movie meta | `id="movieMeta"`. Title, year, TMDB cert badge, optional MPA-disagreement badge (`.badge-mpa-warn`), runtime, genres. |
| Warnings | `id="wList"`. Spoiler toggle (`id="spBtn"`) and the warning cards. |
| Content twins | `id="twinsSection"`. K-Means cluster neighbors (`/api/content_twins/<tmdb_id>`), rendered as a `.twins-grid` of `.twin-card` items with Δ distances. |
| Chat | `id="chatBox"`. Message stream + input. |
| Discover | `id="discoverSection"`. Mood column plus avoid-warnings column. Free-text mood input, contrastive scoring against `avoid_tones`. |
| Group Watch | `id="groupSection"`. Member builder plus merged profile. |
| Watchlist | `id="watchlistSection"`. Ranked cards. |
| Recommendations | `id="recoSection"`. "Similar movies without..." Re-ranked with sentence-transformer embeddings. |
| Reviews | `id="reviewSection"`. External ratings plus critic plus user reviews. |
| Prompt editor modal | `id="promptModal"` |
| `<script>` | `<script src="/static/js/app.js" defer>` — all behavior (auth, search, chat, discover, group, watchlist, reviews, content twins, sensitivities). Functions named after the section they drive. |

`static/css/main.css` is the source of truth for design tokens
(`--bg`, `--accent`, severity colors). It mirrors the style guide in
`docs/wireframes/wireframes.md` § Style Guide.

## Accessibility contract

The UI is built to the WCAG 2.1 AA targets documented in
`docs/wireframes/wireframes.md` § Accessibility Rationale:

- `aria-live="polite"` on results, status, and form-feedback regions
- `role="alert"` on the epilepsy banner (highest-priority announcement)
- `role="dialog"` plus `aria-modal="true"` on every modal
- `aria-label` on every icon-only button
- 3px focus outlines, 4.5:1 text contrast, 3:1 UI contrast

`tests/test_frontend.py::test_accessibility_hooks_present` enforces a
floor on these. If any of them disappear, CI fails.

## API contract

Every `fetch('/api/...')` URL in the page must match a real backend
route. `tests/test_frontend.py::test_frontend_api_calls_resolve_to_backend_routes`
regex-extracts the URLs and checks each one against
`app.url_map`. That's the test that catches dead UI before it ships.
