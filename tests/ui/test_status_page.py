import time
import allure
import requests
from tests.ui.pages.status_page_page import StatusPagePage


@allure.feature("UI")
@allure.story("Status Page")
class TestStatusPage:
    @allure.title("Create a status page and verify it exists in the manage list")
    def test_create_status_page(self, logged_in_page, base_url):
        slug = f"ui-test-{int(time.time())}"
        title = "UI Test Status Page"

        sp = StatusPagePage(logged_in_page, base_url)
        sp.navigate_add()
        sp.fill_title(title)
        sp.fill_slug(slug)
        sp.click_next_step()
        sp.save()

        sp.navigate_manage()
        assert logged_in_page.locator(f"text={title}").count() > 0

    @allure.title("Status page with a monitor group is publicly accessible")
    def test_status_page_public_access(self, logged_in_page, base_url):
        slug = f"ui-public-{int(time.time())}"
        title = "UI Public Status Page"

        sp = StatusPagePage(logged_in_page, base_url)
        sp.navigate_add()
        sp.fill_title(title)
        sp.fill_slug(slug)
        sp.click_next_step()
        sp.add_monitor_group()
        sp.save()

        response = requests.get(f"{base_url}/status/{slug}", timeout=10)
        assert response.status_code == 200

    @allure.title("Navigate to the public status page URL in the browser")
    def test_navigate_to_public_status_page(self, logged_in_page, base_url):
        slug = f"ui-nav-{int(time.time())}"
        title = "UI Nav Status Page"

        sp = StatusPagePage(logged_in_page, base_url)
        sp.navigate_add()
        sp.fill_title(title)
        sp.fill_slug(slug)
        sp.click_next_step()
        sp.save()

        sp.navigate_public(slug)
        assert f"/status/{slug}" in logged_in_page.url
