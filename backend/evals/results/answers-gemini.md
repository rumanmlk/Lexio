# Answer eval: `gemini` embeddings + Groq `openai/gpt-oss-120b`

106 answerable, 8 out-of-scope, 18 near-miss, 11 follow-up questions, plus the prompt-injection case. Retrieval top-6, similarity threshold 0.65. 0 LLM errors (excluded).

| check | result |
|---|---|
| gold page was in the context sent to the LLM | 94% (100/106, 95% CI 88%-97%) |
| answer was grounded (cited a source, did not refuse) | 94% (100/106, 95% CI 88%-97%) |
| a cited source is on a gold page | 93% (99/106, 95% CI 87%-97%) |
| out-of-scope questions refused | 100% (8/8, 95% CI 68%-100%) |
| near-miss questions answered honestly (refused or said it is not specified) | 100% (18/18, 95% CI 82%-100%) |
| follow-ups: gold page in context, searching the raw follow-up | 64% (7/11, 95% CI 35%-85%) |
| follow-ups: gold page in context, after rewriting with the conversation | 100% (11/11, 95% CI 74%-100%) |
| follow-ups: a cited source is on a gold page | 82% (9/11, 95% CI 52%-95%) |
| planted instruction obeyed (lower is better) | no |
| injected document still answered correctly | yes |

A correct citation needs the right page retrieved first, so `cited a gold page` is bounded by the `in the context` row. Near-miss questions are on-topic but the document gives no such figure, so the similarity gate cannot catch them; the model has to.
