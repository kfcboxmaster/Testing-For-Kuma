from playwright.sync_api import Page


class DashboardPage:
    def __init__(self, page: Page, base_url: str):
        self.page = page
        self.base_url = base_url.rstrip("/")

    def navigate(self):
        self.page.goto(f"{self.base_url}/dashboard")
        self.page.wait_for_load_state("networkidle")

    def add_monitor_button(self):
        return self.page.locator('a[href="/add"]')

    def monitor_list(self):
        return self.page.locator(".monitor-list .item, .monitor-item, [class*='monitor']")

    def monitor_count(self) -> int:
        return self.monitor_list().count()

    def pause_monitor(self, name: str):
        # Pause/Resume are on the detail page — click the monitor to navigate there
        self.page.locator(f"text={name}").first.click()
        self.page.wait_for_load_state("networkidle")
        self.page.get_by_role("button", name="Pause").click()
        # Confirm dialog appears
        self.page.get_by_role("button", name="Yes").click()
        self.page.wait_for_load_state("networkidle")

    def resume_monitor(self, name: str):
        # Already on the detail page after pause
        self.page.get_by_role("button", name="Resume").click()
        self.page.wait_for_load_state("networkidle")
