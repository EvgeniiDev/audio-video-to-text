import threading

import pytest
from fastapi.testclient import TestClient

import src.app as appmod
from src.engine import Job, Phrase


@pytest.fixture
def history(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, 'DATA', tmp_path)
    monkeypatch.setattr(appmod, 'jobs', {})
    monkeypatch.setattr(appmod, 'workers', {})
    return TestClient(appmod.app), tmp_path


@pytest.mark.parametrize('status', ['done', 'error'])
def test_delete_removes_history_and_only_its_files(history, status):
    client, data = history
    jid, other = '1234abcd', '5678abcd'
    appmod.jobs[jid] = Job(id=jid, filename='lecture.mp4', status=status,
                          phrases=[Phrase(0, 1, 'hello')])
    appmod.jobs[other] = Job(id=other, filename='other.mp3', status='done')
    upload = data / f'{jid}.mp4'
    upload.write_bytes(b'video')
    result = data / jid / 'video' / 'screenshots'
    result.mkdir(parents=True)
    (result / 'frame.jpg').write_bytes(b'jpg')
    (result.parent / 'transcript.md').write_text('hello')
    unrelated = data / f'{other}.mp3'
    unrelated.write_bytes(b'keep')
    assert client.delete(f'/jobs/{jid}').status_code == 204
    assert client.get('/jobs').json() == [appmod.job_info(appmod.jobs[other])]
    for suffix in ['', '/text', '/srt', '/vtt', '/md', '/shots/frame.jpg']:
        assert client.get(f'/jobs/{jid}{suffix}').status_code == 404
    assert not upload.exists()
    assert not (data / jid).exists()
    assert unrelated.read_bytes() == b'keep'
    assert client.delete(f'/jobs/{jid}').status_code == 404


@pytest.mark.parametrize('status', ['queued', 'downloading', 'decoding', 'transcribing', 'slides'])
def test_delete_rejects_active_job(history, status):
    client, data = history
    jid = '1234abcd'
    appmod.jobs[jid] = Job(id=jid, filename='a.mp3', status=status)
    upload = data / f'{jid}.mp3'
    upload.write_bytes(b'keep')
    assert client.delete(f'/jobs/{jid}').status_code == 409
    assert jid in appmod.jobs
    assert upload.exists()


def test_delete_rejects_done_status_while_url_worker_is_still_writing(history):
    client, _ = history
    jid = '1234abcd'
    appmod.jobs[jid] = Job(id=jid, filename='a.mp3', status='done')
    stop = threading.Event()
    thread = threading.Thread(target=stop.wait)
    appmod.workers[jid] = thread
    thread.start()
    try:
        assert client.delete(f'/jobs/{jid}').status_code == 409
        assert jid in appmod.jobs
    finally:
        stop.set()
        thread.join()
    assert client.delete(f'/jobs/{jid}').status_code == 204
    assert jid not in appmod.workers


def test_delete_filesystem_failure_keeps_history_for_retry(history, monkeypatch):
    client, data = history
    jid = '1234abcd'
    appmod.jobs[jid] = Job(id=jid, filename='a.mp3', status='done')
    (data / jid).mkdir()
    import shutil
    def fail(*args, **kwargs):
        raise PermissionError('denied')
    monkeypatch.setattr(shutil, 'rmtree', fail)
    assert client.delete(f'/jobs/{jid}').status_code == 500
    assert jid in appmod.jobs


def test_delete_unknown_job(history):
    client, _ = history
    assert client.delete('/jobs/nonexistent').status_code == 404


def test_url_worker_tracking_prevents_early_deletion_and_cleans_up(history, monkeypatch):
    client, _ = history
    stop = threading.Event()
    ready = threading.Event()
    def fake(job, *args, **kwargs):
        job.status = 'done'
        ready.set()
        stop.wait(5)
    monkeypatch.setattr(appmod, 'get_engine', lambda: object())
    monkeypatch.setattr(appmod, 'run_url_job', fake)
    response = client.post('/fetch', data={'url': 'https://example.com/video'})
    jid = response.json()['id']
    assert ready.wait(5)
    thread = appmod.workers[jid]
    try:
        assert client.delete(f'/jobs/{jid}').status_code == 409
    finally:
        stop.set()
        thread.join(5)
    assert not thread.is_alive()
    assert jid not in appmod.workers
    assert client.delete(f'/jobs/{jid}').status_code == 204
