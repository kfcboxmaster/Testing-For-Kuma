import allure


@allure.feature("Socket.IO API")
@allure.story("Maintenance")
class TestMaintenance:

    def test_get_maintenance_list(self, auth_sio):
        auth_sio.emit("getMaintenanceList")
        result = auth_sio.receive()
        assert result is not None

