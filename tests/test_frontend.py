from fastapi.testclient import TestClient
from src.app import app

client = TestClient(app)


def test_index_has_url_row():
    html = client.get("/").text
    assert 'id="urlrow"' in html
    assert "/fetch" in html


def test_upload_feedback():
    import shutil
    import subprocess
    from pathlib import Path
    import pytest

    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for frontend behavior tests")
    result = subprocess.run(
        [node, "--test", str(Path(__file__).with_name("test_frontend_upload.cjs"))],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
