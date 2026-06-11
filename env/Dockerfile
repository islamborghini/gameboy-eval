# Offline build sandbox for candidate emulators.
#
# Two run modes:
#   - the harness builds candidates here with `--network none` (a from-scratch emulator has
#     no dependencies, so the build is fully offline);
#   - on the internal `gb-eval-net` (see scripts/run-sandbox.sh) it can reach ONLY the oracle
#     container via the bundled `oracle` CLI ($ORACLE_URL) — no internet.
#
# Build from the repo root: docker build -t gameboy-eval-gen -f env/Dockerfile .
FROM rust:1-slim

RUN rustup target add wasm32-unknown-unknown \
    && apt-get update \
    && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*

COPY oracle/oracle /usr/local/bin/oracle
RUN chmod +x /usr/local/bin/oracle

ENV ORACLE_URL=http://gb-oracle:8765
WORKDIR /task
