FROM ghcr.io/astral-sh/uv:alpine
ADD . /app
WORKDIR /app
ENV UV_NO_DEV=1
ENV PYTHONUNBUFFERED=1
RUN uv sync
CMD ["uv", "run", "/app/main.py"]