# tests/test_api.py
import pytest
from fastapi.testclient import TestClient
from main import app
import os

# Устанавливаем env до импорта приложения
os.environ["AUTH_MODE"] = "dev"
os.environ["DATA_DIR"] = "/tmp/rm_test_data"

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

def test_status_endpoint(client):
    response = client.get("/api/generator/status")
    assert response.status_code == 200
    assert "providers" in response.json()

def test_me_endpoint(client):
    response = client.get("/api/me")
    assert response.status_code == 200
    data = response.json()
    assert "authenticated" in data
    assert data["authenticated"] is True

def test_unauthorized_access(client):
    # В режиме oauth доступ к рецептам без куки должен блокироваться
    os.environ["AUTH_MODE"] = "oauth"
    response = client.get("/api/recipes")
    assert response.status_code == 401