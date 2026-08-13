"""Dawn rewards collector."""

from __future__ import annotations

import logging
import re

from app.collectors import base
from app.collectors.base import KIND_AUTH, KIND_SHAPE, BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

BASE_URL = "https://dashboard.dawninternet.com/dashboard"


def _parse_points(text: str) -> float:
    match = re.search(r"Total Rewards\s+([\d,]+)\s+Points", text, re.IGNORECASE | re.S)
    if not match:
        raise ValueError("Dawn total rewards field missing")
    return float(match.group(1).replace(",", ""))


class DawnCollector(BaseCollector):
    """Collect Dawn dashboard points from a logged-in session."""

    platform = "dawn"

    def __init__(self, dashboard_session: str) -> None:
        super().__init__()
        self.dashboard_session = dashboard_session.strip()

    async def collect(self) -> EarningsResult:
        try:
            client = self._get_client(timeout=30, headers={"Cookie": self.dashboard_session})
            resp = await client.get(BASE_URL)
            resp.raise_for_status()
            if "Log out" not in resp.text and "Connection Quality" not in resp.text:
                return EarningsResult(
                    platform=self.platform,
                    balance=0.0,
                    currency="DAWN",
                    error="Authentication failed - check Dawn dashboard session",
                    error_kind=KIND_AUTH,
                )
            points = _parse_points(resp.text)
            return EarningsResult(platform=self.platform, balance=round(points, 4), currency="DAWN")
        except ValueError as exc:
            return EarningsResult(platform=self.platform, balance=0.0, currency="DAWN", error=str(exc), error_kind=KIND_SHAPE)
        except Exception as exc:
            base.log_failure(logger, "Dawn", exc)
            return EarningsResult(platform=self.platform, balance=0.0, currency="DAWN", error=str(exc), error_kind=base.classify_exception(exc))
