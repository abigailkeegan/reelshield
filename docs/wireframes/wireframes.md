# ReelShield — Wireframes & Design Documentation

> **High-fidelity mockups:** every numbered screen below has a matching
> standalone HTML render under [`mockups/`](mockups/) — open any of
> those files in a browser for a production-quality view of the same
> screen described here. The ASCII below conveys structural intent;
> the HTML conveys finished fidelity.

## Screen 1: Home / Search

> **Mockup:** [`mockups/01-home.html`](mockups/01-home.html)

```
┌────────────────────────────────────────────────────┐
│  [Skip to content]                                 │
│                                                    │
│                  🎬 ReelShield                     │
│         AI-powered analysis — Gemini + TMDB    [⚙] │
│                                                    │
│  ┌──────────────────────────────────────────────┐  │
│  │ Search for a movie                           │  │
│  │ ┌──────────────────────────────────────────┐ │  │
│  │ │  e.g. Interstellar, The Dark Knight...   │ │  │
│  │ └──────────────────────────────────────────┘ │  │
│  │  3 results found                             │  │
│  │  ┌──────┐ ┌──────┐ ┌──────┐                 │  │
│  │  │poster│ │poster│ │poster│                 │  │
│  │  │      │ │      │ │      │                 │  │
│  │  │Title │ │Title │ │Title │                 │  │
│  │  │ 1997 │ │ 2023 │ │ 2018 │                 │  │
│  │  └──────┘ └──────┘ └──────┘                 │  │
│  └──────────────────────────────────────────────┘  │
│                                                    │
│        ○ Generating content warnings...            │
│                                                    │
└────────────────────────────────────────────────────┘
```

**Design decisions:**
- Search is full-width and immediately visible — primary action
- Poster grid for results: visual recognition faster than text lists
- Spinner with status messages prevents perceived abandonment during AI call
- ⚙ button top-right: discoverable but not distracting for primary users

---

## Screen 2: Movie Loaded (Desktop — 2-column)

> **Mockup:** [`mockups/02-movie-loaded.html`](mockups/02-movie-loaded.html)

```
┌──────────────────────────────────────────────────────────────┐
│ ⚠️ PHOTOSENSITIVE EPILEPSY WARNING                           │
│ This film contains flashing lights... [specific notes]       │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────┐  ┌────────────────────────────────┐
│ 🚫 Content Warnings      │  │ 💬 Ask Questions               │
│                          │  │                                │
│ Titanic (1997)           │  │ ┌──────────────────────────┐   │
│ [PG-13] [⚠️ Predicts     │  │ │ Ask me anything about    │   │
│  R/NC-17 · 87%]          │  │ │ this film.               │   │
│ [194 min] [Drama]        │  │                            │   │
│                          │  │    [You: Who is Rose?]     │   │
│ Our ML classifier        │  │                            │   │
│ estimates this film's    │  │  [AI: Rose is a young...]  │   │
│ profile better matches   │  │                            │   │
│ R/NC-17 than its PG-13   │  └──────────────────────────┘   │
│ rating.                  │  │                              │   │
│ ┌──────────────────────┐ │  │ ┌──────────────────┐ [Send] │   │
│ │ Overview blurb text  │ │  │ └──────────────────┘        │   │
│ │ from TMDB...         │ │  └────────────────────────────────┘
│ └──────────────────────┘ │
│                          │
│ Spoiler mode: Off  [○]   │
│                          │
│ ⚠️ Flashing Lights  Mild │
│    ✓ Confirmed           │
│    Brief flashing...     │
│                          │
│ Violence & Gore  Moderate│
│    ✓ Confirmed           │
│    Drowning, injuries... │
│                          │
│ Sexual Content  Moderate │
│    ✓ Confirmed           │
│                          │
│ Language  Mild           │
│    ✓ Confirmed           │
│                          │
│ Self-Harm  None          │
│    ✓ Confirmed absent    │
│                          │
│ 🎬 Content twins         │
│   (Adult drama cluster)  │
│  ┌────┐ ┌────┐ ┌────┐    │
│  │ B  │ │ C  │ │ D  │    │
│  │Δ.42│ │Δ.51│ │Δ.63│    │
│  └────┘ └────┘ └────┘    │
└──────────────────────────┘
```

**Design decisions:**
- Epilepsy banner always renders above everything else — critical safety info
- 2-column layout: warnings left, chat right — parallel use without scrolling
- Warnings sorted by severity descending (most severe first)
- Color-coded left border: red=severe, orange=moderate, green=mild, grey=none
- ✓ Confirmed in green builds trust; ~% in grey signals uncertainty
- Spoiler toggle above warnings: visible but default off
- MPA-disagreement badge sits next to the TMDB cert badge in amber when the LR classifier disagrees ≥70% confident; rendered in the same row as the cert so the comparison is the headline, not a footnote
- Content twins (K-Means neighbors) render below warnings as a small grid; Δ = Euclidean distance in 9-dim severity space, so smaller Δ = closer content-profile match

---

## Screen 3: Mobile (Single Column)

```
┌─────────────────────────┐
│ 🎬 ReelShield           │
│                      [⚙]│
├─────────────────────────┤
│ ⚠️ EPILEPSY WARNING      │
│ Brief flashing lights   │
│ during sinking sequence │
├─────────────────────────┤
│ Search for a movie      │
│ ┌─────────────────────┐ │
│ │ e.g. Titanic...     │ │
│ └─────────────────────┘ │
├─────────────────────────┤
│ 🚫 Content Warnings     │
│ Titanic (1997)          │
│ [PG-13][194 min][Drama] │
│ Overview blurb...       │
│                         │
│ ⚠️ Flashing Lights Mild  │
│   ✓ Confirmed           │
│                         │
│ Violence & Gore Moderate│
│   ✓ Confirmed           │
│ ...                     │
├─────────────────────────┤
│ 💬 Ask Questions        │
│ ┌─────────────────────┐ │
│ │ Chat history...     │ │
│ └─────────────────────┘ │
│ ┌──────────────┐[Send] │ │
│ └──────────────┘       │ │
└─────────────────────────┘
```

**Responsive behavior:** At <768px, columns stack. Epilepsy banner stays pinned to top. Chat moves below warnings.

---

## Screen 4: Prompt Editor Modal

```
┌──────────────────────────────────────────────────────┐
│  ✏️ Edit AI Prompt                                    │
│                                                      │
│  Customize how Gemini generates content warnings.    │
│  Required placeholders: {title} {year} {rating}      │
│  {genres} {overview} {keywords}                      │
│                                                      │
│  ┌────────────────────────────────────────────────┐  │
│  │ You are a film content expert...               │  │
│  │                                                │  │
│  │ Movie: "{title}" ({year})                      │  │
│  │ MPA Rating: {rating}                           │  │
│  │ ...                                            │  │
│  │ Return ONLY valid JSON...                      │  │
│  └────────────────────────────────────────────────┘  │
│                                                      │
│  [Save Prompt]  [Reset to Default]  [Cancel]         │
│                                                      │
│  ✓ Prompt updated. New searches will use this.       │
└──────────────────────────────────────────────────────┘
```

---

## Screen 5: Find Movies (Discover)

> **Mockup:** [`mockups/03-discover.html`](mockups/03-discover.html)

```
┌──────────────────────────────────────────────────────────────────────┐
│  Find Movies                                                          │
│  Choose your mood and the warnings you want to avoid — we'll find     │
│  the best matches from our movie cache.                               │
│                                                                       │
│  ┌──────────────────────────────────┐  ┌────────────────────────┐   │
│  │  How are you feeling? (optional) │  │  Warnings to avoid     │   │
│  ├──────────────────────────────────┤  │  (pick up to 3)        │   │
│  │  [ Light and easy            ]   │  ├────────────────────────┤   │
│  │  [ Some emotion, nothing heavy]  │  │  ☐ Violence & Gore     │   │
│  │  [ Can handle intense        ]   │  │  ☐ Self-Harm & Suicide │   │
│  │  [ Feel something deep       ]   │  │  ☐ Miscarriage         │   │
│  │  [ Comfort and familiarity   ]   │  │  ☐ Sexual Content      │   │
│  │  (one selected = highlighted;    │  │  ☐ Animal Abuse        │   │
│  │   click again to deselect)       │  │  ☐ Substance Use       │   │
│  └──────────────────────────────────┘  │  ☐ Language            │   │
│                                        │  ☐ Horror / Intensity  │   │
│  ┌──────────────────────────────────┐  │  ☐ Flashing Lights     │   │
│  │ 💭 You're feeling X — we'll      │  │  ⓘ "Pick up to 3"      │   │
│  │    look for Y                    │  └────────────────────────┘   │
│  │ Tones that fit:  [whimsical]…    │                               │
│  │ Tones to skip:   [grim]…         │                               │
│  └──────────────────────────────────┘                               │
│                                                                       │
│  [ Find Movies ]                                                      │
│                                                                       │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐                       │
│  │ Safe │ │ Safe │ │ Safe │ │ Safe │ │ Safe │   ← color-coded badge │
│  │ 100  │ │  92  │ │  88  │ │  80  │ │  72  │   per match quality   │
│  │poster│ │poster│ │poster│ │poster│ │poster│                       │
│  │Title │ │Title │ │Title │ │Title │ │Title │                       │
│  │ Mood │ │ Mood │ │ Mood │ │ Mood │ │ Mood │   ← mood fit %        │
│  │  …   │ │  …   │ │  …   │ │  …   │ │  …   │                       │
│  └──────┘ └──────┘ └──────┘ └──────┘ └──────┘                       │
└──────────────────────────────────────────────────────────────────────┘
```

**Design decisions:**
- Two-column layout puts emotional state and content rules side-by-side — neither is more important
- Mood is optional; warnings-to-avoid is the load-bearing filter
- Cap of 3 avoid categories is a soft constraint announced via `aria-live`, not a disabled checkbox — keeps the UI accessible
- Live mood-profile box updates as the user picks moods, so they understand what's about to be searched
- Results are scored 0–100 (safer = higher) with mood-fit shown separately

---

## Screen 6: Group Watch Finder

> **Mockup:** [`mockups/04-group-watch.html`](mockups/04-group-watch.html)

```
┌───────────────────────────────────────────────────────────────────────┐
│  👥 Group Watch Finder                                                 │
│  Add everyone in your group, merge their sensitivities, and find       │
│  movies safe for all.                                                  │
│                                                                        │
│  ┌─────────────────────────────────┐  ┌─────────────────────────────┐ │
│  │  Group Members                  │  │  Group Profile              │ │
│  ├─────────────────────────────────┤  ├─────────────────────────────┤ │
│  │  • Sarah  ✕                     │  │  This group needs movies    │ │
│  │    Violence, Animal abuse       │  │  free of violence, animal   │ │
│  │  • Leo  ✕                       │  │  abuse, and miscarriage.    │ │
│  │    Miscarriage, Self-harm       │  │                             │ │
│  │                                 │  │  All sensitivities:         │ │
│  │  ┌───────────────────────────┐  │  │  [Violence] [Animal abuse]  │ │
│  │  │ Member name…              │  │  │  [Miscarriage] [Self-harm]  │ │
│  │  └───────────────────────────┘  │  │                             │ │
│  │  Their sensitivities:           │  │  Avoid genres:              │ │
│  │  ☐ Violence  ☐ Self-Harm        │  │  [Horror] [War]             │ │
│  │  ☐ Animal    ☐ Sexual           │  │                             │ │
│  │  ☐ Substance ☐ Language         │  │  Suggested genres:          │ │
│  │  ☐ Horror    ☐ Flashing         │  │  [Family] [Comedy] [Animation] │
│  │  ☐ Miscarriage                  │  └─────────────────────────────┘ │
│  │  [+ Add Member]                 │                                  │
│  │                                 │  Find Movies                     │
│  │  [⚙ Merge Profiles]             │  Mood: [Any mood       ▼]        │
│  └─────────────────────────────────┘  Platform (optional): [____]     │
│                                                                        │
│                                       [ Find Movies ]                  │
│                                                                        │
│  3 movie(s) safe for everyone in the group:                            │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐                   │
│  │  100/100     │ │   95/100     │ │   88/100     │                   │
│  │  poster      │ │   poster     │ │   poster     │                   │
│  │  Title       │ │   Title      │ │   Title      │                   │
│  │  Why safe…   │ │   Why safe…  │ │   Why safe…  │                   │
│  │  One concern │ │  One concern │ │  One concern │                   │
│  └──────────────┘ └──────────────┘ └──────────────┘                   │
└───────────────────────────────────────────────────────────────────────┘
```

**Design decisions:**
- Member-builder on the left, profile-and-results on the right — read left-to-right
- Merge button stays disabled until ≥1 member is added (prevents empty-state confusion)
- Privacy: rejection messages refer to "the group", never name the individual member who triggered them
- Each result card includes both `why_safe` and `one_concern` so the group can debate trade-offs

---

## Screen 7: My Watchlist

> **Mockup:** [`mockups/05-watchlist.html`](mockups/05-watchlist.html)

```
┌───────────────────────────────────────────────────────────────────────┐
│  📋 My Watchlist                                                       │
│  Movies are ranked safest-to-most-triggering based on your             │
│  sensitivity profile.                                                  │
│                                                                        │
│  [ ⭐ Rank by My Sensitivities ]                                       │
│                                                                        │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐                  │
│  │ ① ✕      │ │ ② ✕      │ │ ③ ✕      │ │ ④ ✕      │                  │
│  │  poster  │ │  poster  │ │  poster  │ │  poster  │                  │
│  │  Title   │ │  Title   │ │  Title   │ │  Title   │                  │
│  │  1997    │ │  2019    │ │  2023    │ │  2017    │                  │
│  │ 🟢 Safe  │ │🟡 Mild   │ │🟡 Mild   │ │🔴 Strong │                  │
│  │ No trig… │ │Brief…    │ │Some…     │ │Heavy…    │                  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘                  │
│                                                                        │
│  (Rank ① in top-left, ✕ in top-right to remove)                       │
└───────────────────────────────────────────────────────────────────────┘
```

**Design decisions:**
- Rank badge (top-left) is the headline — at a glance the user sees what's safest tonight
- Color-coded watchlist badge (🟢 / 🟡 / 🔴) mirrors the severity scale used on the warning cards
- Remove (✕) is one click but lives in the top-right corner so it isn't fat-fingered while scanning
- Re-ranking is explicit, not automatic — running Gemini on the whole list is costly, so the user opts in

---

## Screen 8: Reviews & Ratings (inline on movie page)

```
┌──────────────────────────────────────────────────────────────────────┐
│  ⭐ Reviews & Ratings                                                 │
│                                                                       │
│  From critics & aggregators:                                          │
│  ┌────────┐  ┌─────────────┐  ┌────────────┐                          │
│  │ IMDb   │  │ Rotten      │  │ Metacritic │                          │
│  │ 7.8/10 │  │ Tomatoes 89%│  │ 74/100     │                          │
│  └────────┘  └─────────────┘  └────────────┘                          │
│  ─────────────────────────────────────────────────────────────────    │
│                                                                       │
│  Critic Reviews                                                       │
│  ┌────────────────────────────────────────────────────────────────┐   │
│  │ A. Critic — "An absorbing, careful film…"                       │   │
│  └────────────────────────────────────────────────────────────────┘   │
│  ─────────────────────────────────────────────────────────────────    │
│                                                                       │
│  User Reviews                                                         │
│  ┌────────────────────────────────────────────────────────────────┐   │
│  │ Your rating                                                     │   │
│  │ ★ ★ ★ ★ ☆                                                       │   │
│  │ Your review                                                     │   │
│  │ ┌─────────────────────────────────────────────────────────────┐ │   │
│  │ │ Share your thoughts...                                      │ │   │
│  │ └─────────────────────────────────────────────────────────────┘ │   │
│  │ [ Post Review ]                                                 │   │
│  │ (or: "Log in to post a review." if not authenticated)           │   │
│  └────────────────────────────────────────────────────────────────┘   │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐   │
│  │ @maria · ★★★★★ · 2 days ago                                    │   │
│  │ Watched with my kids and felt prepared for every scene…         │   │
│  └────────────────────────────────────────────────────────────────┘   │
│  ┌────────────────────────────────────────────────────────────────┐   │
│  │ @jordan · ★★★☆☆ · 1 week ago                                   │   │
│  │ Flashing-lights warning was spot-on, missed a couple of cuts…   │   │
│  └────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
```

**Design decisions:**
- Three trust layers stacked: external aggregators → critic reviews → user reviews — heaviest signal at top
- Star widget is keyboard-accessible (each star is a button with `aria-label`)
- Login gate is in-place: an inline note replaces the form, so the user isn't surprised by a redirect
- User reviews show username + star rating + relative timestamp — matches conventions users already know

---

## Screen 9: Sensitivity Profile Editor (Modal)

```
┌──────────────────────────────────────────────────────┐
│  🛡️ My Sensitivity Profile                            │
│                                                       │
│  Select the content categories you want to be warned │
│  about. This personalizes your watchlist ranking     │
│  and badges.                                          │
│                                                       │
│  ┌─────────────────────┐  ┌─────────────────────┐    │
│  │ ☑ Violence & Gore   │  │ ☐ Substance Use     │    │
│  │ ☑ Self-Harm/Suicide │  │ ☐ Language          │    │
│  │ ☐ Miscarriage       │  │ ☑ Horror / Intensity│    │
│  │ ☐ Sexual Content    │  │ ☑ Flashing Lights   │    │
│  │ ☐ Animal Abuse      │  │                     │    │
│  └─────────────────────┘  └─────────────────────┘    │
│                                                       │
│  [ Save Profile ]   [ Cancel ]                        │
│                                                       │
│  ✓ Profile saved.                                     │
└──────────────────────────────────────────────────────┘
```

**Design decisions:**
- Modal carries `role="dialog"` and `aria-modal="true"` — screen readers announce it as an interrupting layer
- Two-column grid keeps all 9 categories on one screen without scrolling on desktop
- "Save" is the primary button (filled), "Cancel" is the ghost button — visual weight matches intent
- Saved state announced via `aria-live="polite"` so assistive tech users get confirmation without focus shift

---

## Style Guide

### Colors
| Token | Hex | Usage |
|-------|-----|-------|
| `--bg` | `#0f1117` | Page background |
| `--surf` | `#1a1d27` | Card/panel surface |
| `--surf2` | `#242736` | Input fields, nested surfaces |
| `--bdr` | `#2e3347` | Borders |
| `--text` | `#e8eaf0` | Primary text |
| `--muted` | `#8891a8` | Secondary text, labels |
| `--accent` | `#6c8eff` | Primary interactive elements |
| `--mild` | `#4caf50` | Mild severity, confirmed absent |
| `--moderate` | `#ff9800` | Moderate severity |
| `--severe` | `#f44336` | Severe severity |
| `--epi-bdr` | `#ff2222` | Epilepsy banner border |

### Typography
- Font: `'Segoe UI', system-ui, sans-serif`
- Heading: 800 weight
- Body: 400 weight, 1.6 line-height
- Code/prompt: `'Courier New', monospace`

### Spacing
- Base unit: 8px
- Card padding: 24px
- Gap between cards: 20px
- Border radius: 8-12px

### Accessibility Rationale
- Dark theme chosen: reduces eye strain for photosensitive users (Persona 2)
- 3px focus outlines: clearly visible on dark backgrounds
- `aria-live="polite"` on search results and warnings: non-disruptive announcements
- `role="alert"` on epilepsy banner: immediate announcement, highest priority
- Color contrast targets WCAG AA (4.5:1 normal text, 3:1 UI components)

### Audit evidence

A Lighthouse accessibility audit run against the live container on
2026-05-15 scores **100 / 100** — all 26 audits pass, zero element
findings. The full report (raw JSON + HTML + a remediation-history
README documenting the four fixes that took the page from an initial
89/100 to 100/100) is committed under [`accessibility/`](accessibility/)
so the run is reproducible.
