from app.collectors import traffmonetizer


def test_collector_uses_the_api_host_published_by_the_current_dashboard_bundle():
    assert traffmonetizer.API_BASE == "https://data.traffmonetizer.com/api"
