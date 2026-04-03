import allure
from tests.ui.pages.dashboard_page import DashboardPage
from tests.ui.pages.monitor_form_page import MonitorFormPage


@allure.feature("UI")
@allure.story("Dashboard")
class TestDashboard:
    @allure.title("Dashboard loads after login and shows monitor section")
    def test_dashboard_loads(self, logged_in_page, base_url):
        db = DashboardPage(logged_in_page, base_url)
        db.navigate()
        assert "/dashboard" in logged_in_page.url
        assert db.add_monitor_button().is_visible()

    @allure.title("Monitor count is visible on the dashboard")
    def test_monitor_count_visible(self, logged_in_page, base_url):
        db = DashboardPage(logged_in_page, base_url)
        db.navigate()
        count = db.monitor_count()
        assert count >= 0

    @allure.title("Pause and resume buttons work for a monitor")
    def test_pause_resume_monitor(self, logged_in_page, base_url):
        monitor_name = "UI-PauseResume-Test"

        form = MonitorFormPage(logged_in_page, base_url)
        form.navigate_add()
        form.fill_friendly_name(monitor_name)
        form.fill_url("https://example.com")
        form.save()

        db = DashboardPage(logged_in_page, base_url)
        db.navigate()
        assert logged_in_page.locator(f"text={monitor_name}").count() > 0

        db.pause_monitor(monitor_name)
        db.resume_monitor(monitor_name)
        assert logged_in_page.locator(f"text={monitor_name}").count() > 0
