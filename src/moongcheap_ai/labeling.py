from __future__ import annotations

import re
from typing import Any


def label_demand(demand_id: int | str, catalog_id: int | str, extra_requirement: str,
                 taxonomy: dict[str, Any]) -> dict[str, Any]:
    """Minimal deterministic P3 skeleton; it does not write to the Backend DB."""
    facets: dict[str, int] = {}
    text = str(extra_requirement or "")
    for facet in taxonomy.get("facets", []):
        code = 0
        for value in facet.get("values", []):
            if value.get("code", 0) and any(re.search(re.escape(alias), text, re.IGNORECASE) for alias in value.get("aliases", []) + [str(value.get("value", ""))]):
                code = int(value["code"]); break
        facets[str(facet["name"])] = code
    return {"demand_id": demand_id, "catalog_id": catalog_id, "facets": facets,
            "label": "-".join(str(facets[name]) for name in facets)}
