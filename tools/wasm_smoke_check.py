#!/usr/bin/env python3
"""Validate the wasm toolchain + the wasmtime memory-read path the grader depends on.

Run with the project's 3.12 venv:
    .venv/bin/python tools/wasm_smoke_check.py
"""
import sys
from pathlib import Path

from wasmtime import Engine, Store, Module, Instance

DEFAULT = (
    Path(__file__).resolve().parents[1]
    / "reference/wasm-smoke/target/wasm32-unknown-unknown/release/wasm_smoke.wasm"
)


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    if not path.exists():
        sys.exit(
            f"wasm not found: {path}\n"
            "Build it first:\n"
            "  (cd reference/wasm-smoke && "
            "cargo build --release --lib --target wasm32-unknown-unknown)"
        )

    engine = Engine()
    store = Store(engine)
    module = Module.from_file(engine, str(path))
    inst = Instance(store, module, [])
    ex = inst.exports(store)

    assert ex["add"](store, 2, 40) == 42, "add(2,40) != 42"
    assert ex["answer"](store) == 42, "answer() != 42"

    mem = ex["memory"]
    ex["smoke_fill"](store, 0xAB)
    ptr = ex["smoke_buffer"](store)
    data = mem.read(store, ptr, ptr + 16)
    assert all(b == 0xAB for b in data), f"memory read mismatch: {bytes(data).hex()}"

    print(f"WASM smoke OK  ({path.name})")
    print(f"  add(2,40)             = 42")
    print(f"  answer()              = 42")
    print(f"  memory[{ptr}:{ptr + 16}] = {bytes(data).hex()}  (all 0xAB)")


if __name__ == "__main__":
    main()
