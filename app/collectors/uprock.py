"""Uprock account-level earnings collector."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx  # noqa: F401 - tests patch this module's client path

from app.collectors import base
from app.collectors.base import KIND_AUTH, KIND_SHAPE, KIND_TRANSIENT, BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

API_BASE = "https://backend.uprock.com"

def _load_seed(value: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ValueError("Uprock credentials_json is empty")
    try:
        data = json.loads(text)
    except ValueError:
        return text
    token = str(data.get("main") or "").strip()
    if not token:
        raise ValueError("Uprock credentials_json.main is missing")
    return token

def _money(payload: dict[str, Any]) -> float:
    if "total_in_usd" not in payload:
        raise KeyError("total_in_usd")
    return float(payload.get("total_in_usd") or 0)

class UprockCollector(BaseCollector):
    """Collect Uprock account wallet total from the desktop seed token."""

    platform = "uprock"

    def __init__(self, credentials_json: str) -> None:
        super().__init__()
        self.refresh_token = _load_seed(credentials_json)

    async def _get_json(self, path: str, token: str) -> dict[str, Any]:
        client = self._get_client(timeout=30)
        resp = await self._retry(
            lambda: client.get(
                f"{API_BASE}{path}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "User-Agent": "UpRock-Mining/0.0.38",
                },
            )
        )
        if resp.status_code in (401, 403):
            raise PermissionError("Uprock token rejected")
        if resp.status_code >= 500 or resp.status_code == 429:
            raise TimeoutError("Uprock API temporarily unavailable")
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise TypeError("Uprock API returned non-object JSON")
        return data

    async def collect(self) -> EarningsResult:
        try:
            refreshed = await self._get_json("/auth/refresh_token", self.refresh_token)
            access_token = str(refreshed.get("access_token") or "")
            if not access_token:
                raise KeyError("access_token")
            wallet = await self._get_json("/transactions/wallet", access_token)
            await self._get_json("/transactions/rewards", access_token)
            return EarningsResult(platform=self.platform, balance=round(_money(wallet), 4), currency="USD")
        except PermissionError as exc:
            return EarningsResult(platform=self.platform, balance=0.0, error=str(exc), error_kind=KIND_AUTH)
        except TimeoutError as exc:
            return EarningsResult(platform=self.platform, balance=0.0, error=str(exc), error_kind=KIND_TRANSIENT)
        except (KeyError, TypeError, ValueError) as exc:
            return EarningsResult(platform=self.platform, balance=0.0, error=str(exc), error_kind=KIND_SHAPE)
        except Exception as exc:
            base.log_failure(logger, "Uprock", exc)
            return EarningsResult(platform=self.platform, balance=0.0, error=str(exc))
