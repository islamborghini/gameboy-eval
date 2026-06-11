# The SameBoy oracle as its own Linux container: builds SameBoy's libretro core (.so) from
# source and serves it over HTTP. The candidate/agent reaches it only over HTTP and never
# sees the source or binary.
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates build-essential clang bsdextrautils \
        bison flex pkg-config libpng-dev \
        python3 python3-numpy python3-pil \
    && rm -rf /var/lib/apt/lists/*

# rgbds (the Game Boy assembler) isn't packaged in Debian stable — build it from source.
RUN git clone --depth 1 --branch v0.7.0 https://github.com/gbdev/rgbds /rgbds \
    && make -C /rgbds -j"$(nproc)" && make -C /rgbds install && rm -rf /rgbds

# Build SameBoy's libretro core + boot ROMs from source.
RUN git clone --depth 1 https://github.com/LIJI32/SameBoy /sameboy \
    && make -C /sameboy libretro bootroms

COPY oracle/sameboy.py oracle/server.py /app/

ENV SAMEBOY_LIB=/sameboy/build/bin/sameboy_libretro.so \
    SAMEBOY_BOOTROMS=/sameboy/build/bin/BootROMs \
    PYTHONUNBUFFERED=1

EXPOSE 8765
CMD ["python3", "/app/server.py", "--host", "0.0.0.0", "--port", "8765"]
