import requests


def test_entry_page(base_url):
    response = requests.get(f"{base_url}/api/entry-page")
    assert response.status_code == 200