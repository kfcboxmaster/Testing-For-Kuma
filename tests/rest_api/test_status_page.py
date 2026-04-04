import requests


def test_status_page_unknown_slug(base_url):
    response = requests.get(f"{base_url}/api/status-page/unknown-slug")
    assert response.status_code in [200, 404]