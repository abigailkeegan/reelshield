# Data Quality Audit: Mislabeled Content Warnings

**Date:** 2026-06-04
**Scope:** `content_warnings` table (418 films) in `movie_cache.db`

## Summary

A spot check of recommendation output surfaced a systematic labeling defect: **66 of 418 films (16%)** were stored with a severity of **0 in all nine warning categories**, and **56 of those carried confidence 1.0**, asserting with full confidence that the film contained none of the tracked content. Many were demonstrably wrong (Se7en, Snatch, Shutter Island, Dune: Part Two all labeled zero-violence). Because ReelShield exists to warn sensitive viewers, these entries were the worst kind of error: they passed every "avoid" filter and were surfaced to users as safe. The defect was re-assessed and corrected, reducing all-zero films from **66 to 1** (the single remaining film is a genuinely low-content documentary).

## How it was found

A user reported that one film kept topping the mood-based "Find Movies" results. Tracing the ranking showed the candidate pool was dominated by films that passed the avoid-warning filters trivially. Inspecting those films revealed the cause was not the ranking code but the underlying data: the films had no warnings to avoid because every severity was recorded as zero.

## Detection

The defect is detectable with a single pass over the warning JSON. A film is suspect when the maximum severity across all nine categories is zero:

```sql
-- films whose entire spoiler_free severity vector is zero
SELECT m.tmdb_id, m.title
FROM movies m
JOIN content_warnings c USING (tmdb_id)
WHERE (
    json_extract(c.warnings_json, '$.spoiler_free.violence_gore.severity')
  + json_extract(c.warnings_json, '$.spoiler_free.self_harm_suicide.severity')
  + json_extract(c.warnings_json, '$.spoiler_free.sexual_content_nudity.severity')
  + json_extract(c.warnings_json, '$.spoiler_free.substances.severity')
  + json_extract(c.warnings_json, '$.spoiler_free.language.severity')
  + json_extract(c.warnings_json, '$.spoiler_free.horror_intensity.severity')
  + json_extract(c.warnings_json, '$.spoiler_free.flashing_lights.severity')
  + json_extract(c.warnings_json, '$.spoiler_free.animal_abuse.severity')
  + json_extract(c.warnings_json, '$.spoiler_free.miscarriage_pregnancy_loss.severity')
) = 0;
```

| Cohort | Films |
|---|---:|
| All-zero severity vector | 66 |
| ...of those, high confidence (avg >= 0.4) | 56 |
| Genuinely low-content (verified after fix) | 1 |

The high-confidence subset is the dangerous one: a low-confidence all-zero entry is a recognizable "the model did not know this film" case, but a confidence-1.0 all-zero entry is a confident, wrong assertion that defeats every downstream check.

## Root cause

The entries originated from an earlier seeding pass whose responses returned all-zero severities at confidence 1.0. Nothing in the pipeline flagged "confident, yet empty" as implausible, so the rows were cached and treated as authoritative.

## Impact

- **Avoid filters defeated.** A viewer avoiding Violence and Gore was shown Se7en and Dune: Part Two as passing the filter.
- **Analytics skewed.** The all-zero rows depressed every per-decade and per-category average; correcting them raised observed severities (see [decade-analysis.md](decade-analysis.md)).
- **Models trained on bad features.** The MPA classifier and K-Means clusterer read these severity vectors as input.

## Remediation

`backend/reassess_warnings.py` re-runs the app's own warning generation against each suspect film's cached metadata and overwrites the stored warnings. Two safeguards keep the fix from making things worse:

- A failed or fallback generation is **never written**, so a bad call cannot replace existing data.
- The targeting query is idempotent: rerunning only touches films that are still all-zero.

## Results

| Outcome | Films |
|---|---:|
| Re-assessed and now carry content warnings | 65 |
| Re-confirmed genuinely clean | 1 |
| Failed / kept old data | 0 |

Before and after, severity on the spoiler_free vector:

| Film | Before (all 9) | After (violence / language / horror) |
|---|---|---|
| Se7en | 0 | 3 / 3 / 3 |
| Snatch | 0 | 3 / 3 / 2 |
| Shutter Island | 0 | 3 / 2 / 3 |
| Dune: Part Two | 0 | 3 / 1 / 2 |
| Speak | 0 | 2 / 1 / 2 (sexual content 2) |
| Rhythm is it! (documentary) | 0 | 0 / 0 / 0 (correctly unchanged) |

## Validation and downstream propagation

- All-zero count reduced from 66 to 1, verified by re-running the detection query.
- Both models retrained on the corrected data (MPA labelable films 360 to 367; K-Means now clusters all 418).
- The sanitized seed cache and the Hugging Face hydration dataset were refreshed, and the live Space was restarted and verified end to end (Se7en now reports violence severity 3 on the deployed app, previously 0).

## Prevention

The all-zero-at-high-confidence pattern is a cheap, durable data-quality assertion. Adding it as a seed-time check (reject or re-query any film whose entire severity vector is zero at confidence above the ghost floor) would stop the defect from recurring as the cache grows.
