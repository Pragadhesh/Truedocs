FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

COPY . .
RUN uv pip install --system --no-cache .

CMD ["python", "app.py"]
