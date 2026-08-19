# UNVERIFIED. Docker is not installed on the development machine, so this file
# has been reviewed by inspection and never built or run. It is shipped as a
# starting point, not as a tested artifact, and saying so is more useful than
# implying otherwise. See ACCEPTANCE.md.

# ---------------------------------------------------------------------------
# Build stage: install dependencies into a virtualenv that the runtime copies.
# Two stages so the final image carries no compiler and no build cache.
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Dependency metadata first, so the layer caches unless the dependencies change.
COPY pyproject.toml README.md ./
COPY app ./app
COPY worker ./worker

RUN pip install --upgrade pip && pip install .

# ---------------------------------------------------------------------------
# Runtime stage
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# A non-root user. This process handles files chosen by whoever calls the API,
# so the difference between "a bug in the upload path" and "root in the
# container" is worth one line of Dockerfile.
RUN useradd --create-home --uid 10001 upa

COPY --from=build /opt/venv /opt/venv

WORKDIR /srv/app
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY worker ./worker
COPY scripts ./scripts

# Samples live on a volume, not in the image layer.
RUN mkdir -p /var/lib/upa/samples && chown -R upa:upa /var/lib/upa /srv/app
VOLUME ["/var/lib/upa/samples"]

USER upa

ENV UPA_STORAGE_ROOT=/var/lib/upa/samples

EXPOSE 8000

# Readiness rather than liveness: this reports whether the container can
# actually serve, which is what an orchestrator should route on.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/readyz').status == 200 else 1)"

# Migrations are not run here. Starting N replicas would start N migrations,
# and the schema is not each replica's business. Run `alembic upgrade head` as
# a deployment step. See README.md.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
