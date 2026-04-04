import allure
import requests


@allure.feature("REST API")
@allure.story("Status Page")
@allure.title("Unknown status page returns valid response")
def test_status_page_unknown_slug_returns_response(base_url):
    response = requests.get(f"{base_url}/api/status-page/unknown-slug", timeout=10)

    assert response.status_code == 200