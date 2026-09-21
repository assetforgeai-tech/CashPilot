"""Proxies.sx peer earnings collector."""

from __future__ import annotations

import logging
from typing import Any

import httpx  # noqa: F401 - used by tests patching this module

from app.collectors import base
from app.collectors.base import KIND_AUTH, KIND_TRANSIENT, BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

API_BASE = "https://api.proxies.sx/v1"


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, dict):
        for key in ("amount", "usd", "value", "total"):
            parsed = _as_float(value.get(key))
            if parsed is not None:
                return parsed
        return None
    text = str(value).strip().replace("$", "").replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _devices(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [d for d in payload if isinstance(d, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("devices", "agents", "peers", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [d for d in value if isinstance(d, dict)]
    data = payload.get("data")
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    if isinstance(data, dict):
        return _devices(data)
    return []


def _device_money(device: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        parsed = _as_float(device.get(key))
        if parsed is not None:
            return parsed
    return None


def _cents_to_usd(value: Any) -> float | None:
    parsed = _as_float(value)
    return None if parsed is None else parsed / 100.0


def _device_money_usd(device: dict[str, Any], keys: tuple[str, ...], cent_keys: tuple[str, ...] = ()) -> float | None:
    parsed = _device_money(device, keys)
    if parsed is not None:
        return parsed
    for key in cent_keys:
        parsed = _cents_to_usd(device.get(key))
        if parsed is not None:
            return parsed
    return None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "on", "listed", "online", "connected", "verified", "active"}


def _device_status(device: dict[str, Any]) -> str:
    raw = device.get("status") or device.get("state") or device.get("connectionStatus") or ""
    text = str(raw).strip().lower()
    return text or "unknown"


class ProxiesSxCollector(BaseCollector):
    """Collect Proxies.sx peer earnings from the peer API."""

    platform = "proxies-sx"

    def __init__(self, api_key: str) -> None:
        super().__init__()
        self.api_key = api_key.strip()

    async def _fetch_devices(self) -> list[dict[str, Any]]:
        client = self._get_client(timeout=30)
        resp = await self._retry(
            lambda: client.get(
                f"{API_BASE}/peer/my-devices",
                headers={"X-API-Key": self.api_key, "Accept": "application/json"},
            )
        )
        if resp.status_code in (401, 403):
            raise PermissionError("API key rejected by Proxies.sx")
        if resp.status_code == 429:
            raise TimeoutError("Proxies.sx API rate limited this request")
        resp.raise_for_status()
        return _devices(resp.json())

    async def collect(self) -> EarningsResult:
        if not self.api_key:
            return EarningsResult(platform=self.platform, balance=0.0, error="Proxies.sx API key not configured")
        try:
            devices = await self._fetch_devices()
            pending_keys = ("pendingPayout", "pending_payout", "withdrawableBalance", "balance")
            lifetime_keys = ("totalEarned", "total_earned", "earnings", "earned")
            pending = [
                _device_money_usd(d, pending_keys, ("pendingPayoutCents", "pending_payout_cents")) for d in devices
            ]
            values = [v for v in pending if v is not None]
            if not values:
                values = [
                    v
                    for v in (
                        _device_money_usd(d, lifetime_keys, ("totalEarnedCents", "total_earned_cents")) for d in devices
                    )
                    if v is not None
                ]
            return EarningsResult(platform=self.platform, balance=round(sum(values), 4), currency="USD")
        except PermissionError as exc:
            return EarningsResult(platform=self.platform, balance=0.0, error=str(exc), error_kind=KIND_AUTH)
        except TimeoutError as exc:
            return EarningsResult(platform=self.platform, balance=0.0, error=str(exc), error_kind=KIND_TRANSIENT)
        except Exception as exc:
            base.log_failure(logger, "Proxies.sx", exc)
            return EarningsResult(platform=self.platform, balance=0.0, error=str(exc))

    async def get_per_node_earnings(self) -> list[dict[str, Any]]:
        if not self.api_key:
            return []
        result = []
        for device in await self._fetch_devices():
            status = _device_status(device)
            result.append(
                {
                    "device_id": device.get("deviceId") or device.get("device_id") or device.get("id") or "",
                    "name": device.get("name") or device.get("agentName") or "",
                    "status": status,
                    "online": _as_bool(device.get("online"))
                    or _as_bool(device.get("isOnline"))
                    or status in {"online", "connected", "listed", "earning"},
                    "earning": status == "earning" or _as_bool(device.get("earning")),
                    "listed": _as_bool(device.get("listedForSale"))
                    or _as_bool(device.get("listed"))
                    or status in {"listed", "earning"},
                    "verification": str(
                        device.get("verification")
                        or ("verified" if device.get("verified") is True else device.get("verified"))
                        or ""
                    )
                    .strip()
                    .lower(),
                    "speed": str(
                        device.get("speed")
                        or device.get("speedMbps")
                        or (
                            f"{device.get('probeQuality', {}).get('throughputKBps')} KB/s"
                            if isinstance(device.get("probeQuality"), dict)
                            and device.get("probeQuality", {}).get("throughputKBps") is not None
                            else ""
                        )
                    ).strip(),
                    "customer_routable": _as_bool(device.get("customerRoutable") or device.get("customer_routable"))
                    or _as_bool((device.get("probeQuality") or {}).get("workingForCustomers"))
                    if isinstance(device.get("probeQuality"), dict)
                    else _as_bool(device.get("customerRoutable") or device.get("customer_routable")),
                    "gateway_failure": str((device.get("probeQuality") or {}).get("lastFailureReason") or "").strip()
                    if isinstance(device.get("probeQuality"), dict)
                    else "",
                    "gateway_probe": str((device.get("probeQuality") or {}).get("probeMode") or "").strip()
                    if isinstance(device.get("probeQuality"), dict)
                    else "",
                    "gateway_last_probe": str((device.get("probeQuality") or {}).get("lastProbedAt") or "").strip()
                    if isinstance(device.get("probeQuality"), dict)
                    else "",
                    "quality": device.get("quality") or device.get("qualityScore") or "",
                    "traffic": str(
                        device.get("traffic")
                        or device.get("trafficBytes")
                        or (f"{device.get('totalTrafficGB')} GB" if device.get("totalTrafficGB") is not None else "")
                        or (f"{device.get('totalTrafficMB')} MB" if device.get("totalTrafficMB") is not None else "")
                    ).strip(),
                    "last_seen": str(
                        device.get("lastSeen") or device.get("last_seen") or device.get("lastSeenAt") or ""
                    ).strip(),
                    "country": device.get("country") or device.get("countryCode") or "",
                    "ip": device.get("ip") or device.get("publicIp") or "",
                    "pending_payout_usd": _device_money_usd(
                        device, ("pendingPayout", "pending_payout"), ("pendingPayoutCents", "pending_payout_cents")
                    )
                    or 0.0,
                    "total_earned_usd": _device_money_usd(
                        device,
                        ("totalEarned", "total_earned", "earnings", "earned"),
                        ("totalEarnedCents", "total_earned_cents"),
                    )
                    or 0.0,
                }
            )
        return result
