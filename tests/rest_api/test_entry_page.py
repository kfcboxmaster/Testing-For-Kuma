import allure
import requests


@allure.feature("REST API")
@allure.story("Entry Page")
@allure.title("Entry page returns 200 and JSON")
def test_entry_page_returns_200_and_json(base_url):
    response = requests.get(f"{base_url}/api/entry-page", timeout=10)

    assert response.status_code == 200
    assert "application/json" in response.headers.get("Content-Type", "")