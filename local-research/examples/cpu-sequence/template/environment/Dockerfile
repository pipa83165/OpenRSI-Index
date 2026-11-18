# Docker Official Image tag. The first build may need a registry pull.
FROM python:3.12-slim-bookworm
RUN groupadd -g 1000 worker && useradd -u 1000 -g 1000 -m worker \
    && mkdir -p /workspace && chown 1000:1000 /workspace
COPY --chown=1000:1000 sequence.py /workspace/sequence.py
ENV HOME=/home/worker
WORKDIR /workspace
USER 1000:1000
