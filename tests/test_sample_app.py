from fastapi.testclient import TestClient

from sample_app.main import app


def test_hello_world() -> None:
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert response.text == "hello world"
