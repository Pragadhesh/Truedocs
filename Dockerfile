FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

COPY pyproject.toml ./
RUN uv sync --no-dev --no-install-project

COPY . .
RUN uv sync --no-dev

CMD ["uv", "run", "python", "app.py"]
