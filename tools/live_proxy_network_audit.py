"""Read-only live proxy egress audit for selected CashPilot workers."""

from __future__ import annotations

import asyncio
import json

from app import database
from app.main import _proxy_to_worker, _safe_json

WORKER_IDS = {118903, 118904}
ATTEMPTS = 3


async def main() -> None:
    reports = []
    for worker in await database.list_workers():
        worker_id = int(worker.get("id") or 0)
        if worker_id not in WORKER_IDS:
            continue
        containers = _safe_json(worker.get("containers") or "[]", [])
        candidates = sorted(
            {
                str(item.get("instance_slug") or item.get("name") or "").strip()
                for item in containers
                if isinstance(item, dict)
                and str(item.get("instance_mode") or item.get("mode") or "").strip().lower() == "proxy"
                and str(item.get("instance_slug") or item.get("name") or "").strip()
            }
        )
        # One representative per runtime family keeps the read-only audit fast
        # and proves each topology without hammering every provider node.
        families = {}
        for instance_id in candidates:
            family = instance_id.split("-proxy-", 1)[0]
            if family.startswith("earnapp"):
                family = "earnapp"
            families.setdefault(family, instance_id)
        proxy_instances = sorted(families.values())
        samples = {instance_id: [] for instance_id in proxy_instances}
        for _attempt in range(ATTEMPTS):
            result = await _proxy_to_worker(
                worker_id,
                "POST",
                "/api/providers/egress-probe",
                json={"instances": proxy_instances},
                timeout=max(60, len(proxy_instances) * 4),
            )
            for row in result.get("results") or []:
                instance_id = str(row.get("instance_id") or "")
                if instance_id in samples:
                    samples[instance_id].append(row)
        results = []
        for instance_id, rows in samples.items():
            successes = [row for row in rows if row.get("probe_ok") is True]
            latest = successes[-1] if successes else (rows[-1] if rows else {})
            results.append(
                {
                    **latest,
                    "instance_id": instance_id,
                    "attempts": len(rows),
                    "successes": len(successes),
                    "confirmed_failed": bool(rows) and not successes,
                }
            )
        bad_ids = [str(row.get("instance_id") or "") for row in results if row.get("confirmed_failed") is True]
        details = []
        for instance_id in bad_ids:
            try:
                details.append(
                    {
                        "instance_id": instance_id,
                        "logs": await _proxy_to_worker(
                            worker_id,
                            "GET",
                            f"/api/containers/{instance_id}/logs",
                            params={"lines": 120},
                            timeout=20,
                        ),
                    }
                )
            except Exception as exc:
                details.append({"instance_id": instance_id, "error": type(exc).__name__})
        reports.append(
            {
                "worker_id": worker_id,
                "instance_count": len(proxy_instances),
                "results": results,
                "bad_details": details,
            }
        )
    print(json.dumps({"reports": reports, "read_only": True}, indent=2, sort_keys=True))


asyncio.run(main())
