FROM ghcr.io/astral-sh/uv:alpine
ADD . /app
WORKDIR /app
ENV UV_NO_DEV=1
ENV PYTHONUNBUFFERED=1
RUN adduser -D -u 1000 app && chown -R app:app /app
USER app
RUN uv sync --no-cache --frozen
CMD ["uv", "run", "/app/main.py"]
