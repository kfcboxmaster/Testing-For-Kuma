import pytest
from tests.ui.pages.login_page import LoginPage

ADMIN_USER = "test"
ADMIN_PASS = "1q2w#E$R"


@pytest.fixture()
def browser_context_args(browser_context_args):
    """Force desktop viewport at context creation so Vue's isMobile starts correct."""
    return {
        **browser_context_args,
        "viewport": {"width": 1280, "height": 800},
    }


@pytest.fixture()
def logged_in_page(page, base_url):
    """Return a Playwright page that has already completed login."""
    lp = LoginPage(page, base_url)
    lp.navigate()
    lp.login(ADMIN_USER, ADMIN_PASS)
    yield page


@pytest.fixture(autouse=True)
def set_timeout(page):
    page.set_default_timeout(5000)
    page.set_default_navigation_timeout(8000)
