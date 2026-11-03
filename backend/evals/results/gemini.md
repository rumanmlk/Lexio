# Retrieval eval: `gemini` embeddings

106 answerable + 8 unanswerable questions over 9 documents. Chunk 1200 chars / 150 overlap, candidates 30.

| mode | hit@1 | hit@3 | hit@6 | MRR | median ms (database only) |
|---|---|---|---|---|---|
| vector | 0.78 | 0.92 | 0.97 | 0.859 | 17 |
| keyword | 0.66 | 0.78 | 0.87 | 0.728 | 11 |
| hybrid, keyword weight 1.0 | 0.78 | 0.91 | 0.94 | 0.844 | 20 |
| hybrid, keyword weight 0.5 | 0.78 | 0.93 | 0.95 | 0.852 | 18 |
| hybrid, keyword weight 0.25 | 0.77 | 0.94 | 0.96 | 0.856 | 17 |

## How far to trust these numbers (106 questions)

95% confidence intervals: Wilson for the hit rates, a bootstrap over questions for MRR. Two rows whose intervals overlap are not reliably different.

| mode | hit@1 | hit@3 | hit@6 | MRR |
|---|---|---|---|---|
| vector | 0.70-0.85 | 0.85-0.95 | 0.92-0.99 | 0.805-0.910 |
| keyword | 0.57-0.74 | 0.70-0.85 | 0.79-0.92 | 0.652-0.802 |
| hybrid, keyword weight 1.0 | 0.70-0.85 | 0.83-0.95 | 0.88-0.97 | 0.784-0.903 |
| hybrid, keyword weight 0.5 | 0.70-0.85 | 0.87-0.97 | 0.89-0.98 | 0.795-0.906 |
| hybrid, keyword weight 0.25 | 0.69-0.84 | 0.88-0.97 | 0.91-0.99 | 0.802-0.907 |

Paired difference in MRR, `hybrid, keyword weight 1.0` minus each other mode (positive: the default is better; an interval that contains 0 means no reliable difference):

- vs vector: -0.014 (95% CI -0.068 to +0.039)
- vs keyword: +0.117 (95% CI +0.063 to +0.174)
- vs hybrid, keyword weight 0.5: -0.007 (95% CI -0.022 to +0.008)
- vs hybrid, keyword weight 0.25: -0.012 (95% CI -0.036 to +0.013)

## Refusal gate (hybrid)

`sim-only` refuses when the best cosine similarity is below the threshold. `sim+keyword` additionally requires zero keyword hits, so any OR-matched term disables refusal.

| threshold | sim-only: refused unanswerable | sim-only: wrongly refused | sim+keyword: refused unanswerable | sim+keyword: wrongly refused |
|---|---|---|---|---|
| 0.30 | 0% | 0% | 0% | 0% |
| 0.40 | 0% | 0% | 0% | 0% |
| 0.45 | 0% | 0% | 0% | 0% |
| 0.50 | 0% | 0% | 0% | 0% |
| 0.55 | 0% | 0% | 0% | 0% |
| 0.60 | 50% | 0% | 0% | 0% |
| 0.65 | 62% | 0% | 0% | 0% |
| 0.70 | 88% | 8% | 0% | 8% |

Best cosine similarity per question (hybrid):

- answerable: min 0.661, median 0.766, max 0.853
- unanswerable: min 0.566, median 0.637, max 0.704
- unanswerable questions with a keyword hit: 8/8
