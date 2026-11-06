<!-- markdownlint-disable-next-line MD041 -->
## What and why

<!-- What does this change, and why? Link the issue it closes: "Closes #123". -->

## How it was checked

- [ ] `uv run ruff check .` and `uv run pytest -q` pass (backend changes)
- [ ] `npm run typecheck`, `npm test` and `npm run build` pass (frontend changes)
- [ ] Tests added or updated for the behaviour that changed
- [ ] Retrieval, chunking or prompt change: before and after eval numbers are below

<!-- Paste eval results or screenshots here when relevant. -->

## Checklist

- [ ] Docs updated where behaviour changed (README, `docs/`)
- [ ] New database change is a new numbered file in `backend/migrations`
- [ ] No secrets, tokens or real `.env` files included
- [ ] Stays inside the free-tier limits, or the cost change is explained above
