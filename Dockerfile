# AlphaDesk — the whole terminal in one container.
#
# The frontend is NOT built here: the shipped bundle is committed under
# alphadesk/app/static (deliberately — one process serves API and SPA), so
# the image is a Python runtime plus the package. Built for Cloud Run and
# friends: binds the injected PORT, everything else configured by env.
#
# On a platform with an ephemeral filesystem, set ALPHADESK_DATABASE_URL to
# a Postgres connection string — without it the store writes SQLite into the
# container's disk and history dies with each revision.

FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
# torch's CPU-only build first: the default wheel carries ~2 GB of CUDA
# libraries a Cloud Run CPU never uses.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r requirements.txt

# The embedding model for search by meaning (alphadesk/semantic.py), baked
# into the image at build time (~1.2 GB) so a starting instance fetches
# nothing; at run time the Hugging Face hub is not contacted at all.
ENV HF_HOME=/app/hf
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('Qwen/Qwen3-Embedding-0.6B', device='cpu')"
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

COPY alphadesk/ alphadesk/

ENV PYTHONUNBUFFERED=1 \
    DASHBOARD_HOST=0.0.0.0

# Cloud Run injects PORT; anywhere else falls back to 8000.
CMD ["sh", "-c", "DASHBOARD_PORT=${PORT:-8000} exec python -m alphadesk.main dashboard"]
