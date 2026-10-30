# Deploying Lexio (Vercel + Neon, all free tiers)

This starts from nothing deployed. You will end up with:

| Piece | Where | What it is |
|---|---|---|
| **Web** | Vercel project 1, root directory `frontend` | The Next.js app, Google sign-in, and the route that authorises PDF uploads |
| **API** | Vercel project 2, root directory `backend` | The FastAPI app (a Python function) |
| **Database** | Neon | Postgres with pgvector: chunks, vectors, counters, the sample PDFs |
| **PDF storage** | Vercel Blob (private store) | PDFs that signed-in users upload |
| **Sign-in** | Google Cloud OAuth client | The only sign-in provider |
| **Tracing** | Langfuse (optional) | Timings and flags per question |

The browser talks to the web app for pages and sign-in, and **directly to the API** for data (with a 5-minute token the web app mints). That is why the two are separate projects on separate domains and the API needs CORS.

> **Status of this guide.** The code paths (direct upload, registration, streaming, tracing, migrations) are covered by tests that fake Vercel Blob and Langfuse. Nothing here has been run against real Vercel, Neon, Blob or Langfuse accounts, because none existed when it was written. Step 9 is a checklist that proves each assumption on the real thing; do it before telling anyone about the site, and report what breaks.

## 0. Before you start

- The repository is pushed to GitHub (Vercel deploys from it).
- You have installed Node and, for seeding, `uv` and system Python (see the README).
- Pick the two Vercel project names now, because each project's production URL (`https://<name>.vercel.app`) is needed in the other one's settings. This guide calls them `lexio-web` and `lexio-api`. Names are global on Vercel, so you may need different ones; use yours everywhere below.
- Vercel's free **Hobby** plan is for non-commercial use.

Free-tier facts (as read from the providers' pages on 2026-10-29; they change, so check):

- **Neon Free:** 1 GB per project, 100 compute-hours a month, scales to zero after 5 minutes idle (not configurable), 5 GB data transfer a month.
- **Vercel Functions (Hobby):** 2 GB memory, 300 s maximum duration, 4.5 MB request and response body limit for a non-streamed body, Python bundle up to 500 MB.
- **Vercel Blob (Hobby):** 1 GB storage, 10,000 simple and 2,000 advanced operations a month (every upload is an advanced operation). **Going over blocks Blob for 30 days, with no way to pay your way out on Hobby.** The code therefore limits upload tickets per user per day (`UPLOAD_TICKET_LIMIT`, default 30) and deletes uploads that were never registered after two hours.

## 1. Accounts and keys

1. **GitHub**: the repo.
2. **Vercel**: sign up with GitHub.
3. **Neon** (neon.com): sign up.
4. **Google Cloud** (console.cloud.google.com): any project, for the OAuth client (step 5).
5. **Gemini API key** (aistudio.google.com): for embeddings.
6. **Groq API key** (console.groq.com): for answers.
7. *Optional:* **Langfuse** (cloud.langfuse.com).

## 2. Neon database

1. Create a project. Choose the region closest to where the API will run: Vercel Functions run in `iad1` (Washington, D.C.) by default, so pick **AWS US East (N. Virginia)**.
2. In the dashboard open **Connect**. You need two connection strings for the same database:
   - the **pooled** one (the host contains `-pooler`) goes in `DATABASE_URL`: the app queries through it;
   - the **direct** one (no `-pooler`) goes in `DATABASE_URL_UNPOOLED`: migrations and seeding use it, because they take a Postgres advisory lock that a transaction-mode pooler cannot hold.
3. Both should end in `?sslmode=require`.

The app already copes with Neon: connections are not prepared (`prepare_threshold=None`, needed behind the pooler), the pool holds no idle connections and checks one before use (Neon drops them when it scales to zero), and migrations run under an advisory lock so several cold instances cannot race. The first request after the database was idle waits for it to wake, usually a second or two.

## 3. Secrets

Generate three different random values (any 32+ character random string works; this uses Node, which you already have):

```bash
node -e "console.log(require('crypto').randomBytes(32).toString('base64'))"
```

Run it three times and keep them: `API_TOKEN_SECRET` (**the same value in both projects**), `AUTH_SECRET` (web only), `VISITOR_SALT` (API only). Never reuse a value across names, never commit them, and never paste them into chat or issues.

## 4. API project (Vercel project 2)

1. **Add New → Project**, import the GitHub repo, name it `lexio-api`, and set **Root Directory** to `backend`. Vercel detects FastAPI from `pyproject.toml` (`[tool.vercel] entrypoint = "index:app"`), uses the Python version in `.python-version`, installs from `uv.lock`, and applies `vercel.json` (maximum duration 300 s). `.vercelignore` keeps tests and evals out of the bundle.
2. Add these **Environment Variables** (Production):

   | Name | Value |
   |---|---|
   | `DATABASE_URL` | Neon **pooled** string |
   | `DATABASE_URL_UNPOOLED` | Neon **direct** string |
   | `EMBEDDING_PROVIDER` | `gemini` |
   | `GEMINI_API_KEY` | your key |
   | `GROQ_API_KEY` | your key |
   | `DEMO_MODE` | `true` (the free-tier preset: capped questions and uploads, see the README) |
   | `API_TOKEN_SECRET` | the shared secret from step 3 |
   | `VISITOR_SALT` | the salt from step 3 (the default is only for local use) |
   | `TRUST_FORWARDED_FOR` | `true` (the browser reaches the API directly, so Vercel's edge sets `X-Forwarded-For`) |
   | `CORS_ORIGINS` | a JSON list with the web URL: `["https://lexio-web.vercel.app"]` (add a custom domain here too if you add one) |
   | `BLOB_READ_WRITE_TOKEN` | added in step 6 |

   Do **not** set `ALLOW_DEV_USERS`; leaving it unset means the backend refuses the frontend's development login.
3. Deploy. Open `https://lexio-api.vercel.app/api/health`: `{"status":"ok"}` means the function started, ran the migrations and reached Neon. (Before step 7 the sample list will be empty.)

## 5. Google sign-in

1. Google Cloud → **APIs & Services → OAuth consent screen**: user type **External**, app name, your email. While the app is in **Testing**, only test users you list can sign in; click **Publish app** to open it to anyone with a Google account (the sign-in only asks for basic profile scopes, but read what Google's page says when you publish).
2. **Credentials → Create credentials → OAuth client ID → Web application**:
   - Authorised JavaScript origins: `https://lexio-web.vercel.app`
   - Authorised redirect URIs: `https://lexio-web.vercel.app/api/auth/callback/google`
   - Add `http://localhost:3000` and `http://localhost:3000/api/auth/callback/google` as well if you want local sign-in to keep working with the same client.
3. Copy the client ID and secret for step 6.

## 6. Web project (Vercel project 1) and Blob

1. **Add New → Project**, same repo, name `lexio-web`, **Root Directory** `frontend`. Framework: Next.js (automatic).
2. **Storage → Create → Blob**, access **Private**, and connect it to `lexio-web` for Production (and Preview if you use previews). Vercel adds `BLOB_READ_WRITE_TOKEN` to the web project.
3. Add these environment variables to `lexio-web`:

   | Name | Value |
   |---|---|
   | `NEXT_PUBLIC_API_URL` | `https://lexio-api.vercel.app`. This is baked in at **build** time: change it and you must redeploy. |
   | `AUTH_SECRET` | from step 3 |
   | `AUTH_GOOGLE_ID` / `AUTH_GOOGLE_SECRET` | from step 5 |
   | `API_TOKEN_SECRET` | the **same** value as the API's |

   Do not set `AUTH_URL`: on Vercel, Auth.js trusts the platform's host. A production build also has no dev login (the provider is only added under `next dev`).
4. Give the **API** project the same Blob token. Easiest: open the Blob store, go to its **Projects** tab and connect it to `lexio-api` as well, which adds the same `BLOB_READ_WRITE_TOKEN` there. If that is not offered, copy the value from the web project's environment variables into the API project by hand. The API reads and deletes PDFs with it, so it must be the token of the *same* store the web app uploads to.
5. Redeploy **both** projects (the API to pick up the token, the web app to bake in the API URL).

## 7. Seed the sample documents

The sample PDFs are loaded straight into Neon (they stay in Postgres, about 8 MB, and are streamed to the viewer). Run this once from `backend/` on your own machine, with the **direct** Neon string:

```powershell
$env:DATABASE_URL = "<Neon direct string>"
$env:EMBEDDING_PROVIDER = "gemini"
$env:GEMINI_API_KEY = "<your key>"
$env:UV_PYTHON_PREFERENCE = "only-system"
uv run python -m evals.seed
```

It reads vectors from `backend/evals/.cache`, which exists on the machine that ran the Gemini eval and is not in git. **Without that cache it embeds about 800 chunks, most of a day's Gemini free quota.** It prints how many requests it sent. Re-running skips documents that are already present. Close the PowerShell window afterwards so the key and database string are not left in your environment.

## 8. Langfuse (optional)

Create a project in Langfuse, then add to the **API** project: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_HOST` (`https://cloud.langfuse.com` for the EU region, `https://us.cloud.langfuse.com` for the US one). Each chat then produces one trace with a retrieval span and rewrite and answer generations. By default traces hold timings, counts and flags and a salted visitor hash. They do **not** hold the question, the passages or the answer, because those come from users' private documents. `LANGFUSE_CAPTURE_CONTENT=true` adds them; only turn it on for a deployment with no private uploads, or if you accept Langfuse holding that text.

## 9. Check it on the real thing

Each line is an assumption the tests could not prove. Tick them off in order.

- [ ] `https://lexio-api.vercel.app/api/health` returns `{"status":"ok"}`. Vercel → API project → **Logs**: no import errors (the `vercel-blob` SDK and the Python 3.14 runtime are the things most likely to complain).
- [ ] Open the web app signed out: the five samples are listed.
- [ ] Open the **Buyer Guidance** sample (6 MB, over the 4.5 MB limit): the viewer shows it. This proves a streamed response is exempt from the limit, as Vercel's documentation says. If it fails with a 413, tell me; the fallback is signed Blob URLs.
- [ ] Ask a question: text streams in token by token rather than arriving at the end.
- [ ] Sign in with Google. Upload a PDF **larger than 4.5 MB**. It appears in your library and opens in the viewer. In Vercel → Storage → your Blob store you see one object under `u/…/`.
- [ ] Upload the same PDF again: "already in your library", and still one object in the store.
- [ ] Delete the document: the object disappears from the store.
- [ ] Ask more than `VISITOR_QUESTION_LIMIT` questions: you get the 429 message. Then ask from a phone on mobile data: its count starts from zero, which shows `X-Forwarded-For` is telling visitors apart (if it did not, every visitor would share one counter).
- [ ] If you set up Langfuse: the questions you asked appear as traces.
- [ ] Try the same upload with the Wi-Fi turned off midway, then wait two hours and open the Blob store: the half-finished object is gone (the API sweeps unregistered uploads when an instance starts, so this needs some traffic).

## Limits you should know about

- **Groq is the ceiling**: about 60 answers a day across all visitors (`QUESTION_DAILY_LIMIT`). The CI answer eval and any local eval use the same Groq key and quota, so do not run them during demo hours.
- **Orphaned uploads** (the browser uploaded, then the user closed the tab before registering) sit in Blob until the sweep removes them, up to a couple of hours later and only when an API instance starts. A flood of them is capped by the per-user ticket limit but not eliminated.
- **A function is limited to 300 s.** Registering a very long PDF embeds every chunk inside one request; `MAX_UPLOAD_CHUNKS` (150 in demo mode) keeps that well inside the limit.
- **Changing a secret**: a new `API_TOKEN_SECRET` must be set in both projects and both redeployed (until then every signed-in request gets a 401). A new `AUTH_SECRET` signs everyone out. A new `VISITOR_SALT` makes everyone a new visitor, which resets the anonymous counters.
- **Previews**: preview deployments of the web app get different URLs that are not in the API's `CORS_ORIGINS` or Google's redirect URIs, so sign-in and API calls fail there unless you add them.
