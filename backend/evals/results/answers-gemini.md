# Answer eval: `gemini` embeddings + Groq `openai/gpt-oss-120b`

73 answerable, 8 out-of-scope, 14 near-miss, 9 follow-up questions, plus the prompt-injection case. Retrieval top-6, similarity threshold 0.65. 0 LLM errors (excluded).

| check | result |
|---|---|
| gold page was in the context sent to the LLM | 93% (68/73) |
| answer was grounded (cited a source, did not refuse) | 93% (68/73) |
| a cited source is on a gold page | 92% (67/73) |
| out-of-scope questions refused | 100% (8/8) |
| near-miss questions answered honestly (refused or said it is not specified) | 100% (14/14) |
| follow-ups: gold page in context, searching the raw follow-up | 56% (5/9) |
| follow-ups: gold page in context, after rewriting with the conversation | 100% (9/9) |
| follow-ups: a cited source is on a gold page | 78% (7/9) |
| planted instruction obeyed (lower is better) | no |
| injected document still answered correctly | yes |

A correct citation needs the right page retrieved first, so `cited a gold page` is bounded by the `in the context` row. Near-miss questions are on-topic but the document gives no such figure, so the similarity gate cannot catch them; the model has to.
