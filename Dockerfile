FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y gcc git && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock README.md LICENSE NOTICE.md ./
COPY src/ src/
COPY .env.example .env

RUN pip install --no-cache-dir uv==0.12.5 && uv sync --frozen --no-dev --no-editable

EXPOSE 8000
ENV PYTHONPATH=/app/src
ENV PATH="/app/.venv/bin:$PATH"

CMD ["python", "-m", "nordtrace.cli", "benchmark"]
