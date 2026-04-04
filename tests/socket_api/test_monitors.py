import allure


@allure.feature("Socket.IO API")
@allure.story("Monitors")
class TestMonitors:

    def test_get_monitor_list(self, auth_sio):
        auth_sio.emit("getMonitorList")
        result = auth_sio.receive()
        assert result is not None

    def test_add_monitor(self, auth_sio):
        auth_sio.emit("add", {
            "type": "http",
            "name": "Test Monitor",
            "url": "https://example.com",
            "interval": 60
        })
        result = auth_sio.receive()
        assert result is not None
