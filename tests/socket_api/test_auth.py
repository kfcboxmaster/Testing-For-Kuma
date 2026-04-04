import allure


@allure.feature("Socket.IO API")
@allure.story("Authentication")
class TestAuth:

    def test_login(self, sio):
        sio.emit("login", {"username": "admin", "password": "admin123"})
        result = sio.receive()
        assert result is not None

    def test_wrong_password(self, sio):
        sio.emit("login", {"username": "admin", "password": "wrong"})
        result = sio.receive()
        assert result is not None

    def test_need_setup(self, sio):
        sio.emit("needSetup")
        result = sio.receive()
        assert result is not None

    def test_logout(self, auth_sio):
        auth_sio.emit("logout")
        result = auth_sio.receive()
        assert result is not None
