"""Offline Kustomize checks for the Part A labeling CronJob."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module", params=["base", "overlays/dev"])
def resources(request, tmp_path_factory):
    kubectl = shutil.which("kubectl")
    if kubectl is None:
        pytest.skip("kubectl is required for offline Kustomize checks")
    environment = dict(os.environ)
    environment["KUBECONFIG"] = str(
        tmp_path_factory.mktemp("no-cluster-a") / "nonexistent-kubeconfig"
    )
    result = subprocess.run(
        [kubectl, "kustomize", str(ROOT / "k8s" / request.param)],
        check=True, capture_output=True, text=True, timeout=30, env=environment,
    )
    documents = [
        document for document in yaml.safe_load_all(result.stdout)
        if document["metadata"]["name"].startswith("a-labeling")
        or document["metadata"]["name"].startswith("a-labeling-config")
    ]
    assert len(documents) == 3
    expected_namespace = "moongcheap-ai-dev" if request.param == "overlays/dev" else None
    for document in documents:
        assert document["metadata"].get("namespace") == expected_namespace
    return {document["kind"]: document for document in documents}


def test_is_suspended_and_writes_through_database(resources):
    cronjob = resources["CronJob"]
    assert cronjob["spec"]["suspend"] is True
    assert cronjob["spec"]["concurrencyPolicy"] == "Forbid"
    assert cronjob["spec"]["jobTemplate"]["spec"]["backoffLimit"] == 0
    pod = cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    container = pod["containers"][0]
    assert container["command"] == [
        "a-labeling-batch", "--write-db", "--output", "/tmp/a-labeling-output.csv",
    ]
    assert container["image"] == "moongcheap/ai-labeling:replace-with-git-sha"
    assert container["resources"] == {
        "requests": {"cpu": "1", "memory": "2Gi"},
        "limits": {"cpu": "2", "memory": "3Gi"},
    }


def test_secret_and_http_contract(resources):
    cronjob = resources["CronJob"]
    pod = cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    container = pod["containers"][0]
    assert container["env"] == [{
        "name": "A_DATABASE_URL",
        "valueFrom": {"secretKeyRef": {"name": "ai-labeling-database", "key": "url"}},
    }]
    assert container["envFrom"][0]["configMapRef"]["name"].startswith("a-labeling-config-")
    assert pod["automountServiceAccountToken"] is False
    assert "ports" not in container
    assert "livenessProbe" not in container
    assert "readinessProbe" not in container
