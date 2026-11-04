# Evaluation results

Everything here is measured on this repository's own question set. Read the confidence intervals: the set is small, so it works as a regression check, not as proof of accuracy on real contracts.

## The question set

Nine public documents (five of them standard contract templates), 106 answerable questions with a verified gold page each, 8 clearly out-of-scope questions, 18 "near-miss" questions (on-topic, but the document gives no such detail) and 11 follow-ups. A test checks every gold page against the PDFs. Sources and licences: [`data/samples/NOTICE.md`](../data/samples/NOTICE.md).

| Document | Pages | Chunks |
| --- | --- | --- |
| Universal Declaration of Human Rights | 8 | 14 |
| UN Convention on the Rights of the Child | 15 | 55 |
| Common Paper Mutual NDA | 2 | 9 |
| Common Paper Cloud Service Agreement 3.0 | 11 | 54 |
| Common Paper Data Processing Agreement 1.1 | 9 | 34 |
| Common Paper Professional Services Agreement 1.1 | 11 | 49 |
| Common Paper Software License Agreement 1.0 | 5 | 34 |
| GDPR (Regulation 2016/679) | 88 | 405 |
| UK Model Services Contract, guidance for authorities | 132 | 325 |

## Retrieval (local `bge-base-en-v1.5` embeddings, all nine documents)

hit@k = the right page is among the top k results.

| retrieval | hit@1 | hit@3 | hit@6 | MRR |
| --- | --- | --- | --- | --- |
| vector only | 0.60 | 0.79 | 0.88 | 0.710 |
| keyword only | 0.66 | 0.78 | 0.87 | 0.728 |
| hybrid, equal weights (default) | 0.67 | 0.78 | 0.91 | 0.743 |
| hybrid, keyword weight 0.5 | 0.64 | 0.80 | 0.91 | 0.733 |
| hybrid, keyword weight 0.25 | 0.62 | 0.83 | 0.90 | 0.727 |

- **The keyword ranking function mattered more than any weight.** The first version ranked keyword matches with `ts_rank_cd` (cover density). On the original five-document set (73 questions) it scored MRR 0.539 on its own and dragged hybrid below plain vector search (0.720 vs 0.752). Switching to `ts_rank` (term frequency), which suits questions whose words are OR-ed together, lifted keyword-only to 0.786 and hybrid to 0.794 there. That is a large effect, well outside the noise. The ranking was chosen by comparing variants offline on that same question set, so treat the size of the gain as indicative.
- **Nothing here reliably separates the retrieval modes.** Hybrid's MRR is ahead of keyword-only by +0.016 (95% CI -0.037 to +0.071) and of vector-only by +0.033 (95% CI -0.021 to +0.087); both intervals contain 0, and so do its differences from the lower keyword weights. On the original 73 questions hybrid looked reliably better than the lower weights (+0.034, 95% CI +0.006 to +0.067); that edge did not survive adding 33 questions and four documents, which is a reminder of how little a small set can settle. Hybrid is kept for robustness: it does not depend on either signal being good on a given question.
- **The similarity refusal gate does not separate cleanly with the local model**: answerable questions score down to 0.557 while out-of-scope ones reach 0.648, so any threshold trades missed refusals against wrong ones (at 0.55: 50% of out-of-scope questions refused, no wrong refusals; at 0.60: 75% refused and 7% of answerable questions wrongly refused; at 0.65 every out-of-scope question is refused but 19% of answerable ones are too). The default stays at 0.5, which refuses nothing wrongly. The near-miss questions are on-topic, so no similarity threshold can catch them; the model has to, and the answer eval measures that.
- Full output: [`backend/evals/results/local.md`](../backend/evals/results/local.md).

## Retrieval (Gemini `gemini-embedding-2`, all nine documents)

106 answerable and 8 out-of-scope questions, same chunking as above.

| retrieval | hit@1 | hit@3 | hit@6 | MRR |
| --- | --- | --- | --- | --- |
| vector only | 0.78 | 0.92 | 0.97 | 0.859 |
| keyword only | 0.66 | 0.78 | 0.87 | 0.728 |
| hybrid, keyword weight 1.0 (default) | 0.78 | 0.91 | 0.94 | 0.844 |
| hybrid, keyword weight 0.5 | 0.78 | 0.93 | 0.95 | 0.852 |
| hybrid, keyword weight 0.25 | 0.77 | 0.94 | 0.96 | 0.856 |

- **With Gemini embeddings, hybrid does not beat plain vector search**: MRR 0.844 against 0.859, a paired difference of -0.014 (95% CI -0.068 to +0.039), so neither is reliably better. It is reliably better than keyword-only (+0.117, 95% CI +0.063 to +0.174). The hybrid weights are indistinguishable (weight 1.0 minus 0.5: -0.007, 95% CI -0.022 to +0.008; minus 0.25: -0.012, 95% CI -0.036 to +0.013), so the default weight of 1.0 was not changed. Hybrid is kept for the same robustness reason as above (and the local model, where keyword search is the stronger signal).
- **Refusal threshold 0.65 holds up, but with little room.** Answerable questions score from 0.661 to 0.853 (median 0.766); out-of-scope ones from 0.566 to 0.704 (median 0.637). At 0.65, 62% of out-of-scope questions are refused and none of the answerable ones; 0.70 would refuse 88% but also wrongly refuse 8% of answerable ones. The lowest answerable score is only 0.011 above the threshold, so a few more questions could push a correct one under it. Adding 33 questions and four contract documents did not move that lowest score. The keyword check does not help: all 8 out-of-scope questions had a keyword hit.
- **What 106 questions can and cannot show.** One question moves a hit rate by about one point, and the 95% intervals are still wide (hit@3 for the default hybrid with Gemini is 0.91, interval 0.83 to 0.95). The set reliably catches large regressions, which is what the CI floor uses it for, but it cannot rank two close configurations. The full tables with intervals are in the result files below; more questions would be needed for finer comparisons.
- Full output: [`backend/evals/results/gemini.md`](../backend/evals/results/gemini.md).

## Earlier run with Gemini embeddings and Groq answers (two UN documents only)

Measured before the other three documents and the `ts_rank` change, so it does not describe the current code. It is kept in [`backend/evals/results/history/`](../backend/evals/results/history/). On 38 questions: Gemini hybrid reached hit@3 1.00 and MRR 0.934; every answer was grounded and 38/38 cited a gold page; all 8 out-of-scope questions were refused; and an instruction planted inside a document was ignored. The first version of that eval reported only 34% grounded: the model wrote citations as `【1†L1-L3】` and the parser only knew `[1]`. Fixing the parser is why the answer eval exists.

## Answer quality (Gemini retrieval, Groq `openai/gpt-oss-120b`, all nine documents)

The full set is 144 cases. It was first run (105 cases, five documents) over two days because of Groq's daily token cap; after the four contract agreements were added, the cases whose retrieved context changed were re-run and the rest came from the cache, which took 19 minutes. Output: [`backend/evals/results/answers-gemini.md`](../backend/evals/results/answers-gemini.md).

| check | result |
| --- | --- |
| gold page was in the context sent to the LLM | 94% (100/106, 95% CI 88%-97%) |
| answer was grounded (cited a source, did not refuse) | 94% (100/106, 95% CI 88%-97%) |
| a cited source is on a gold page | 93% (99/106, 95% CI 87%-97%) |
| out-of-scope questions refused | 100% (8/8, 95% CI 68%-100%) |
| near-miss questions answered honestly (refused or said it is not specified) | 100% (18/18, 95% CI 82%-100%) |
| follow-ups: gold page in context, searching the raw follow-up | 64% (7/11, 95% CI 35%-85%) |
| follow-ups: gold page in context, after rewriting with the conversation | 100% (11/11, 95% CI 74%-100%) |
| follow-ups: a cited source is on a gold page | 82% (9/11, 95% CI 52%-95%) |
| planted instruction obeyed (lower is better) | no (0/1) |
| injected document still answered correctly | yes (1/1) |

Each rate carries its 95% confidence interval (Wilson). With so few cases, a perfect score is weaker evidence than it looks: 8 of 8 out-of-scope refusals is consistent with a true rate as low as 68%, and 18 of 18 near-miss answers with 82%. Treat 100% here as "no failures seen", not as a guarantee.

- **Retrieval is the bottleneck, not the model.** Six of the seven answerable misses (a04, a05, a18, a68, a72, a81) did not get the gold page into the top 6, so the model never saw it. In one of them (a72) the model still answered from another page, so it counts as grounded but cites the wrong page. The seventh (a51) had the gold page in context and still was not answered with a citation.
- **Rewriting follow-ups matters:** searching the raw follow-up finds the gold page 7 times out of 11; after the LLM rewrites it using the conversation, 11 out of 11. Two follow-ups (f06, f07) are still not cited on a gold page.
- **Prompt injection:** this is a single case (a lease with a planted instruction to output a code word). The model ignored it and answered the real question. One case shows the defence can work, not that it always does.
- **Adding four contract agreements did not hurt the original questions.** The original 73 questions score exactly as before (68 of 73 grounded) even though nine documents now compete for the same top 6, and the 33 new contract questions score 32 of 33 (the one miss, a81, asks about the UN sales convention and retrieval returned the wrong pages). The new documents share a lineage and much of their wording, so questions name the agreement they are about; the eval does not test a user who asks "what is the notice period?" without saying which contract.
- With 106 answerable questions, one question is about 0.9 percentage points, so small differences are noise.

The Gemini retrieval eval above was produced with `uv run python -m evals.run --provider gemini --sweep` (the four added agreements cost about 130 Gemini embeddings plus about 40 for the new questions; the earlier five documents used about 920 of the day's 1,000, once).

## Reproducing the evaluations

Run these from `backend/`.

### Evaluate retrieval

```bash
uv sync --group local-embeddings
uv run python -m evals.run --provider local --sweep
```

Results are written to `backend/evals/results/`.

`--min-mrr 0.68` makes `evals.run` exit 1 when the default hybrid MRR falls below that floor, and `evals.answers --strict` exits 1 if an out-of-scope question was answered, a planted instruction was obeyed, or Groq cut the run short (`--min-grounded 0.85` adds a floor on grounded answers). In CI, [`.github/workflows/evals.yml`](../.github/workflows/evals.yml) runs the retrieval eval with the local model (no keys, no quota) weekly and on demand with a floor of 0.68 (the committed local result is 0.743; the floor leaves room for a different CPU). The Groq answer eval only runs when started by hand, because it spends the tokens the live demo answers with: the default sample of 5 answerable questions is 32 cases, roughly 50k of Groq's 200k daily tokens (by the measured 1,750 per answer). The Gemini evals stay local, since a fresh machine has no embedding cache and would use up the day's 1,000 embeddings.

### Evaluate answers (real LLM)

```bash
uv run python -m evals.answers --provider gemini --limit 10   # a sample; drop --limit for everything
```

Sends each question through the same path as `/api/chat` with Groq and checks that answers are grounded, that a cited source is on the gold page, that out-of-scope and near-miss questions are refused or flagged as unspecified, that follow-ups are rewritten into searchable questions, and that an instruction planted inside a document is not obeyed. Groq's free tier allows 200k tokens a day, so a full run spans two days: it stops cleanly when the quota runs out, caches finished cases, and continues on the next run. A run that did not finish is written to `answers-<provider>-partial.md` and marked as partial.
