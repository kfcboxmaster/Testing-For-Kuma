import pytest
import socketio


@pytest.fixture(scope="session")
def base_url():
    return "http://localhost:3001"


@pytest.fixture
def sio(base_url):
    client = socketio.SimpleClient()
    client.connect(base_url, transports=["websocket"])
    yield client
    try:
        client.disconnect()
    except Exception:
        pass


@pytest.fixture
def auth_sio(sio):
    sio.emit("login", {
        "username": "test",
        "password": "1q2w#E$R"
    })
    sio.receive()
    return sio
