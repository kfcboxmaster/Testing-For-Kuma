import allure


@allure.feature("Socket.IO API")
@allure.story("Notifications")
class TestNotifications:

    def test_add_notification(self, auth_sio):
        auth_sio.emit("addNotification", {
            "type": "webhook",
            "name": "Test Notification",
            "webhookURL": "https://example.com"
        })
        result = auth_sio.receive()
        assert result is not None
