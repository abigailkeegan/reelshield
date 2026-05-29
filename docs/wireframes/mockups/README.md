# Static HTML mockups

High-fidelity mockups of ReelShield's five key screens, rendered as
standalone HTML files using a CSS subset derived from
`frontend/static/css/main.css`. The mockups are openable directly in
any browser — no server, build step, or framework required.

These complement (rather than replace) the ASCII wireframes in
[`../wireframes.md`](../wireframes.md). The ASCII versions show
structural intent; these HTML versions show production-quality fidelity.

| # | File | Screen | Demonstrates |
|---|---|---|---|
| 1 | [`01-home.html`](01-home.html) | Home / Search | Search-led entry point, genre filter, poster results grid |
| 2 | [`02-movie-loaded.html`](02-movie-loaded.html) | Movie Loaded | MPA-disagreement badge (classic-ML output), warning cards by severity, K-Means Content Twins, "Similar Movies Without" recommender |
| 3 | [`03-discover.html`](03-discover.html) | Discover | Mood-first discovery with contrastive `avoid_tones` scoring; safety-score-based results grid |
| 4 | [`04-group-watch.html`](04-group-watch.html) | Group Watch | Multi-user sensitivity merging; per-film "why safe / one concern" reasoning |
| 5 | [`05-watchlist.html`](05-watchlist.html) | Watchlist | Personalized ranking with 🟢 / 🟡 / 🔴 safety badges |

## Design tokens

Each mockup is fully self-contained — the CSS is inlined inside a
`<style>` block in the HTML, so the file renders without any external
resources. The styles are a hand-curated subset of
`frontend/static/css/main.css` and reflect the same WCAG-compliant
design tokens as the live app (most recently, `--accent` darkened from
`#6c8eff` to `#4860e8` to clear the 4.5:1 contrast bar — see
[`../accessibility/README.md`](../accessibility/README.md)).

## How to open

Each file works standalone. Drop into any browser:

```bash
# from repo root
xdg-open docs/wireframes/mockups/01-home.html   # Linux
open       docs/wireframes/mockups/01-home.html # macOS
```

Or, since the CSS is inlined, the files render correctly via
`raw.githack.com` URLs too — useful for sharing a single rendered
mockup without cloning the repo. Example:
`https://raw.githack.com/abigailkeegan/movie-warnings/main/docs/wireframes/mockups/02-movie-loaded.html`
