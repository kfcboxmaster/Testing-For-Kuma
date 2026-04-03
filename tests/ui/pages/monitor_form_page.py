from playwright.sync_api import Page


class MonitorFormPage:
    def __init__(self, page: Page, base_url: str):
        self.page = page
        self.base_url = base_url.rstrip("/")

    def navigate_add(self):
        self.page.goto(f"{self.base_url}/add")
        self.page.wait_for_load_state("networkidle")
        self.page.locator("#name").wait_for()

    def navigate_edit(self, monitor_id: int):
        self.page.goto(f"{self.base_url}/edit/{monitor_id}")
        self.page.wait_for_load_state("networkidle")
        self.page.locator("#name").wait_for()

    def select_monitor_type(self, monitor_type: str):
        self.page.get_by_label("Monitor Type").select_option(monitor_type)

    def fill_friendly_name(self, name: str):
        self.page.locator("#name").fill(name)

    def fill_url(self, url: str):
        self.page.locator("#url").fill(url)

    def save(self):
        self.page.locator("#monitor-submit-btn").click()
        self.page.wait_for_load_state("networkidle")

    def monitor_name_in_list(self, name: str) -> bool:
        return self.page.locator(f"text={name}").count() > 0
