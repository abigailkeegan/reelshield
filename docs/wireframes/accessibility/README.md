# Accessibility Audit Evidence

External validation of the WCAG 2.1 AA claims in
[`../wireframes.md` § Style Guide › Accessibility Rationale](../wireframes.md).

## Method

| Detail | Value |
|---|---|
| Tool | Lighthouse 12.x (Chromium headless via `npx lighthouse`) |
| Latest run | 2026-05-15 (post-remediation) |
| Target | `http://localhost:7860/` (Docker container, parity with the live HF Space) |
| Categories audited | accessibility |
| Reports | [`lighthouse-home.report.html`](lighthouse-home.report.html) (human-readable), [`lighthouse-home.report.json`](lighthouse-home.report.json) (raw) |

## Score

**100 / 100** — all 26 Lighthouse accessibility audits pass, zero element findings.

## Remediation history

| Run | Score | Outstanding failures |
|---|---|---|
| 1 — initial audit (2026-05-15 morning) | 89 / 100 | 4 rules / 6 elements |
| 2 — after `<main>`/contrast/h2 fixes | 98 / 100 | 1 rule / 1 element (h4 inside groupSection) |
| 3 — after h4 → h3 promotion | **100 / 100** | none |

### Fixes applied between Run 1 and Run 3

1. **`color-contrast` (3 buttons)** — `--accent` darkened from `#6c8eff` (3.02:1 against white) to `#4860e8` (5.10:1). Single token change in `frontend/static/css/main.css`; cascades to every primary-button background.
2. **`aria-prohibited-attr`** — added `role="region"` to `#searchResults` so its `aria-label` has a valid target.
3. **`landmark-one-main`** — the page had a `<main id="main">` that was `display:none` until a movie loaded, which axe-core treats as no main landmark. Renamed it to `<section id="main">` and added a real, always-visible `<main>` wrapping the page's primary content (epilepsy banner through reviews section). The skip-link target (`#main`) still works because the id was preserved.
4. **`heading-order`** — promoted six top-level section headings from `h3` to `h2` (Discover, Group Watch, Watchlist, Content Twins, Recommendations, Reviews), since they are semantic peers of the epilepsy banner's `h2`. Three nested `h4`s inside Group Watch (Group Members / Group Profile / Find Movies) were then promoted to `h3` for the same reason. CSS selectors targeting these headings were updated in parallel.

## How to reproduce

```bash
docker compose up -d
npx lighthouse http://localhost:7860/ \
  --only-categories=accessibility \
  --output=json --output=html \
  --output-path=./docs/wireframes/accessibility/lighthouse-home \
  --chrome-flags="--headless --no-sandbox --disable-gpu" \
  --quiet
```

The committed reports in this folder are the output of the post-remediation run; running the command above against a current container should reproduce the 100/100 score.
