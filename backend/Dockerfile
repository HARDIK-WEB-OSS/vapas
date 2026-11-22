FROM ghcr.io/astral-sh/uv:0.13.9 AS uv

FROM python:3.11-slim
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --locked --no-dev --no-install-project
COPY backend/ ./
COPY rules/ ./rules/
RUN uv sync --locked --no-dev && useradd --create-home --uid 10001 vapas
USER vapas
EXPOSE 8000
CMD ["uvicorn", "--factory", "vapas.main:create_app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header", "--timeout-graceful-shutdown", "25"]
