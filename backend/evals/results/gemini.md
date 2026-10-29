# Retrieval eval: `gemini` embeddings

73 answerable + 8 unanswerable questions over 5 documents. Chunk 1200 chars / 150 overlap, candidates 30.

| mode | hit@1 | hit@3 | hit@6 | MRR | median ms (database only) |
|---|---|---|---|---|---|
| vector | 0.81 | 0.93 | 0.96 | 0.871 | 15 |
| keyword | 0.74 | 0.82 | 0.89 | 0.786 | 9 |
| hybrid, keyword weight 1.0 | 0.81 | 0.89 | 0.93 | 0.856 | 20 |
| hybrid, keyword weight 0.5 | 0.81 | 0.92 | 0.95 | 0.861 | 16 |
| hybrid, keyword weight 0.25 | 0.78 | 0.93 | 0.95 | 0.857 | 18 |

## Refusal gate (hybrid)

`sim-only` refuses when the best cosine similarity is below the threshold. `sim+keyword` additionally requires zero keyword hits, so any OR-matched term disables refusal.

| threshold | sim-only: refused unanswerable | sim-only: wrongly refused | sim+keyword: refused unanswerable | sim+keyword: wrongly refused |
|---|---|---|---|---|
| 0.30 | 0% | 0% | 0% | 0% |
| 0.40 | 0% | 0% | 0% | 0% |
| 0.45 | 0% | 0% | 0% | 0% |
| 0.50 | 0% | 0% | 0% | 0% |
| 0.55 | 12% | 0% | 0% | 0% |
| 0.60 | 50% | 0% | 0% | 0% |
| 0.65 | 62% | 0% | 0% | 0% |
| 0.70 | 88% | 10% | 0% | 10% |

Best cosine similarity per question (hybrid):

- answerable: min 0.661, median 0.773, max 0.851
- unanswerable: min 0.548, median 0.625, max 0.704
- unanswerable questions with a keyword hit: 8/8
