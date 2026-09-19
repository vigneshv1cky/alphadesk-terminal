#!/usr/bin/env bash
# Deploy main to Cloud Run: build the image on Cloud Build, roll the service
# to it — and nothing else. Only --image changes, so the service keeps its
# environment, its Cloud SQL mount and its scaling exactly as provisioned.
#
# Run the tests first (python -m pytest -q; cd alphadesk/ui && pnpm test &&
# pnpm build). The committed bundle in alphadesk/app/static is what ships.
#
# The target is configured, not written here: set these in the environment
# or in scripts/deploy.env (git-ignored, read if present):
#   DEPLOY_ACCOUNT   the gcloud account to run as
#   DEPLOY_PROJECT   the Google Cloud project
#   DEPLOY_REGION    the Cloud Run region (default us-east4)
#   DEPLOY_SERVICE   the Cloud Run service (default alphadesk)
#   DEPLOY_URL       the service's public URL, to check the new build is live
#
# Usage: scripts/deploy.sh            (deploys HEAD of a clean, pushed main)
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
[[ -f "$here/deploy.env" ]] && source "$here/deploy.env"

ACCOUNT="${DEPLOY_ACCOUNT:?set DEPLOY_ACCOUNT (or scripts/deploy.env)}"
PROJECT="${DEPLOY_PROJECT:?set DEPLOY_PROJECT (or scripts/deploy.env)}"
REGION="${DEPLOY_REGION:-us-east4}"
SERVICE="${DEPLOY_SERVICE:-alphadesk}"
URL="${DEPLOY_URL:?set DEPLOY_URL (or scripts/deploy.env)}"

cd "$(git rev-parse --show-toplevel)"

branch="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$branch" != "main" ]]; then
  echo "refusing: on '$branch', deploy from main" >&2; exit 1
fi
if [[ -n "$(git status --porcelain)" ]]; then
  echo "refusing: uncommitted changes — the build uploads the working tree" >&2; exit 1
fi
git fetch -q origin main
if [[ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]]; then
  echo "refusing: main differs from origin/main — push or pull first" >&2; exit 1
fi

sha="$(git rev-parse HEAD)"
image="${REGION}-docker.pkg.dev/${PROJECT}/${SERVICE}/app:${sha}"
echo "building ${sha:0:8} as ${ACCOUNT} on ${PROJECT}"
gcloud builds submit --tag "$image" --project "$PROJECT" --account "$ACCOUNT" --quiet --suppress-logs
gcloud run deploy "$SERVICE" --image "$image" --region "$REGION" --project "$PROJECT" --account "$ACCOUNT" --quiet

# The live page must name this build's bundle.
want="$(grep -oE 'assets/index-[^"]+\.(css|js)' alphadesk/app/static/index.html | sort)"
got="$(curl -fsS "$URL/" | grep -oE 'assets/index-[^"]+\.(css|js)' | sort)"
if [[ "$want" == "$got" ]]; then
  echo "live: ${URL} serves ${sha:0:8}"
else
  echo "WARNING: the live page does not serve this build's bundle yet" >&2; exit 1
fi
