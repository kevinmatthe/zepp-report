FROM python:3.11.15-slim@sha256:baf89808ec37adeaab83cec287adb4a2afa4a11c1d51e961c7ec737877e61af6
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/app/data
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --no-deps -r requirements.txt && pip check \
    && groupadd --gid 1000 zepp \
    && useradd --uid 1000 --gid 1000 --no-create-home zepp \
    && mkdir -p /app/data && chown 1000:1000 /app/data
COPY --chown=1000:1000 zepp_report ./zepp_report
COPY THIRD_PARTY_NOTICES.md ./
USER 1000:1000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"
CMD ["uvicorn", "zepp_report.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
