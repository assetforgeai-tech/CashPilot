"""Read-only, account-scoped EarnApp dashboard collector."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

from app.collectors import base

API_BASE = "https://earnapp.com/dashboard/api"
API_PARAMS = {"appid": "earnapp"}
AUTH_FAILURE_CODES = {401, 403}


def build_proxy_url(proxy: Mapping[str, Any]) -> str:
    protocol = str(proxy.get("protocol") or "").strip().lower()
    if protocol not in {"http", "socks5"}:
        raise ValueError("EarnApp collector proxy must be HTTP or SOCKS5")
    host = str(proxy.get("host") or "").strip()
    port = int(proxy.get("port") or 0)
    if not host or not 1 <= port <= 65535:
        raise ValueError("EarnApp collector proxy host/port is invalid")
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    username = str(proxy.get("username") or "")
    password = str(proxy.get("password") or "")
    auth = ""
    if username or password:
        auth = f"{quote(username, safe='')}:{quote(password, safe='')}@"
    return f"{protocol}://{auth}{host}:{port}"


def _float(value: Any) -> float:
    try:
        return float(str(value).replace("$", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, str) and not value.strip():
        return None
    try:
        return float(str(value).replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    parsed = _optional_float(value)
    return None if parsed is None else max(0, int(parsed))


def _payload_devices(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, Mapping):
        return []
    for key in ("devices", "items", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _status_for(statuses: Any, device_id: str) -> Any:
    if isinstance(statuses, Mapping):
        direct = statuses.get(device_id)
        if direct is not None:
            return direct
        for key in ("statuses", "devices", "data"):
            nested = statuses.get(key)
            if isinstance(nested, Mapping) and device_id in nested:
                return nested[device_id]
            if isinstance(nested, list):
                for item in nested:
                    if (
                        isinstance(item, Mapping)
                        and str(item.get("device_id") or item.get("uuid") or item.get("id") or "") == device_id
                    ):
                        return item
    return None


def _online(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (list, tuple)):
        return bool(value and value[0])
    if isinstance(value, Mapping):
        if "online" in value:
            return bool(value.get("online"))
        value = value.get("status") or value.get("state") or value.get("connection_status")
    return str(value or "").strip().lower() in {"online", "connected", "active", "green", "enabled"}


def _device_id(raw: Mapping[str, Any]) -> str:
    return str(raw.get("device_id") or raw.get("uuid") or raw.get("id") or "").strip()


def _device_for(payload: Any, device_id: str) -> dict[str, Any] | None:
    for row in _payload_devices(payload):
        if _device_id(row) == device_id:
            return row
    return None


def _first_ip(raw: Mapping[str, Any], node: Mapping[str, Any] | None = None) -> str:
    nested = node if isinstance(node, Mapping) else {}
    direct = nested.get("ip") or raw.get("ip") or raw.get("public_ip")
    if direct:
        return str(direct)
    ips = raw.get("ips")
    if isinstance(ips, list):
        return next((str(value) for value in ips if str(value).strip()), "")
    return ""


def normalize_usage_series(payload: Any) -> dict[str, dict[str, Any]]:
    rows = payload if isinstance(payload, list) else []
    if isinstance(payload, Mapping):
        for key in ("list", "items", "data"):
            if isinstance(payload.get(key), list):
                rows = payload[key]
                break
    normalized: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        device_id = str(raw.get("_id") or raw.get("device_id") or raw.get("uuid") or "").strip()
        data = raw.get("data")
        if not device_id or not isinstance(data, Mapping):
            continue
        points = [value for value in (_optional_float(item) for item in data.values()) if value is not None]
        today_key = datetime.now(UTC).date().isoformat()
        # A missing UTC-today bucket means current workload is unknown; never
        # promote the latest historical bucket into the live verification metric.
        current = _optional_float(data.get(today_key)) if today_key in data else None
        normalized[device_id] = {
            "name": str(raw.get("name") or device_id),
            "total": sum(points),
            "current": current,
            "points": len(points),
        }
    return normalized


def _device_metrics(
    raw: Mapping[str, Any],
    usage: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    # EarnApp has emitted both the compact dashboard keys and descriptive keys.
    # Keep both forms normalized so usage evidence survives API shape changes.
    bandwidth = raw.get("bandwidth", raw.get("bw", raw.get("traffic")))
    total_bandwidth = raw.get("total_bandwidth", raw.get("total_bw"))
    redeemed_bandwidth = raw.get("redeemed_bandwidth", raw.get("redeem_bw"))
    usage_row = usage.get(_device_id(raw)) if isinstance(usage, Mapping) else None
    return {
        "ip": _first_ip(raw),
        "country_code": str(raw.get("country") or raw.get("country_code") or "").strip().upper(),
        "bandwidth": _optional_float(bandwidth),
        "total_bandwidth": _optional_float(total_bandwidth),
        "redeemed_bandwidth": _optional_float(redeemed_bandwidth),
        "earned": _optional_float(raw.get("earned")),
        "earned_total": _optional_float(raw.get("earned_total")),
        "uptime": _optional_int(raw.get("uptime")),
        "total_uptime": _optional_int(raw.get("total_uptime")),
        "billing": str(raw.get("billing") or "").strip(),
        "usage_total": _optional_float(usage_row.get("total")) if isinstance(usage_row, Mapping) else None,
        "usage_current": _optional_float(usage_row.get("current")) if isinstance(usage_row, Mapping) else None,
        "usage_points": int(usage_row.get("points") or 0) if isinstance(usage_row, Mapping) else 0,
        "usage_available": isinstance(usage_row, Mapping),
    }


def _banned(device: Mapping[str, Any] | None) -> bool:
    if not isinstance(device, Mapping):
        return False
    return bool(device.get("banned") or device.get("is_banned"))


def _mask_destination(value: Any) -> str:
    """Keep payment snapshots useful without persisting a payout address."""
    text = str(value or "").strip()
    if not text:
        return ""
    if "@" in text:
        local, domain = text.split("@", 1)
        return f"{local[:1]}***@{domain}"
    return f"{text[:2]}***"


def _normalize_payment_methods(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping):
        return []
    rows: list[dict[str, Any]] = []
    for method_id, raw in sorted(payload.items(), key=lambda item: str(item[0])):
        if not isinstance(raw, Mapping):
            continue
        rows.append(
            {
                "id": str(method_id),
                "label": str(raw.get("value") or method_id),
                "minimum": _optional_float(raw.get("min_redeem")),
                "fee_fixed": _optional_float(raw.get("fixed_fee")),
                "fee_percent": _optional_float(raw.get("percentage_fee")),
                "disabled": bool(raw.get("disabled")),
                "parent": str(raw.get("parent") or ""),
            }
        )
    return rows


def _normalize_transactions(payload: Any) -> list[dict[str, Any]]:
    rows = payload if isinstance(payload, list) else payload.get("list", []) if isinstance(payload, Mapping) else []
    if not isinstance(rows, list):
        return []
    allowed = {"id", "date", "payment_date", "money_amount", "fee_amount", "payment_method", "status"}
    return [
        {str(key): value for key, value in row.items() if str(key) in allowed}
        for row in rows
        if isinstance(row, Mapping)
    ]


def normalize_payment(methods: Any, redeem_details: Any, transactions: Any) -> dict[str, Any]:
    details = redeem_details if isinstance(redeem_details, Mapping) else {}
    method = details.get("payment_method") or details.get("method") or ""
    destination = details.get("email") or details.get("to") or details.get("paypal_email") or ""
    return {
        "configured": bool(method and destination),
        "method": str(method),
        "destination_masked": _mask_destination(destination),
        "methods": _normalize_payment_methods(methods),
        "transactions": _normalize_transactions(transactions),
    }


def normalize_snapshot(
    user_data: Any,
    money: Any,
    devices_payload: Any,
    statuses: Any,
    usage_payload: Any = None,
) -> dict[str, Any]:
    user = dict(user_data) if isinstance(user_data, Mapping) else {}
    balances = dict(money) if isinstance(money, Mapping) else {}
    usage = normalize_usage_series(usage_payload)
    devices: list[dict[str, Any]] = []
    for raw in _payload_devices(devices_payload):
        device_id = str(raw.get("device_id") or raw.get("uuid") or raw.get("id") or "").strip()
        if not device_id:
            continue
        node = raw.get("node") if isinstance(raw.get("node"), Mapping) else {}
        share = raw.get("share") if isinstance(raw.get("share"), Mapping) else {}
        status = _status_for(statuses, device_id)
        devices.append(
            {
                "device_id": device_id,
                **_device_metrics(raw, usage),
                "ip": _first_ip(raw, node),
                "rate": _float(share.get("rate", raw.get("rate"))),
                "online": _online(status),
            }
        )
    balance = balances.get("money_balance", balances.get("balance", user.get("money_balance", user.get("balance"))))
    total = balances.get(
        "money_total",
        balances.get(
            "earnings_total",
            balances.get("total", user.get("money_total", user.get("earnings_total", user.get("total")))),
        ),
    )
    online = sum(1 for device in devices if device["online"])
    available = [device for device in devices if device.get("usage_available")]
    payment = {
        key: value
        for key, value in {**user, **balances}.items()
        if str(key).lower()
        in {
            "payment_method",
            "payment_methods",
            "payout_method",
            "payout_methods",
            "payout_threshold",
            "minimum_payout",
            "currency",
            "payment_currency",
            "paypal_email",
            "payment_email",
            "payout_status",
        }
    }
    snapshot = {
        "status": "ok",
        "money_balance": _float(balance),
        "money_total": _float(total),
        "online_nodes": online,
        "offline_nodes": len(devices) - online,
        "usage_current": sum(float(device.get("usage_current") or 0) for device in available),
        "usage_total": sum(float(device.get("usage_total") or 0) for device in available),
        "usage_available_nodes": len(available),
        "usage_missing_nodes": len(devices) - len(available),
        "devices": devices,
    }
    if payment:
        snapshot["payment"] = payment
    return snapshot


class EarnAppAccountCollector:
    """One uncached collector bound to one account and one of its proxies."""

    def __init__(self, credentials: Mapping[str, Any], proxy: Mapping[str, Any]) -> None:
        raw_cookies = credentials.get("cookies") if isinstance(credentials, Mapping) else {}
        if not isinstance(raw_cookies, Mapping):
            raw_cookies = {}
        self.cookies = {str(key): str(value) for key, value in raw_cookies.items() if str(value)}
        self.proxy_url = build_proxy_url(proxy)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=30,
            cookies=self.cookies,
            proxy=self.proxy_url,
            follow_redirects=False,
        )

    @staticmethod
    def _headers(client: httpx.AsyncClient, fallback_cookies: Mapping[str, str]) -> dict[str, str]:
        xsrf = str(client.cookies.get("xsrf-token") or fallback_cookies.get("xsrf-token") or "")
        # Match the dashboard's browser contract for authenticated XHR calls.
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://earnapp.com",
            "Referer": "https://earnapp.com/dashboard/",
        }
        if xsrf:
            headers["xsrf-token"] = xsrf
        return headers

    async def _payment_state(self, client: httpx.AsyncClient, headers: Mapping[str, str]) -> dict[str, Any]:
        methods = await client.get(f"{API_BASE}/payment_methods", params=API_PARAMS, headers=headers)
        details = await client.get(f"{API_BASE}/redeem_details", params=API_PARAMS, headers=headers)
        transactions = await client.get(f"{API_BASE}/transactions", params=API_PARAMS, headers=headers)
        return normalize_payment(
            methods.json() if methods.status_code == 200 else {},
            details.json() if details.status_code == 200 else {},
            transactions.json() if transactions.status_code == 200 else [],
        )

    async def configure_payment(self, *, payment_method: str, destination: str) -> dict[str, Any]:
        client = self._client()
        try:
            rotate = await client.get(f"{API_BASE}/sec/rotate_xsrf", params=API_PARAMS)
            rotate.raise_for_status()
            headers = self._headers(client, self.cookies)
            methods_response = await client.get(f"{API_BASE}/payment_methods", params=API_PARAMS, headers=headers)
            methods_response.raise_for_status()
            methods = _normalize_payment_methods(methods_response.json())
            selected = next((item for item in methods if item["id"] == payment_method), None)
            if not selected or selected["disabled"]:
                raise ValueError("payment method is unavailable")
            response = await client.post(
                f"{API_BASE}/redeem_details",
                params=API_PARAMS,
                headers=headers,
                json={"to": destination, "payment_method": payment_method},
            )
            response.raise_for_status()
            return await self._payment_state(client, headers)
        finally:
            await client.aclose()

    async def disable_payment(self) -> dict[str, Any]:
        client = self._client()
        try:
            rotate = await client.get(f"{API_BASE}/sec/rotate_xsrf", params=API_PARAMS)
            rotate.raise_for_status()
            headers = self._headers(client, self.cookies)
            response = await client.delete(f"{API_BASE}/redeem_details", params=API_PARAMS, headers=headers)
            response.raise_for_status()
            state = await self._payment_state(client, headers)
            return {**state, "configured": False, "method": "", "destination_masked": ""}
        finally:
            await client.aclose()

    @staticmethod
    def _link_contract(device_id: str, platform: str, xsrf: str) -> tuple[dict[str, str], dict[str, str]]:
        wire_platform = {"ubuntu": "linux", "macos": "macos", "ios": "ios"}.get(platform, platform)
        headers = {
            "Referer": f"https://earnapp.com/dashboard/link/{device_id}",
            "csrf-token": xsrf,
            "xsrf-token": xsrf,
            "x-csrf-token": xsrf,
            "x-xsrf-token": xsrf,
            "X-XSRF-TOKEN": xsrf,
        }
        return headers, {"uuid": device_id, "platform": wire_platform, "_csrf": xsrf}

    async def link_and_verify_device(self, device_id: str, *, platform: str = "macos") -> dict[str, Any]:
        """Link one device through its account proxy and return secret-free dashboard evidence."""
        uuid = str(device_id or "").strip()
        if not uuid:
            return {"status": "error", "error_kind": "shape", "error": "EarnApp device id is required"}
        client = self._client()
        try:
            rotate = await client.get(f"{API_BASE}/sec/rotate_xsrf", params=API_PARAMS)
            if rotate.status_code in AUTH_FAILURE_CODES:
                return {"status": "error", "error_kind": "auth", "error": "authentication rejected"}
            rotate.raise_for_status()
            headers = self._headers(client, self.cookies)
            user_response = await client.get(f"{API_BASE}/user_data", params=API_PARAMS, headers=headers)
            if user_response.status_code in AUTH_FAILURE_CODES:
                return {"status": "error", "error_kind": "auth", "error": "authentication rejected"}
            if user_response.status_code == 406 and "ip_block" in str(user_response.headers.get("location") or ""):
                return {"status": "error", "error_kind": "proxy_blocked", "error": "EarnApp blocked the account proxy"}
            user_response.raise_for_status()

            devices_response = await client.get(f"{API_BASE}/devices", params=API_PARAMS, headers=headers)
            if devices_response.status_code in AUTH_FAILURE_CODES:
                return {"status": "error", "error_kind": "auth", "error": "authentication rejected"}
            devices_response.raise_for_status()
            device = _device_for(devices_response.json(), uuid)
            # Official runtimes register a UUID before account linking.  Always
            # perform the account-scoped API link instead of treating presence
            # in /devices as proof that the account assignment is complete.
            link_attempted = True
            xsrf = str(client.cookies.get("xsrf-token") or self.cookies.get("xsrf-token") or "")
            if not xsrf:
                return {"status": "error", "error_kind": "auth", "error": "EarnApp XSRF unavailable"}
            link_headers, link_request = self._link_contract(uuid, platform, xsrf)
            link_response = await client.post(
                f"{API_BASE}/link_device",
                params=API_PARAMS,
                headers={**headers, **link_headers},
                json=link_request,
            )
            if link_response.status_code in AUTH_FAILURE_CODES:
                return {"status": "error", "error_kind": "auth", "error": "authentication rejected"}
            # Registration in /devices is not proof of account linking.  A
            # rate-limited link must remain pending so workload verification
            # cannot report a false online node.
            if link_response.status_code == 429:
                return {
                    "status": "pending",
                    "error_kind": "rate_limited",
                    "error": "EarnApp device link is rate-limited",
                    "device_id": uuid,
                    "authenticated": True,
                    "link_attempted": True,
                    "device_present": device is not None,
                    "online": False,
                    "banned": bool(device and _banned(device)),
                    "retry_after_seconds": 300,
                }
            link_response.raise_for_status()
            link_result = link_response.json()
            link_error = str(link_result.get("error") or "") if isinstance(link_result, Mapping) else ""
            already_linked = "already linked" in link_error.lower()
            if link_error and not already_linked:
                return {
                    "status": "error",
                    "error_kind": "remote",
                    "error": "EarnApp rejected device link",
                    "device_id": uuid,
                    "authenticated": True,
                    "link_attempted": True,
                    "device_present": False,
                    "online": False,
                    "banned": False,
                }
            # Treat an "already linked" response as success only after an
            # authenticated refetch still contains this exact UUID.
            devices_response = await client.get(f"{API_BASE}/devices", params=API_PARAMS, headers=headers)
            if devices_response.status_code in AUTH_FAILURE_CODES:
                return {"status": "error", "error_kind": "auth", "error": "authentication rejected"}
            devices_response.raise_for_status()
            device = _device_for(devices_response.json(), uuid)

            if device is None:
                if already_linked:
                    return {
                        "status": "error",
                        "error_kind": "remote",
                        "error": "EarnApp rejected device link",
                        "device_id": uuid,
                        "authenticated": True,
                        "link_attempted": True,
                        "device_present": False,
                        "online": False,
                        "banned": False,
                    }
                return {
                    "status": "pending",
                    "device_id": uuid,
                    "authenticated": True,
                    "link_attempted": link_attempted,
                    "device_present": False,
                    "online": False,
                    "banned": False,
                }
            status_response = await client.post(
                f"{API_BASE}/device_statuses",
                params=API_PARAMS,
                headers=headers,
                json={"data": {"devices": [uuid]}},
            )
            if status_response.status_code in AUTH_FAILURE_CODES:
                return {"status": "error", "error_kind": "auth", "error": "authentication rejected"}
            status_response.raise_for_status()
            online = _online(_status_for(status_response.json(), uuid))
            banned = _banned(device)
            usage_response = await client.get(
                f"{API_BASE}/usage",
                params={**API_PARAMS, "step": "daily"},
                headers=headers,
            )
            if usage_response.status_code in AUTH_FAILURE_CODES:
                return {"status": "error", "error_kind": "auth", "error": "authentication rejected"}
            usage_response.raise_for_status()
            usage = normalize_usage_series(usage_response.json())
            return {
                "status": "online" if online and not banned else "offline",
                "device_id": uuid,
                "authenticated": True,
                "link_attempted": link_attempted,
                "device_present": True,
                "online": online,
                "banned": banned,
                **_device_metrics(device, usage),
            }
        except (httpx.TimeoutException, httpx.NetworkError, httpx.ProxyError):
            return {"status": "error", "error_kind": "route", "error": "proxy unavailable"}
        except httpx.HTTPStatusError as exc:
            kind = base.classify_exception(exc)
            return {
                "status": "error",
                "error_kind": "auth" if kind == base.KIND_AUTH else "route",
                "error": "authentication rejected" if kind == base.KIND_AUTH else "EarnApp route unavailable",
            }
        except (TypeError, ValueError, KeyError):
            return {"status": "error", "error_kind": "shape", "error": "EarnApp API shape changed"}
        finally:
            await client.aclose()

    async def collect_snapshot(self) -> dict[str, Any]:
        try:
            client = self._client()
            try:
                rotate = await client.get(f"{API_BASE}/sec/rotate_xsrf", params=API_PARAMS)
                if rotate.status_code in AUTH_FAILURE_CODES:
                    return {"status": "error", "error_kind": "auth", "error": "authentication rejected"}
                rotate.raise_for_status()
                headers = self._headers(client, self.cookies)

                user_response = await client.get(f"{API_BASE}/user_data", params=API_PARAMS, headers=headers)
                money_response = await client.get(f"{API_BASE}/money", params=API_PARAMS, headers=headers)
                devices_response = await client.get(f"{API_BASE}/devices", params=API_PARAMS, headers=headers)
                usage_response = await client.get(
                    f"{API_BASE}/usage",
                    params={**API_PARAMS, "step": "daily"},
                    headers=headers,
                )
                payment_methods_response = await client.get(
                    f"{API_BASE}/payment_methods", params=API_PARAMS, headers=headers
                )
                redeem_details_response = await client.get(
                    f"{API_BASE}/redeem_details", params=API_PARAMS, headers=headers
                )
                transactions_response = await client.get(f"{API_BASE}/transactions", params=API_PARAMS, headers=headers)
                for response in (user_response, money_response, devices_response, usage_response):
                    if response.status_code in AUTH_FAILURE_CODES:
                        return {"status": "error", "error_kind": "auth", "error": "authentication rejected"}
                    if response.status_code == 406 and "ip_block" in str(response.headers.get("location") or ""):
                        return {
                            "status": "error",
                            "error_kind": "proxy_blocked",
                            "error": "EarnApp blocked the account proxy",
                        }
                    response.raise_for_status()
                devices = _payload_devices(devices_response.json())
                device_ids = [_device_id(item) for item in devices]
                device_ids = [device_id for device_id in device_ids if device_id]
                statuses: Any = {}
                if device_ids:
                    status_response = await client.post(
                        f"{API_BASE}/device_statuses",
                        params=API_PARAMS,
                        headers=headers,
                        json={"data": {"devices": device_ids}},
                    )
                    if status_response.status_code in AUTH_FAILURE_CODES:
                        return {"status": "error", "error_kind": "auth", "error": "authentication rejected"}
                    status_response.raise_for_status()
                    statuses = status_response.json()
                return normalize_snapshot(
                    user_response.json(),
                    money_response.json(),
                    devices_response.json(),
                    statuses,
                    usage_response.json(),
                ) | {
                    "payment": normalize_payment(
                        payment_methods_response.json() if payment_methods_response.status_code == 200 else {},
                        redeem_details_response.json() if redeem_details_response.status_code == 200 else {},
                        transactions_response.json() if transactions_response.status_code == 200 else [],
                    )
                }
            finally:
                await client.aclose()
        except (httpx.TimeoutException, httpx.NetworkError, httpx.ProxyError):
            return {"status": "error", "error_kind": "route", "error": "proxy unavailable"}
        except httpx.HTTPStatusError as exc:
            kind = base.classify_exception(exc)
            return {
                "status": "error",
                "error_kind": "auth" if kind == base.KIND_AUTH else "route",
                "error": "authentication rejected" if kind == base.KIND_AUTH else "EarnApp route unavailable",
            }
        except (TypeError, ValueError, KeyError):
            return {"status": "error", "error_kind": "shape", "error": "EarnApp API shape changed"}
