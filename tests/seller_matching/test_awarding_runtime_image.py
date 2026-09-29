"""The runtime verifier must detect directory COPY contamination too."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("runtime_verifier", ROOT / "scripts/awarding/verify_runtime_image.py")
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


@pytest.fixture
def runtime(tmp_path):
    for name in verifier.REQUIRED:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    return tmp_path


def test_runtime_files_are_present_without_mock(runtime):
    assert verifier.verify(runtime)["status"] == "PASS"


@pytest.mark.parametrize("filename", ["mock_backend.py", "container_smoke.py"])
@pytest.mark.parametrize("directory", ["scripts/awarding", "copied-from-test"])
def test_mock_files_are_rejected_after_directory_copy(runtime, filename, directory):
    path = runtime / directory / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    with pytest.raises(RuntimeError, match="forbidden"):
        verifier.verify(runtime)


@pytest.mark.parametrize("filename", verifier.REQUIRED)
def test_missing_runtime_file_is_rejected(runtime, filename):
    (runtime / filename).unlink()
    with pytest.raises(RuntimeError, match="missing"):
        verifier.verify(runtime)
