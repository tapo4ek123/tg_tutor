FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock \
    && useradd --uid 10001 --create-home tutor
COPY pyproject.toml ./
COPY tutor ./tutor
COPY scripts/__init__.py scripts/evaluate.py ./scripts/
COPY tests/__init__.py tests/fakes.py ./tests/
COPY evals/cases.json ./evals/
COPY evals/baselines ./evals/baselines/
RUN pip install --no-deps . && mkdir /app/data && chown tutor:tutor /app/data
USER tutor
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "-m", "tutor.health"]
CMD ["python", "-m", "tutor.main"]
