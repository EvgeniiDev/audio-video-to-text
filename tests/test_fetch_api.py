from fastapi.testclient import TestClient
from src.app import app

client = TestClient(app)


def test_fetch_garbage_rejected():
    r = client.post("/fetch", data={"url": "not a url"})
    assert r.status_code == 400


def test_md_missing_job():
    r = client.get("/jobs/nonexistent/md")
    assert r.status_code == 404
