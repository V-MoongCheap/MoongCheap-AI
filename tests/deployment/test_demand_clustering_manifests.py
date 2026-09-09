"""Offline render and application-contract checks; never contacts Kubernetes."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path, PurePosixPath

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
        tmp_path_factory.mktemp("no-cluster") / "nonexistent-kubeconfig"
    )
    result = subprocess.run(
        [kubectl, "kustomize", str(ROOT / "k8s" / request.param)],
        check=True, capture_output=True, text=True, timeout=30, env=environment,
    )
    documents = list(yaml.safe_load_all(result.stdout))
    assert len(documents) == 3
    assert {document["kind"] for document in documents} == {
        "CronJob", "ConfigMap", "ServiceAccount",
    }
    expected_namespace = "moongcheap-ai-dev" if request.param == "overlays/dev" else None
    for document in documents:
        assert document["metadata"].get("namespace") == expected_namespace
    return {document["kind"]: document for document in documents}


def pod_spec(resources):
    return resources["CronJob"]["spec"]["jobTemplate"]["spec"]["template"]["spec"]


def test_schedule_starts_suspended_and_disables_immediate_retry(resources):
    cronjob = resources["CronJob"]
    spec = cronjob["spec"]
    assert cronjob["apiVersion"] == "batch/v1"
    assert spec["suspend"] is True
    assert spec["schedule"] == "15 * * * *"
    assert spec["timeZone"] == "Asia/Seoul"
    assert spec["concurrencyPolicy"] == "Forbid"
    assert spec["startingDeadlineSeconds"] == 300
    assert spec["jobTemplate"]["spec"]["backoffLimit"] == 0
    assert spec["jobTemplate"]["spec"]["activeDeadlineSeconds"] == 1800
    assert pod_spec(resources)["restartPolicy"] == "Never"


def test_ai_node_selector_and_matching_toleration(resources):
    pod = pod_spec(resources)
    assert pod["nodeSelector"] == {
        "workload": "ai", "kubernetes.io/os": "linux", "kubernetes.io/arch": "amd64",
    }
    assert pod["tolerations"] == [{
        "key": "workload", "operator": "Equal", "value": "ai", "effect": "NoSchedule",
    }]
    assert "nodeName" not in pod
    assert "hostNetwork" not in pod


def test_only_required_secrets_are_injected_by_reference(resources):
    container = pod_spec(resources)["containers"][0]
    assert container["env"] == [
        {
            "name": "SHARED_DATABASE_URL",
            "valueFrom": {"secretKeyRef": {"name": "ai-batch-reader-database", "key": "url"}},
        },
        {
            "name": "BACKEND_INTERNAL_KEY",
            "valueFrom": {"secretKeyRef": {"name": "ai-backend-internal-key", "key": "internal-key"}},
        },
    ]
    config = resources["ConfigMap"]["data"]
    for forbidden in (
        "SHARED_DATABASE_URL", "BACKEND_INTERNAL_KEY", "BACKEND_SERVICE_TOKEN",
        "BATCH_STATE_DIR", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
    ):
        assert forbidden not in config


def test_generated_config_reference_and_runtime_settings(resources):
    configmap = resources["ConfigMap"]
    name = configmap["metadata"]["name"]
    assert name.startswith("demand-clustering-config-")
    assert pod_spec(resources)["containers"][0]["envFrom"] == [
        {"configMapRef": {"name": name}},
    ]
    config = configmap["data"]
    assert all(isinstance(value, str) for value in config.values())
    assert config["BACKEND_BASE_URL"] == "https://backend.invalid"
    assert config["CLUSTER_MIN_PARTICIPANTS"] == "5"
    assert config["E5_BATCH_SIZE"] == "32"
    assert config["HF_HUB_OFFLINE"] == config["TRANSFORMERS_OFFLINE"] == "1"
    assert config["OMP_NUM_THREADS"] == config["MKL_NUM_THREADS"] == "1"
    assert config["HF_HOME"] == "/tmp/huggingface"
    profiles = PurePosixPath(config["MFDS_CATALOG_PROFILES_PATH"])
    taxonomy = PurePosixPath(config["DEMAND_TAXONOMY_PATH"])
    assert profiles.parent == taxonomy.parent
    assert profiles.parent.parts[:3] == ("/", "artifacts", "releases")
    assert profiles.name == "catalog_profiles.csv"
    assert taxonomy.name == "taxonomy.json"


def test_read_only_artifact_mounts_and_bounded_tmp(resources):
    pod = pod_spec(resources)
    container = pod["containers"][0]
    mounts = {mount["name"]: mount for mount in container["volumeMounts"]}
    volumes = {volume["name"]: volume for volume in pod["volumes"]}
    assert set(mounts) == set(volumes) == {"artifacts", "e5-model", "tmp"}
    for volume_name, mount_path, claim_name in (
        ("artifacts", "/artifacts", "demand-clustering-artifacts"),
        ("e5-model", "/models/multilingual-e5-small", "demand-clustering-e5-model"),
    ):
        assert mounts[volume_name]["mountPath"] == mount_path
        assert mounts[volume_name]["readOnly"] is True
        assert volumes[volume_name]["persistentVolumeClaim"] == {
            "claimName": claim_name, "readOnly": True,
        }
    assert mounts["tmp"]["mountPath"] == "/tmp"
    assert volumes["tmp"]["emptyDir"] == {"sizeLimit": "256Mi"}
    config = resources["ConfigMap"]["data"]
    assert PurePosixPath(config["E5_MODEL_PATH"]).is_relative_to(
        mounts["e5-model"]["mountPath"]
    )


def test_non_root_without_kubernetes_api_token(resources):
    pod = pod_spec(resources)
    assert pod["automountServiceAccountToken"] is False
    assert pod["serviceAccountName"] == resources["ServiceAccount"]["metadata"]["name"]
    assert resources["ServiceAccount"]["automountServiceAccountToken"] is False
    assert pod["securityContext"] == {
        "runAsNonRoot": True, "runAsUser": 65534, "runAsGroup": 65534,
        "seccompProfile": {"type": "RuntimeDefault"},
    }
    assert pod["containers"][0]["securityContext"] == {
        "allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
        "capabilities": {"drop": ["ALL"]},
    }


def test_measured_resource_baseline_and_one_shot_command(resources):
    containers = pod_spec(resources)["containers"]
    assert len(containers) == 1
    container = containers[0]
    assert container["command"] == ["demand-clustering-batch"]
    assert not container.get("args")
    assert container["image"] == "demand-clustering-job:replace-with-git-sha"
    assert container["resources"] == {
        "requests": {"cpu": "1", "memory": "3Gi"},
        "limits": {"cpu": "2", "memory": "4Gi"},
    }
    for server_field in ("ports", "livenessProbe", "readinessProbe", "startupProbe"):
        assert server_field not in container
