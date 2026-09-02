from pathlib import Path

import pytest
import requests

from moongcheap_ai.data_foundation.mfds import MFDSCollectionError, collect


class FailingSession:
    def get(self, url: str, timeout: int) -> None:
        raise requests.ConnectionError("offline")


def test_mfds_network_failure_is_reportable(tmp_path: Path) -> None:
    with pytest.raises(MFDSCollectionError, match="request failed"):
        collect("I0030", "test-key", tmp_path, max_pages=1, session=FailingSession())
