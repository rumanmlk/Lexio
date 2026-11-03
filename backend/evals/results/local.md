# Retrieval eval: `local` embeddings

106 answerable + 8 unanswerable questions over 9 documents. Chunk 1200 chars / 150 overlap, candidates 30.

| mode | hit@1 | hit@3 | hit@6 | MRR | median ms (database only) |
|---|---|---|---|---|---|
| vector | 0.60 | 0.79 | 0.88 | 0.710 | 19 |
| keyword | 0.66 | 0.78 | 0.87 | 0.728 | 13 |
| hybrid, keyword weight 1.0 | 0.67 | 0.78 | 0.91 | 0.743 | 25 |
| hybrid, keyword weight 0.5 | 0.64 | 0.80 | 0.91 | 0.733 | 22 |
| hybrid, keyword weight 0.25 | 0.62 | 0.83 | 0.90 | 0.727 | 19 |

## How far to trust these numbers (106 questions)

95% confidence intervals: Wilson for the hit rates, a bootstrap over questions for MRR. Two rows whose intervals overlap are not reliably different.

| mode | hit@1 | hit@3 | hit@6 | MRR |
|---|---|---|---|---|
| vector | 0.51-0.69 | 0.71-0.86 | 0.80-0.93 | 0.637-0.783 |
| keyword | 0.57-0.74 | 0.70-0.85 | 0.79-0.92 | 0.652-0.802 |
| hybrid, keyword weight 1.0 | 0.58-0.75 | 0.70-0.85 | 0.83-0.95 | 0.670-0.814 |
| hybrid, keyword weight 0.5 | 0.55-0.73 | 0.72-0.87 | 0.83-0.95 | 0.660-0.804 |
| hybrid, keyword weight 0.25 | 0.53-0.71 | 0.75-0.89 | 0.82-0.94 | 0.654-0.797 |

Paired difference in MRR, `hybrid, keyword weight 1.0` minus each other mode (positive: the default is better; an interval that contains 0 means no reliable difference):

- vs vector: +0.033 (95% CI -0.021 to +0.087)
- vs keyword: +0.016 (95% CI -0.037 to +0.071)
- vs hybrid, keyword weight 0.5: +0.010 (95% CI -0.012 to +0.033)
- vs hybrid, keyword weight 0.25: +0.017 (95% CI -0.013 to +0.048)

## Refusal gate (hybrid)

`sim-only` refuses when the best cosine similarity is below the threshold. `sim+keyword` additionally requires zero keyword hits, so any OR-matched term disables refusal.

| threshold | sim-only: refused unanswerable | sim-only: wrongly refused | sim+keyword: refused unanswerable | sim+keyword: wrongly refused |
|---|---|---|---|---|
| 0.30 | 0% | 0% | 0% | 0% |
| 0.40 | 0% | 0% | 0% | 0% |
| 0.45 | 0% | 0% | 0% | 0% |
| 0.50 | 12% | 0% | 0% | 0% |
| 0.55 | 50% | 0% | 0% | 0% |
| 0.60 | 75% | 7% | 0% | 7% |
| 0.65 | 100% | 19% | 0% | 19% |
| 0.70 | 100% | 49% | 0% | 49% |

Best cosine similarity per question (hybrid):

- answerable: min 0.557, median 0.702, max 0.864
- unanswerable: min 0.479, median 0.561, max 0.648
- unanswerable questions with a keyword hit: 8/8
