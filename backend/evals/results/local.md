# Retrieval eval: `local` embeddings

73 answerable + 8 unanswerable questions over 5 documents. Chunk 1200 chars / 150 overlap, candidates 30.

| mode | hit@1 | hit@3 | hit@6 | MRR | median ms (database only) |
|---|---|---|---|---|---|
| vector | 0.66 | 0.84 | 0.88 | 0.752 | 13 |
| keyword | 0.74 | 0.82 | 0.89 | 0.786 | 7 |
| hybrid, keyword weight 1.0 | 0.74 | 0.82 | 0.90 | 0.794 | 13 |
| hybrid, keyword weight 0.5 | 0.67 | 0.81 | 0.92 | 0.761 | 13 |
| hybrid, keyword weight 0.25 | 0.66 | 0.86 | 0.89 | 0.755 | 13 |

## Refusal gate (hybrid)

`sim-only` refuses when the best cosine similarity is below the threshold. `sim+keyword` additionally requires zero keyword hits, so any OR-matched term disables refusal.

| threshold | sim-only: refused unanswerable | sim-only: wrongly refused | sim+keyword: refused unanswerable | sim+keyword: wrongly refused |
|---|---|---|---|---|
| 0.30 | 0% | 0% | 0% | 0% |
| 0.40 | 0% | 0% | 0% | 0% |
| 0.45 | 0% | 0% | 0% | 0% |
| 0.50 | 12% | 0% | 0% | 0% |
| 0.55 | 62% | 0% | 0% | 0% |
| 0.60 | 75% | 10% | 0% | 10% |
| 0.65 | 100% | 23% | 0% | 23% |
| 0.70 | 100% | 53% | 0% | 53% |

Best cosine similarity per question (hybrid):

- answerable: min 0.557, median 0.698, max 0.847
- unanswerable: min 0.464, median 0.546, max 0.641
- unanswerable questions with a keyword hit: 8/8
