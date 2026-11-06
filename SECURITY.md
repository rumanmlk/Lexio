# Security policy

## Reporting a vulnerability

Please report security problems privately, not in a public issue or pull request.

1. **Preferred:** open a private report at
   [github.com/rumanmlk/Lexio/security/advisories/new](https://github.com/rumanmlk/Lexio/security/advisories/new).
   Only the maintainer can see it, and we can work on a fix in a private fork.
2. **Fallback:** email <rumanmlk123@gmail.com> with "Lexio security" in the subject.

Include what you found, the steps or request that reproduce it, which version or commit it affects, and what an attacker could do with it. Please do not include real personal data or other people's documents.

You will get an acknowledgement within 5 days. Lexio is a one-person project, so a fix can take longer, but you will be told where it stands and credited in the advisory unless you prefer not to be.

## Supported versions

Only the latest commit on `main` and the live deployment at [ask-lexio.vercel.app](https://ask-lexio.vercel.app) are supported. There are no maintained release branches.

## Scope

In scope:

- The FastAPI backend (`backend/`) and the Next.js web app (`frontend/`).
- Authentication and the token flow between them, per-user document isolation (one user reading, searching or deleting another user's documents), upload handling, the daily-limit counters, and prompt injection that makes the assistant leak data or act outside its answer.
- Secrets or personal data exposed through the repository, its history or its CI workflows.

Out of scope:

- Free-tier quota exhaustion or denial of service by sending many requests. The daily caps are a budget guard, not a security boundary (see [docs/operations.md](docs/operations.md)).
- Answers that are wrong or incomplete. That is an accuracy problem, so please open a normal issue (see [docs/evaluation.md](docs/evaluation.md) for what is measured).
- Prompt-injection attempts that only change the wording of an answer. The README already lists prompt injection as a known, reduced-but-not-removed risk.
- Vulnerabilities in third-party services (Vercel, Neon, Groq, Google) that are not caused by how Lexio uses them. Report those to the provider.
- Findings that need a modified client, a stolen account or physical access to the user's device.

## Handling secrets

Never put API keys, tokens or real `.env` files in an issue, pull request or commit. Only `.env.example` files belong in the repository. If you find a live key anywhere in the repository history, report it privately as above so it can be rotated.
