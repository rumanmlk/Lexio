# Retrieval eval: `gemini` embeddings

> **Historical run, not current.** Measured on the two UN documents only, before the NDA, GDPR and Model Services Contract guidance were added, and with the earlier keyword ranking (`ts_rank_cd`, weight 0.25). Kept for reference; see the README for current results.

38 answerable + 8 unanswerable questions over 2 documents. Chunk 1200 chars / 150 overlap, candidates 30.

| mode | hit@1 | hit@3 | hit@6 | MRR | median ms (database only) |
|---|---|---|---|---|---|
| vector | 0.84 | 1.00 | 1.00 | 0.917 | 8 |
| keyword | 0.53 | 0.76 | 0.79 | 0.643 | 8 |
| hybrid, keyword weight 1.0 | 0.74 | 0.95 | 0.97 | 0.836 | 10 |
| hybrid, keyword weight 0.5 | 0.84 | 1.00 | 1.00 | 0.912 | 10 |
| hybrid, keyword weight 0.25 | 0.87 | 1.00 | 1.00 | 0.934 | 10 |

## Refusal gate (hybrid)

`sim-only` refuses when the best cosine similarity is below the threshold. `sim+keyword` additionally requires zero keyword hits, so any OR-matched term disables refusal.

| threshold | sim-only: refused unanswerable | sim-only: wrongly refused | sim+keyword: refused unanswerable | sim+keyword: wrongly refused |
|---|---|---|---|---|
| 0.30 | 0% | 0% | 0% | 0% |
| 0.40 | 0% | 0% | 0% | 0% |
| 0.45 | 0% | 0% | 0% | 0% |
| 0.50 | 0% | 0% | 0% | 0% |
| 0.55 | 12% | 0% | 0% | 0% |
| 0.60 | 88% | 0% | 0% | 0% |
| 0.65 | 100% | 0% | 0% | 0% |
| 0.70 | 100% | 18% | 0% | 18% |

Best cosine similarity per question (hybrid):

- answerable: min 0.661, median 0.748, max 0.81
- unanswerable: min 0.507, median 0.581, max 0.641
- unanswerable questions with a keyword hit: 8/8
