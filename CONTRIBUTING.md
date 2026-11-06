# Contributing to Lexio

Thanks for taking the time. Issues and pull requests are welcome, from typo fixes to retrieval improvements.

By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md). To report a security problem, use [SECURITY.md](SECURITY.md) instead of a public issue.

## Before you start

- **Small fixes** (typos, docs, an obvious bug): open a pull request directly.
- **Anything larger** (a new feature, a change to chunking, retrieval, prompts or limits): open an issue first so we can agree on the approach before you spend time on it.
- Check [Known limitations](README.md#known-limitations) in the README. Some gaps, such as no OCR, are deliberate.

## Set up

You need Docker, [uv](https://docs.astral.sh/uv/) and Node.js 24. The full walkthrough is in the [README quick start](README.md#quick-start); in short:

```bash
docker compose up -d db
cp .env.example .env                 # tests need no API keys
cd backend && uv sync --group dev
cd ../frontend && cp .env.example .env.local && npm install
```

On Windows run the API with `uv run uvicorn app.main:app --reload`. Without `--reload` uvicorn uses an event loop that psycopg's async mode cannot run on.

## Checks to run before you open a pull request

CI runs the same checks on every pull request, and both jobs must pass.

```bash
cd backend
uv run ruff check .                  # lint and import order (line length 100, Python 3.12)
uv run pytest -q                     # unit and end-to-end tests against local Postgres

cd ../frontend
npm run typecheck
npm test
npm run build
```

## Guidelines

- **Keep a change focused.** One concern per pull request, with a description of what changed and why.
- **Add tests with behaviour changes.** Backend tests live in `backend/tests`, frontend tests are `frontend/lib/*.test.ts`. Tests must not need real API keys; use the `hash` embedding provider or mocks.
- **Database changes are new migrations.** Add the next numbered file to `backend/migrations` and never edit one that has been applied.
- **Retrieval, chunking or prompt changes need evaluation numbers.** Run the retrieval eval (`uv run --group local-embeddings python -m evals.run --provider local`, free and offline) and include the before and after results. The answer eval spends Groq's free daily tokens, so run it only when the change affects answers and say so in the pull request. Methods and results are in [docs/evaluation.md](docs/evaluation.md).
- **Stay inside the free tiers.** The project is designed to run on free Gemini, Groq, Neon and Vercel plans. Changes that raise per-question cost or token use need a reason.
- **Update the docs** that describe the behaviour you changed ([docs/api.md](docs/api.md), [docs/operations.md](docs/operations.md), the README).
- **Never commit secrets.** Only `.env.example` files are tracked. Sample documents added to `data/samples/` need a licence that allows redistribution, recorded in [data/samples/NOTICE.md](data/samples/NOTICE.md).
- **Next.js here is a recent major version** with breaking changes. Read the guide in `frontend/node_modules/next/dist/docs/` before writing framework code (see `frontend/AGENTS.md`).

## Commits and pull requests

- Work on a branch and open a pull request against `main`. Branch names such as `feat/...`, `fix/...`, `docs/...` and `perf/...` are the convention.
- Write the commit subject in the imperative mood, as a sentence that says what the change does ("Load only the cited PDF pages with HTTP range requests"). Explain the why in the body when it is not obvious.
- Fill in the pull request template. Link the issue it closes.

## Reporting bugs and asking for features

Use the issue forms. A good bug report says what you did, what you expected, what happened, and whether it was the live demo or a local run. Do not paste API keys, tokens or private documents.

## Licence

Contributions are released under the project's [MIT licence](LICENSE).
