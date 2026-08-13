"""Titan rewards collector."""

from __future__ import annotations

import logging
import re

from app.collectors import base
from app.collectors.base import KIND_AUTH, KIND_SHAPE, BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

BASE_URL = "https://edge.titannet.info/deviceManagement"


def _parse_tntip(text: str) -> float:
    match = re.search(r"Total Earnings\s+([\d.]+)\s*TNTIP", text, re.IGNORECASE | re.S)
    if not match:
        raise ValueError("Titan total earnings field missing")
    return float(match.group(1))


class TitanCollector(BaseCollector):
    """Collect Titan dashboard total earnings from a logged-in session."""

    platform = "titan"

    def __init__(self, dashboard_session: str) -> None:
        super().__init__()
        self.dashboard_session = dashboard_session.strip()

    async def collect(self) -> EarningsResult:
        try:
            client = self._get_client(timeout=30, headers={"Cookie": self.dashboard_session})
            resp = await client.get(BASE_URL)
            resp.raise_for_status()
            if "Device Management" not in resp.text or "Connection Status" not in resp.text:
                return EarningsResult(
                    platform=self.platform,
                    balance=0.0,
                    currency="TNTIP",
                    error="Authentication failed - check Titan dashboard session",
                    error_kind=KIND_AUTH,
                )
            total = _parse_tntip(resp.text)
            return EarningsResult(platform=self.platform, balance=round(total, 4), currency="TNTIP")
        except ValueError as exc:
            return EarningsResult(platform=self.platform, balance=0.0, currency="TNTIP", error=str(exc), error_kind=KIND_SHAPE)
        except Exception as exc:
            base.log_failure(logger, "Titan", exc)
            return EarningsResult(platform=self.platform, balance=0.0, currency="TNTIP", error=str(exc), error_kind=base.classify_exception(exc))
