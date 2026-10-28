# Retrieval eval: `local` embeddings

38 answerable + 8 unanswerable questions over 2 documents. Chunk 1200 chars / 150 overlap, candidates 30.

| mode | hit@1 | hit@3 | hit@6 | MRR | median ms |
|---|---|---|---|---|---|
| vector | 0.74 | 0.89 | 0.97 | 0.830 | 75 |
| keyword | 0.53 | 0.79 | 0.79 | 0.649 | 11 |
| hybrid, keyword weight 1.0 | 0.61 | 0.84 | 0.95 | 0.737 | 64 |
| hybrid, keyword weight 0.5 | 0.63 | 0.92 | 1.00 | 0.773 | 62 |
| hybrid, keyword weight 0.25 | 0.68 | 0.97 | 1.00 | 0.821 | 68 |

## Refusal gate (hybrid)

`sim-only` refuses when the best cosine similarity is below the threshold. `sim+keyword` additionally requires zero keyword hits, so any OR-matched term disables refusal.

| threshold | sim-only: refused unanswerable | sim-only: wrongly refused | sim+keyword: refused unanswerable | sim+keyword: wrongly refused |
|---|---|---|---|---|
| 0.30 | 0% | 0% | 0% | 0% |
| 0.40 | 12% | 0% | 0% | 0% |
| 0.45 | 50% | 0% | 0% | 0% |
| 0.50 | 75% | 0% | 0% | 0% |
| 0.55 | 100% | 3% | 0% | 3% |
| 0.60 | 100% | 18% | 0% | 18% |
| 0.65 | 100% | 42% | 0% | 42% |
| 0.70 | 100% | 76% | 0% | 76% |

Best cosine similarity per question (hybrid):

- answerable: min 0.548, median 0.676, max 0.786
- unanswerable: min 0.334, median 0.452, max 0.546
- unanswerable questions with a keyword hit: 8/8
