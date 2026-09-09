from __future__ import annotations

import ast
import importlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[2]
PACKAGE_NAME = "moongcheap_ai.demand_clustering"
PACKAGE_DIR = ROOT / "src" / "moongcheap_ai" / "demand_clustering"
OFFLINE_PREFIXES = (
    f"{PACKAGE_NAME}.evaluation",
    f"{PACKAGE_NAME}.substitute_annotation",
    "scripts",
)


def test_runtime_source_does_not_import_offline_tools() -> None:
    violations = []
    for path in sorted(PACKAGE_DIR.glob("*.py")):
        # This explicit compatibility adapter belongs to the offline review app.
        if path.name == "substitute_annotation.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                module = "." * node.level + (node.module or "")
                if node.level:
                    module = importlib.util.resolve_name(module, PACKAGE_NAME)
                imports = [module, *(f"{module}.{alias.name}" for alias in node.names)]
            else:
                continue
            for name in imports:
                if any(
                    name == prefix or name.startswith(prefix + ".")
                    for prefix in OFFLINE_PREFIXES
                ):
                    violations.append(f"{path.name}:{node.lineno}: {name}")
    assert not violations, "\n".join(violations)


@pytest.mark.parametrize("mode", ["runtime", "evaluation"])
def test_package_imports_without_optional_model_stack(mode: str) -> None:
    # A fresh interpreter prevents previously imported test modules from hiding
    # a forbidden dependency. No DB, HTTP call or model download is required.
    code = textwrap.dedent("""
        import importlib
        import importlib.abc
        import pkgutil
        import sys

        mode = sys.argv[1]
        package_name = "moongcheap_ai.demand_clustering"
        blocked = ["torch", "transformers", "sentence_transformers", "sklearn"]
        if mode == "runtime":
            blocked += [
                package_name + ".evaluation",
                package_name + ".substitute_annotation",
                "scripts",
            ]

        class BlockUnexpectedImports(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if any(
                    fullname == prefix or fullname.startswith(prefix + ".")
                    for prefix in blocked
                ):
                    raise AssertionError("unexpected import: " + fullname)
                return None

        sys.meta_path.insert(0, BlockUnexpectedImports())
        package = importlib.import_module(package_name)
        for name in package.__all__:
            getattr(package, name)

        if mode == "runtime":
            for module in pkgutil.iter_modules(package.__path__):
                if module.name not in {"evaluation", "substitute_annotation"}:
                    importlib.import_module(package_name + "." + module.name)
            from moongcheap_ai.demand_clustering.runtime_job import main
            main(["--help"])
        else:
            evaluation = importlib.import_module(package_name + ".evaluation")
            for module in pkgutil.iter_modules(evaluation.__path__):
                importlib.import_module(evaluation.__name__ + "." + module.name)
    """)
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    result = subprocess.run(
        [sys.executable, "-c", code, mode],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    if mode == "runtime":
        assert "--env-file" in result.stdout
        assert "--planned-at" not in result.stdout
        assert "--batch-id" not in result.stdout


def test_review_app_compatibility_exports_are_identical() -> None:
    legacy = importlib.import_module(f"{PACKAGE_NAME}.substitute_annotation")
    current = importlib.import_module(
        f"{PACKAGE_NAME}.evaluation.substitute_annotation"
    )
    assert set(legacy.__all__) == {
        "GOLD_LABELS",
        "REASON_CODES",
        "AnnotationValidationError",
        "SubstituteAnnotationStore",
        "dataset_fingerprint",
        "load_pair_frame",
    }
    for name in legacy.__all__:
        assert getattr(legacy, name) is getattr(current, name)
