# Answer eval: `gemini` embeddings + Groq `openai/gpt-oss-120b`

> **PARTIAL RUN: 103 of 105 cases finished.** Stopped: Groq quota is used up; it resets in about 11 minutes. Run it again to continue; finished cases are cached.

73 answerable, 8 out-of-scope, 14 near-miss, 8 follow-up questions, plus the prompt-injection case. Retrieval top-6, similarity threshold 0.65. 0 LLM errors (excluded).

| check | result |
|---|---|
| gold page was in the context sent to the LLM | 93% (68/73) |
| answer was grounded (cited a source, did not refuse) | 93% (68/73) |
| a cited source is on a gold page | 92% (67/73) |
| out-of-scope questions refused | 100% (8/8) |
| near-miss questions answered honestly (refused or said it is not specified) | 100% (14/14) |
| follow-ups: gold page in context, searching the raw follow-up | 50% (4/8) |
| follow-ups: gold page in context, after rewriting with the conversation | 100% (8/8) |
| follow-ups: a cited source is on a gold page | 75% (6/8) |
| planted instruction obeyed (lower is better) | not run yet |
| injected document still answered correctly | not run yet |

A correct citation needs the right page retrieved first, so `cited a gold page` is bounded by the `in the context` row. Near-miss questions are on-topic but the document gives no such figure, so the similarity gate cannot catch them; the model has to.
