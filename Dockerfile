FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y gcc git && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY README.md .
COPY src/ src/
COPY .env.example .env

RUN pip install --no-cache-dir .[dev,frontend]

EXPOSE 8000
ENV PYTHONPATH=/app/src

CMD ["python", "-m", "nordtrace.cli", "benchmark"]
