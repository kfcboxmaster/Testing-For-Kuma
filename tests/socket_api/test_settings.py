import allure


@allure.feature("Socket.IO API")
@allure.story("Settings")
class TestSettings:

    def test_get_settings(self, auth_sio):
        auth_sio.emit("getSettings")
        result = auth_sio.receive()
        assert result is not None
