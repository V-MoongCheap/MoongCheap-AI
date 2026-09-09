from pathlib import Path

from scripts.collect.consumer_reference_inventory import SOURCES, collect_inventory


def test_external_sources_are_reference_only():
    assert SOURCES["esci"]["role"] == "expression_reference_only"
    assert SOURCES["xpqa"]["role"] == "expression_reference_only"
    assert SOURCES["kuaisearch"]["role"] == "not_acquired"


def test_inventory_uses_project_local_paths():
    inventory = collect_inventory()
    assert inventory["aihub_policy"].startswith("AI-Hub path")
    assert all(Path(item["local_path"]).parts[0] == "data" for item in inventory["datasets"])
