import time
from pathlib import Path

from fastapi.testclient import TestClient

import src.app as appmod
from src.app import app

client = TestClient(app)


def _wait_done(jid: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/jobs/{jid}")
        assert r.status_code == 200
        if r.json()["status"] == "done":
            return r.json()
        time.sleep(0.05)
    raise AssertionError(f"job {jid} not done after {timeout}s")


def test_urljob_happy(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "DATA", tmp_path)
    monkeypatch.setattr(appmod, "get_engine", lambda: object())

    def fake(job, url, data_dir, engine=None, **kw):
        d = Path(data_dir) / "vid1"
        (d / "screenshots").mkdir(parents=True)
        (d / "screenshots" / "frame_1.jpg").write_bytes(b"fake")
        (d / "transcript.md").write_text(
            "hello\n\n![](screenshots/frame_1.jpg)\n", encoding="utf-8")
        job.filename = "vid1.mp4"
        job.status = "done"

    monkeypatch.setattr(appmod, "run_url_job", fake)

    r = client.post("/fetch", data={"url": "https://example.com/video"})
    assert r.status_code == 200
    assert "stage" in r.json()
    jid = r.json()["id"]

    _wait_done(jid)

    md = client.get(f"/jobs/{jid}/md")
    assert md.status_code == 200
    assert f"/jobs/{jid}/shots/frame_1.jpg" in md.text

    shot = client.get(f"/jobs/{jid}/shots/frame_1.jpg")
    assert shot.status_code == 200
    assert shot.content == b"fake"

    # Second job writes nothing -> md 404, first job unaffected.
    monkeypatch.setattr(
        appmod, "run_url_job",
        lambda job, url, data_dir, engine=None, **kw: setattr(job, "status", "done"))
    r2 = client.post("/fetch", data={"url": "https://example.com/other"})
    assert r2.status_code == 200
    jid2 = r2.json()["id"]
    assert jid2 != jid

    assert client.get(f"/jobs/{jid2}/md").status_code == 404
    assert client.get(f"/jobs/{jid}/md").status_code == 200
