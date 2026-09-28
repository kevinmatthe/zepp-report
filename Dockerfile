FROM node:24.21.0-bookworm-slim@sha256:0e0ff40c39bc087845bfb27465a0df4ea419520094bc35842ff83dd8cbe6f9b6 AS frontend
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY scripts/build-frontend.mjs ./scripts/build-frontend.mjs
COPY zepp_report/static ./zepp_report/static
RUN npm run build

FROM python:3.11.15-slim@sha256:baf89808ec37adeaab83cec287adb4a2afa4a11c1d51e961c7ec737877e61af6
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/app/data
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --no-deps -r requirements.txt && pip check \
    && groupadd --gid 1000 zepp \
    && useradd --uid 1000 --gid 1000 --no-create-home zepp \
    && mkdir -p /app/data && chown 1000:1000 /app/data
COPY --chown=1000:1000 zepp_report ./zepp_report
COPY --from=frontend --chown=1000:1000 /build/zepp_report/static/dist ./zepp_report/static/dist
COPY THIRD_PARTY_NOTICES.md ./
USER 1000:1000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"
CMD ["uvicorn", "zepp_report.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
