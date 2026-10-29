# Answer eval: `gemini` embeddings + Groq `openai/gpt-oss-120b`

> **Historical run, not current.** Measured on the two UN documents only, before the NDA, GDPR and Model Services Contract guidance were added, and with the earlier keyword ranking (`ts_rank_cd`, weight 0.25). Kept for reference; see the README for current results.

38 answerable, 8 out-of-scope, 7 near-miss and 1 follow-up questions, plus 1 prompt-injection case. Retrieval top-6, similarity threshold 0.65. Took 1991s; 9 LLM errors (excluded).

| check | result |
|---|---|
| gold page was in the context sent to the LLM | 100% (38/38) |
| answer was grounded (cited a source, did not refuse) | 100% (38/38) |
| a cited source is on a gold page | 100% (38/38) |
| out-of-scope questions refused | 100% (8/8) |
| near-miss questions answered honestly (refused or said it is not specified) | 100% (3/3) |
| follow-ups: gold page in context, searching the raw follow-up | 0% (0/1) |
| follow-ups: gold page in context, after rewriting with the conversation | 0% (0/1) |
| follow-ups: a cited source is on a gold page | 0% (0/1) |
| planted instruction obeyed (lower is better) | no |
| injected document still answered correctly | yes |

A correct citation needs the right page retrieved first, so `cited a gold page` is bounded by the `in the context` row. Near-miss questions are on-topic but the document gives no such figure, so the similarity gate cannot catch them; the model has to.
