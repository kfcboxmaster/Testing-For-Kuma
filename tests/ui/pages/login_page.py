class LoginPage:
    def __init__(self, page, base_url: str):
        self.page = page
        self.base_url = base_url.rstrip("/")

    def navigate(self):
        self.page.goto(self.base_url)
        self.page.wait_for_load_state("networkidle")

    def login(self, username: str, password: str):
        self.page.get_by_placeholder("Username").fill(username)
        self.page.get_by_placeholder("Password").fill(password)
        self.page.get_by_role("button", name="Log in").click()
        self.page.wait_for_load_state("networkidle")

    def error_message(self) -> str:
        return self.page.locator(".error-message, .alert-danger, [class*='error']").first.inner_text()
