import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.collectors.adnade import AdnadeCollector, parse_withdrawable_balance
from app.collectors.base import KIND_AUTH, KIND_SHAPE


def _response(text: str, status: int = 200, url: str = "https://adnade.net/login.php"):
    resp = MagicMock()
    resp.text = text
    resp.status_code = status
    resp.url = url
    resp.raise_for_status = MagicMock()
    return resp


def _collect(responses):
    client = MagicMock()
    client.is_closed = False
    client.aclose = AsyncMock()
    client.get = AsyncMock(return_value=_response("<input name='Manuell_Code' value='ABC123'>"))
    client.post = AsyncMock(return_value=responses[0])
    client.get.side_effect = [_response("<input name='Manuell_Code' value='ABC123'>"), *responses[1:]]
    with patch("app.collectors.adnade.httpx.AsyncClient", return_value=client):
        return asyncio.run(AdnadeCollector(username="kalinh", password="pw").collect())


def test_adnade_collector_logs_in_and_reads_withdrawable_balance():
    html = """
    Account Dashboard
    <a href="login.php?page=account&navaction=links">Surfbar and PTP</a>
    Withdrawable balance: 4.44 EUR
    """
    result = _collect([_response("Account Dashboard"), _response(html)])
    assert result.error is None
    assert result.balance == 4.44
    assert result.currency == "EUR"


def test_adnade_balance_parser_handles_markup_between_label_and_amount():
    html = "<td>Withdrawable balance:</td><td><strong>4.44</strong> EUR</td>"
    assert parse_withdrawable_balance(html) == 4.44


def test_adnade_collector_marks_login_redirect_as_auth_failure():
    result = _collect([_response("Login", url="https://adnade.net/login.php")])
    assert result.error_kind == KIND_AUTH


def test_adnade_collector_marks_missing_balance_as_shape_failure():
    result = _collect([_response("Account Dashboard"), _response("Withdrawal page changed")])
    assert result.error_kind == KIND_SHAPE
