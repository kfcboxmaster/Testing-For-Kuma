import allure
import requests


@allure.feature("REST API")
@allure.story("Badges")
@allure.title("Invalid badge id returns valid HTTP response")
def test_badge_invalid_id_returns_valid_response(base_url):
    response = requests.get(f"{base_url}/api/badge/999999/status", timeout=10)

    assert response.status_code == 200
    assert "text/html" in response.headers.get("Content-Type", "")