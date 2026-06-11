# Offline build sandbox for candidate emulators.
# The harness runs `cargo build` here with `--network none`: a from-scratch emulator has no
# dependencies, so the build is fully offline (no crates.io, no tutorials, no SameBoy source).
FROM rust:1-slim

RUN rustup target add wasm32-unknown-unknown

WORKDIR /task
