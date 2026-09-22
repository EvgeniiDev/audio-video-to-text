from fastapi.testclient import TestClient
from src.app import app

client = TestClient(app)


def test_index_has_url_row():
    html = client.get("/").text
    assert 'id="urlrow"' in html
    assert "/fetch" in html
