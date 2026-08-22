"""Official NKN beneficiary balance and worker-node summary collector."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from app.collectors import base
from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

NKN_RPC_URL = "https://mainnet-rpc-node-0001.nkn.org/mainnet/api/wallet"


class NknCollector(BaseCollector):
    platform = "nkn"

    def __init__(self, beneficiary_address: str = "") -> None:
        super().__init__()
        self.beneficiary_address = str(beneficiary_address or "").strip()

    async def collect(self) -> EarningsResult:
        if not self.beneficiary_address:
            return EarningsResult(
                platform=self.platform, balance=0.0, currency="NKN", error="NKN beneficiary address is not configured"
            )
        try:
            client = self._get_client(timeout=30)

            async def fetch() -> httpx.Response:
                return await client.post(
                    NKN_RPC_URL,
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                    json={
                        "jsonrpc": "2.0",
                        "method": "getbalancebyaddr",
                        "params": {"address": self.beneficiary_address},
                        "id": 1,
                    },
                )

            response = await self._retry(fetch)
            response.raise_for_status()
            payload = response.json()
            amount = (payload.get("result") or {}).get("amount") if isinstance(payload, Mapping) else None
            if amount is None:
                raise ValueError("NKN balance amount field missing")
            return EarningsResult(platform=self.platform, balance=float(amount), currency="NKN")
        except Exception as exc:  # noqa: BLE001 - collector boundary
            base.log_failure(logger, "NKN", exc)
            return EarningsResult(
                platform=self.platform, balance=0.0, currency="NKN", error="NKN balance collection failed"
            )

    @staticmethod
    def node_summary(instances: Sequence[Mapping[str, Any]]) -> dict[str, int]:
        total = len(instances)
        online = sum(1 for instance in instances if (instance.get("evidence") or {}).get("online") is True)
        return {"total": total, "online": online, "offline": total - online}
