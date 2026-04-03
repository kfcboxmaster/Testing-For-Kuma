import allure
from tests.ui.pages.monitor_form_page import MonitorFormPage


@allure.feature("UI")
@allure.story("Monitor Form")
class TestMonitorForm:
    @allure.title("Add an HTTP monitor and verify it appears in the list")
    def test_add_http_monitor(self, logged_in_page, base_url):
        monitor_name = "UI-Add-HTTP-Test"

        form = MonitorFormPage(logged_in_page, base_url)
        form.navigate_add()
        form.fill_friendly_name(monitor_name)
        form.fill_url("https://example.com")
        form.save()

        # Kuma redirects to /dashboard/<id> after saving a new monitor
        logged_in_page.wait_for_load_state("networkidle")
        assert logged_in_page.locator(f"text={monitor_name}").count() > 0

    @allure.title("Edit monitor name and verify updated name appears in list")
    def test_edit_monitor_name(self, logged_in_page, base_url):
        original_name = "UI-Edit-Before"
        updated_name = "UI-Edit-After"

        form = MonitorFormPage(logged_in_page, base_url)
        form.navigate_add()
        form.fill_friendly_name(original_name)
        form.fill_url("https://example.com")
        form.save()

        # After save Kuma lands on the monitor detail page (/dashboard/<id>)
        logged_in_page.wait_for_load_state("networkidle")

        # Edit is a router-link (<a>), not a button — exact=True avoids matching sidebar items
        logged_in_page.get_by_role("link", name="Edit", exact=True).click()
        logged_in_page.wait_for_load_state("networkidle")
        logged_in_page.locator("#name").wait_for()

        logged_in_page.locator("#name").fill("")
        logged_in_page.locator("#name").fill(updated_name)
        logged_in_page.locator("#monitor-submit-btn").click()
        logged_in_page.wait_for_load_state("networkidle")

        assert logged_in_page.locator(f"text={updated_name}").count() > 0
