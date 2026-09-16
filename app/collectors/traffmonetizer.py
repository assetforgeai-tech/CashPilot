"""Traffmonetizer earnings collector.

Traffmonetizer balance reads use the dashboard auth session. The collector logs
in with email/password, then calls the balance API.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC
from email.utils import parsedate_to_datetime

import httpx

from app.collectors import base
from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

# The dashboard bundle publishes data.traffmonetizer.com as its API origin.
API_BASE = "https://data.traffmonetizer.com/api"


class TraffmonetizerCollector(BaseCollector):
    """Collect earnings from Traffmonetizer's API using email/password."""

    platform = "traffmonetizer"

    def __init__(self, email: str = "", password: str = "") -> None:
        super().__init__()
        self.email = email.strip()
        self.password = password.strip()
        self._token: str = ""
        self._cooldown_until = 0.0

    def _check_cooldown(self) -> None:
        if time.monotonic() < self._cooldown_until:
            raise RuntimeError("Traffmonetizer rate limited - retry later")

    def _set_cooldown(self, response: httpx.Response) -> None:
        value = response.headers.get("Retry-After", "")
        try:
            seconds = float(value)
        except ValueError:
            try:
                seconds = max(
                    0.0,
                    (parsedate_to_datetime(value).astimezone(UTC).timestamp() - time.time()),
                )
            except (TypeError, ValueError, OverflowError):
                seconds = 60.0
        self._cooldown_until = time.monotonic() + min(max(seconds, 1.0), 3600.0)

    async def _authenticate(self, client: httpx.AsyncClient) -> str:
        self._check_cooldown()
        resp = await client.post(
            f"{API_BASE}/auth/login",
            json={
                "email": self.email,
                "password": self.password,
                "g-recaptcha-response": "",
                "visitor_id": "",
            },
            headers={
                "Origin": "https://app.traffmonetizer.com",
                "Referer": "https://app.traffmonetizer.com/dashboard",
            },
        )
        resp.raise_for_status()
        data = resp.json() or {}
        token = str((data.get("data") or {}).get("token") or data.get("token") or "").strip()
        if not token:
            raise ValueError("No token in Traffmonetizer login response")
        return token

    async def collect(self) -> EarningsResult:
        if not self.email or not self.password:
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error="No collector credentials configured - enter Traffmonetizer email and password",
            )

        try:
            self._check_cooldown()
            client = self._get_client(timeout=30)
            if not self._token:
                self._token = await self._authenticate(client)

            headers = {
                "Authorization": f"Bearer {self._token}",
                "Origin": "https://app.traffmonetizer.com",
                "Referer": "https://app.traffmonetizer.com/dashboard",
            }

            async def _fetch_balance() -> httpx.Response:
                return await client.get(f"{API_BASE}/app_user/get_balance", headers=headers)

            resp = await self._retry(_fetch_balance)
            if resp.status_code in (401, 403):
                self._token = await self._authenticate(client)
                headers["Authorization"] = f"Bearer {self._token}"
                resp = await self._retry(_fetch_balance)
                if resp.status_code in (401, 403):
                    return EarningsResult(
                        platform=self.platform,
                        balance=0.0,
                        error="Traffmonetizer login rejected - check email/password",
                    )

            resp.raise_for_status()
            data = resp.json()
            raw = data.get("data", {}).get("balance")
            if raw is None:
                raise ValueError("balance field missing - API shape may have changed")

            return EarningsResult(
                platform=self.platform,
                balance=round(float(raw), 4),
                currency="USD",
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                self._set_cooldown(exc.response)
                return EarningsResult(
                    platform=self.platform,
                    balance=0.0,
                    error="Traffmonetizer rate limited - retry later",
                    error_kind=base.KIND_TRANSIENT,
                )
            if exc.response.status_code in (401, 403, 422):
                return EarningsResult(
                    platform=self.platform,
                    balance=0.0,
                    error="Traffmonetizer credentials rejected - update the collector credentials",
                    error_kind=base.KIND_AUTH,
                )
            base.log_failure(logger, "Traffmonetizer", exc)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error="Traffmonetizer API request failed",
                error_kind=base.classify_exception(exc),
            )
        except RuntimeError as exc:
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=str(exc),
                error_kind=base.KIND_TRANSIENT,
            )
        except Exception as exc:
            base.log_failure(logger, "Traffmonetizer", exc)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=str(exc),
            )
