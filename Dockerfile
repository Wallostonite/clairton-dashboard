# Container image for the Clairton dashboard. Works on any container host
# (Render, Fly.io, Cloud Run, a VPS, etc.).
FROM python:3.13-slim

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the app and data.
COPY . .

# Build the processed dataset at image-build time so the container starts fast
# and never needs write access at runtime. Harmless if data is already built.
RUN python etl.py --no-strict || true

EXPOSE 8501

# Most platforms inject the port via $PORT; default to 8501 locally.
ENV PORT=8501
HEALTHCHECK CMD python -c "import os,urllib.request; urllib.request.urlopen(f\"http://localhost:{os.environ['PORT']}/healthz\")" || exit 1

CMD streamlit run app.py \
    --server.port=${PORT} \
    --server.address=0.0.0.0 \
    --server.headless=true
