from playwright.sync_api import Page


class SettingsPage:
    def __init__(self, page: Page, base_url: str):
        self.page = page
        self.base_url = base_url.rstrip("/")

    def navigate(self):
        self.page.goto(f"{self.base_url}/settings")
        self.page.wait_for_load_state("networkidle")

    def click_tab(self, tab_name: str):
        key = tab_name.lower().replace(" ", "-")
        self.page.locator(f'a[href="/settings/{key}"]').click()
        self.page.wait_for_load_state("networkidle")

    def set_check_interval(self, seconds: int):
        field = self.page.get_by_label("Check Interval (Every X Seconds)")
        field.fill(str(seconds))

    def save(self):
        self.page.get_by_role("button", name="Save").click()
        self.page.wait_for_load_state("networkidle")

    def get_check_interval_value(self) -> str:
        return self.page.get_by_label("Check Interval (Every X Seconds)").input_value()
