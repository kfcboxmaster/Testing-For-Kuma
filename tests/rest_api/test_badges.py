import requests


def test_badge_invalid_id(base_url):
    response = requests.get(f"{base_url}/api/badge/999999/status")
    assert response.status_code in [200, 404]