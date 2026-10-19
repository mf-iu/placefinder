# syntax=docker/dockerfile:1
# PlaceFinder image: GeoNames data, virtual environment, unprivileged runtime.
# Build: docker build --tag placefinder:0.7.0 .
# Run:   docker run --rm --publish 8000:8000 placefinder:0.7.0

# GeoNames dump that is baked into the image, e.g. cities5000 or DE
ARG GEONAMES_FILE=cities15000

# ---- Stage 1: download the GeoNames data (CC BY 4.0) ----
FROM python:3.14-slim AS data
ARG GEONAMES_FILE
WORKDIR /data
# the slim image has no curl or unzip, Python does both
RUN python -c "import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], 'data.zip')" \
      "https://download.geonames.org/export/dump/${GEONAMES_FILE}.zip" \
 && python -m zipfile --extract data.zip . \
 && rm data.zip

# ---- Stage 2: build the virtual environment ----
FROM python:3.14-slim AS build
# take the uv binary from its official image (pinned version)
COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /bin/uv
# precompile bytecode; use the Python of the base image only
ENV UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=0
WORKDIR /app
# dependencies first: cached until uv.lock changes
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
# then the application itself, installed as a package
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

# ---- Stage 3: runtime image without build tools ----
FROM python:3.14-slim
ARG GEONAMES_FILE
# unprivileged user instead of root;
# pip is not needed at runtime and its bundled packages would
# only add findings to the Trivy scan
RUN useradd --system --uid 10001 app \
 && python -m pip uninstall --yes --root-user-action ignore pip
# copy only the finished virtual environment and the data
COPY --from=build /app/.venv /app/.venv
COPY --from=data /data /data
ENV DATA_FILE=/data/${GEONAMES_FILE}.txt
USER app
# document the port; publish it with docker run --publish
EXPOSE 8000
# exec form: uvicorn runs as PID 1 and receives signals
CMD ["/app/.venv/bin/uvicorn", "placefinder.main:app", "--host", "0.0.0.0", "--port", "8000"]
