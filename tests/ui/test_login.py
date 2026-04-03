import allure
import pytest
from tests.ui.pages.login_page import LoginPage


@allure.feature("UI")
@allure.story("Login")
class TestLogin:
    @allure.title("Valid credentials redirect to dashboard")
    def test_valid_login(self, page, base_url):
        lp = LoginPage(page, base_url)
        lp.navigate()
        lp.login("admin", "admin123")
        assert "/dashboard" in page.url

    @allure.title("Wrong password shows an error message")
    def test_wrong_password_shows_error(self, page, base_url):
        lp = LoginPage(page, base_url)
        lp.navigate()
        lp.login("admin", "wrongpassword")
        error = lp.error_message()
        assert error.strip() != ""

    @allure.title("Empty fields are blocked by HTML5 validation")
    def test_empty_fields_blocked(self, page, base_url):
        page.context.clear_cookies()
        lp = LoginPage(page, base_url)
        lp.navigate()
        page.get_by_role("button", name="Log in").click()
        assert page.get_by_placeholder("Username").is_visible()
