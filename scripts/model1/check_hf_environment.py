"""Check optional Model 1 Hugging Face runtime without downloading weights."""

from __future__ import annotations

import importlib


def main() -> int:
    required = ("torch", "transformers", "accelerate", "huggingface_hub")
    missing = []
    for name in required:
        try:
            module = importlib.import_module(name)
        except ImportError:
            missing.append(name)
            continue
        print(f"{name}={getattr(module, '__version__', 'installed')}")
    if missing:
        print("missing=" + ",".join(missing))
        print("Install with: .\\.venv\\Scripts\\python.exe -m pip install -r requirements-model1-hf.txt")
        return 1
    print("status=READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
