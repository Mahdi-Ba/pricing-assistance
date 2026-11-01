# syntax=docker/dockerfile:1.7
# Backend image: API, scheduler and non-browser workers (design D14).
# Runs as a non-root, arbitrary UID (OpenShift restricted SCC) with a read-only root filesystem;
# only /tmp must be writable (mount an emptyDir / tmpfs there).
ARG PYTHON_IMAGE=registry.access.redhat.com/ubi9/python-312:latest

FROM ${PYTHON_IMAGE} AS build
USER 0
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/opt/venv
RUN pip install --no-cache-dir "uv==0.11.*"
WORKDIR /build
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM ${PYTHON_IMAGE} AS runtime
USER 0
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY alembic.ini ./
COPY alembic ./alembic
# group 0 owns the app so an arbitrary UID (member of group 0) can read it; nothing is writable
RUN chgrp -R 0 /app /opt/venv && chmod -R g=u,o-w /app /opt/venv
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp \
    TMPDIR=/tmp \
    PA_LOG_JSON=true
# the UBI base entrypoint re-sources its own PATH (system Python/Node first); run commands directly
ENTRYPOINT []
USER 1001
EXPOSE 8000
# role is chosen by the command (see the Helm chart): api | scheduler | worker | migrate
CMD ["uvicorn", "--factory", "pricing_assistant.app:create_app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
