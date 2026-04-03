from playwright.sync_api import Page


class StatusPagePage:
    def __init__(self, page: Page, base_url: str):
        self.page = page
        self.base_url = base_url.rstrip("/")

    def navigate_manage(self):
        self.page.goto(f"{self.base_url}/manage-status-page")
        self.page.wait_for_load_state("networkidle")

    def navigate_add(self):
        self.page.goto(f"{self.base_url}/add-status-page")
        self.page.wait_for_load_state("networkidle")
        self.page.locator("#name").wait_for()

    def navigate_public(self, slug: str):
        self.page.goto(f"{self.base_url}/status/{slug}", wait_until="domcontentloaded")
        self.page.wait_for_load_state("networkidle")

    def fill_title(self, title: str):
        self.page.locator("#name").fill(title)

    def fill_slug(self, slug: str):
        self.page.locator("#slug").fill("")
        self.page.locator("#slug").fill(slug)

    def click_next_step(self):
        self.page.locator("#monitor-submit-btn").click()
        self.page.wait_for_load_state("networkidle")

    def save(self):
        self.page.locator('[data-testid="save-button"], button:has-text("Save")').first.click()
        self.page.wait_for_load_state("networkidle")

    def add_monitor_group(self):
        self.page.locator('button:has-text("Add Group")').click()

    def status_page_title(self) -> str:
        return self.page.locator("h1, .status-page-title, [class*='title']").first.inner_text()
