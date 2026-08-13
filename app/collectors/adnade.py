"""Adnade withdrawable-balance collector."""

from __future__ import annotations

import logging
import re
from html import unescape

import httpx

from app.collectors import base
from app.collectors.base import KIND_AUTH, KIND_SHAPE, BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

BASE_URL = "https://adnade.net"
WITHDRAWAL_URL = f"{BASE_URL}/login.php?page=paid4use&navaction=auszahlung"


def parse_withdrawable_balance(html: str) -> float:
    text = unescape(re.sub(r"<[^>]+>", " ", html))
    text = re.sub(r"\s+", " ", text)
    match = re.search(r"Withdrawable\s+balance:\s*([\d.,]+)\s*EUR", text, re.IGNORECASE)
    if not match:
        raise ValueError("Withdrawable balance field missing")
    return float(match.group(1).replace(",", ""))


class AdnadeCollector(BaseCollector):
    """Collect Adnade withdrawable EUR balance via the account login page."""

    platform = "adnade"

    def __init__(self, username: str, password: str) -> None:
        super().__init__()
        self.username = username
        self.password = password

    async def collect(self) -> EarningsResult:
        try:
            client = self._get_client(follow_redirects=True, timeout=30)
            login_page = await client.get(f"{BASE_URL}/login.php")
            login_page.raise_for_status()
            code = ""
            match = re.search(r'name=["\']Manuell_Code["\'][^>]*value=["\']([^"\']+)', login_page.text)
            if match:
                code = match.group(1)

            login = await client.post(
                f"{BASE_URL}/login.php",
                data={
                    "action": "",
                    "step": "2",
                    "Manuell_Code": code,
                    "navaction": "login",
                    "UserID": self.username,
                    "Passwort": self.password,
                },
            )
            if login.status_code in (401, 403) or "navaction=login" in str(login.url) or "Account Dashboard" not in login.text:
                return EarningsResult(
                    platform=self.platform,
                    balance=0.0,
                    currency="EUR",
                    error="Authentication failed - check Adnade username/password",
                    error_kind=KIND_AUTH,
                )

            payout = await client.get(WITHDRAWAL_URL)
            payout.raise_for_status()
            balance = parse_withdrawable_balance(payout.text)
            return EarningsResult(platform=self.platform, balance=round(balance, 4), currency="EUR")
        except ValueError as exc:
            return EarningsResult(platform=self.platform, balance=0.0, currency="EUR", error=str(exc), error_kind=KIND_SHAPE)
        except Exception as exc:
            base.log_failure(logger, "Adnade", exc)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                currency="EUR",
                error=str(exc),
                error_kind=base.classify_exception(exc),
            )
