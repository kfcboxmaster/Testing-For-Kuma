import allure

@allure.feature("Smoke Test")
@allure.story("App Availability")
def test_juice_shop_title(driver):
    with allure.step("Open Juice Shop URL"):
        # Use http://localhost:3000 if Jenkins is on the same machine
        driver.get("http://localhost:3000")
        
    with allure.step("Verify Page Title"):
        assert "OWASP Juice Shop" in driver.title