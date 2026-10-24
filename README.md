# BrandLens

Pre-publication brand governance for the Inkloom AI problem statement. A creator submits a draft, BrandLens checks it
against the organisation's approved guidelines, glossary and claim ledger, explains every finding with the exact source
it comes from, suggests a fix that keeps the creator's intent, and routes the draft through manager and reviewer approval.

Built with FastAPI only: server-rendered pages (Jinja2), SQLModel with SQLite, Pillow for image checks.

## Run locally

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://localhost:8000. A demo organisation (Acme) is created on first start.

## Try it

1. Sign in as Asha, choose New draft, use sample 1, press Check draft.
2. Press Apply all fixes, then Submit for approval.
3. Sign in as Ravi and approve. Try sample 2 as Asha to see an expired claim, a wrong price and pressure language.
   The manager cannot approve a draft with open high-risk claim findings; Meera (reviewer) can, with a written reason.

## Optional AI layer

Set `ANTHROPIC_API_KEY` (and optionally `LLM_MODEL`) to switch on the AI judge for tone and messaging and the
intent-preserving AI rewrite. Every AI finding must quote a real guideline paragraph and real draft text, or the verifier
drops it. Without a key the product still runs on the rule engine and the claim ledger. `/health` reports whether AI is on.

## Architecture

```
app/engine/segment.py   split text into sentences and paragraphs
app/engine/rules.py     glossary, tone, messaging and accessibility rules
app/engine/claims.py    claim ledger: supported / contradicted / outdated / unverified
app/engine/llm.py       optional AI judge and AI rewrite (strict JSON contract)
app/engine/verify.py    drops any finding whose quoted evidence does not exist
app/engine/images.py    alt text and brand palette checks
app/engine/review.py    pipeline that ties the steps together
app/services.py         versions, apply fixes, re-check, insights
app/routes.py           pages and workflow
```

## Tests

```bash
PYTHONPATH=. pytest tests -q -s
```

## Deploy on Vercel

Vercel finds `app/main.py` and serves the app as a function. Vercel functions cannot keep files between requests, so
attach a database or your data will reset:

1. Import the GitHub repo in Vercel (framework preset: FastAPI or Other).
2. In the project's Storage tab, add a free Postgres database (Neon). Vercel adds `DATABASE_URL` or `POSTGRES_URL` for you.
3. Under Settings, Environment Variables, add `SECRET_KEY` (any long random text) and, optionally, `ANTHROPIC_API_KEY`.
4. Redeploy. Demo data is created on first start. Uploaded images are stored in the database (keep them under 4 MB).

Without a database the app falls back to SQLite in `/tmp`, which is lost whenever Vercel starts a new instance.

## Deploy (Render)

Push to GitHub, create a Render web service from the repo (it reads `render.yaml`), and add `ANTHROPIC_API_KEY`
if you want the AI layer. The demo data is re-created on start, so a free instance that restarts still works.
