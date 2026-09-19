# Deploying AlphaDesk

AlphaDesk runs as **one process on one port**: the FastAPI app serves the
JSON API, the live-data streams, the agent tools and the built frontend, and
runs the background loops (news, EDGAR, the daily forecast capture, the
search-by-meaning worker and the owner prewarm) in the same process. The
frontend bundle is committed under `alphadesk/app/static`, so an image needs
no Node build step.

## Production: Google Cloud Run

The reference service is **`alphadesk` on Cloud Run** (region `us-east4`),
with **Cloud SQL for Postgres** as its store
(mounted through the Cloud SQL connector; `ALPHADESK_DATABASE_URL` carries
`?host=/cloudsql/…`).

| Setting | Value | Why |
|---|---|---|
| CPU / memory | 2 vCPU / 4 GiB | the embedding model and the web server share the instance |
| Instances | min 1, max 1 | one writer for the background loops and the live sockets |
| CPU allocation | always on, with startup boost | the loops run between requests |
| Image | `Dockerfile`: Python 3.12 slim, PyTorch CPU build, the model baked in | nothing is downloaded at start |

**Always on is required as built.** The news poll, the held news sockets,
the EDGAR sweep, the forecast capture and the embedding worker run on their
own schedules; scaling to zero would stall them and make the first visit
wait for a cold start. The cost at this size is roughly $110–120 a month
plus Cloud SQL.

### Deploying a change

Continuous integration tests every pull request; deploying is a
maintainer's step. Run the checks locally first — `python -m pytest -q`,
`pnpm test`, `pnpm build` —
then, from a clean `main` that matches `origin/main`, with the target set in
`scripts/deploy.env` (git-ignored: `DEPLOY_ACCOUNT`, `DEPLOY_PROJECT`,
`DEPLOY_URL`, optionally `DEPLOY_REGION` and `DEPLOY_SERVICE`):

```bash
scripts/deploy.sh
```

The script builds the image on Cloud Build, rolls the service with the new
**image only** (environment variables, the Cloud SQL mount and scaling are
untouched) and checks that the live page serves the new build. It runs as
the project's deploy account; ask before running any `gcloud` command.

### Changing configuration

Change one variable at a time, and **always** with `--update-env-vars`:

```bash
gcloud run services update alphadesk --region us-east4 --update-env-vars ALPHADESK_SEMANTIC_SEARCH=off
```

Never use `--set-env-vars`: it replaces every variable with the ones listed,
and wiped the sign-in configuration once.

Resizing is likewise its own command (`--cpu`, `--memory`); `deploy.sh`
never changes it.

### Switches for incidents

| Symptom | First move |
|---|---|
| Requests refused ("Rate exceeded") or pages slow after a deploy | turn off new background work: `ALPHADESK_SEMANTIC_SEARCH=off`, `ALPHADESK_PREWARM=off` |
| Anything worse | route traffic back to the previous revision in the Cloud Run console |

Ship risky background work switched off, then switch it on and watch the
request log for refused or slow requests. A 2-vCPU container reports more
cores than it has, so a many-core laptop does not predict production:
sizing threads from the reported core count once starved the web server.

### Logs

Cloud Logging, service `alphadesk`. Useful lines: `Terminal on` (start),
`semantic search: … loaded` (the model and its thread count),
`prewarm: refreshed N panels`, `pruned vendor data`, `Ingested N articles`.

## Local development

```bash
pip install -r requirements.txt
cp alphadesk/deploy/env.example .env      # ALPHADESK_VAULT_KEY, SEC_USER_AGENT
python -m alphadesk.main dashboard        # http://127.0.0.1:8000
```

Locally the store is SQLite in `ALPHADESK_DATA` (default `~/.alphadesk`). On
start, the store drops tables retired from the schema — deliberate, so back
up the directory if its history matters.
