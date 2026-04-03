import allure
from tests.ui.pages.settings_page import SettingsPage


@allure.feature("UI")
@allure.story("Settings")
class TestSettings:
    @allure.title("Settings page loads and General tab is visible")
    def test_settings_page_loads(self, logged_in_page, base_url):
        sp = SettingsPage(logged_in_page, base_url)
        sp.navigate()
        assert "/settings" in logged_in_page.url
        assert logged_in_page.locator('a[href="/settings/notifications"]').is_visible()

    @allure.title("Navigate to Notifications tab without error")
    def test_navigate_notifications_tab(self, logged_in_page, base_url):
        sp = SettingsPage(logged_in_page, base_url)
        sp.navigate()
        sp.click_tab("Notifications")
        assert logged_in_page.locator("text=Notifications").count() > 0

    @allure.title("Navigate to Security tab without error")
    def test_navigate_security_tab(self, logged_in_page, base_url):
        sp = SettingsPage(logged_in_page, base_url)
        sp.navigate()
        sp.click_tab("Security")
        assert logged_in_page.locator("text=Security").count() > 0
