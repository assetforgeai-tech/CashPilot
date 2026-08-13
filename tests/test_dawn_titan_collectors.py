from __future__ import annotations

from unittest.mock import AsyncMock, patch

from app.collectors.dawn import DawnCollector
from app.collectors.titan import TitanCollector


class _Response:
    def __init__(self, text: str) -> None:
        self.status_code = 200
        self.text = text

    def raise_for_status(self) -> None:
        return None


def test_dawn_parser_and_session_header():
    collector = DawnCollector("sid=abc")
    with patch.object(collector, "_get_client") as get_client:
        client = AsyncMock()
        client.get.return_value = _Response("Log out Total Rewards 4,300 Points Connection Quality Connected")
        get_client.return_value = client
        result = __import__("asyncio").run(collector.collect())
    assert result.platform == "dawn"
    assert result.balance == 4300.0
    assert result.currency == "DAWN"


def test_titan_parser_and_session_header():
    collector = TitanCollector("sid=abc")
    with patch.object(collector, "_get_client") as get_client:
        client = AsyncMock()
        client.get.return_value = _Response("Device Management Connection Status Total Earnings 591.926 TNTIP")
        get_client.return_value = client
        result = __import__("asyncio").run(collector.collect())
    assert result.platform == "titan"
    assert result.balance == 591.926
    assert result.currency == "TNTIP"
