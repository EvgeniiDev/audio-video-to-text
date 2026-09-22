from src.engine import Job
from src import pipeline


class FakeEngine:
    def run_job(self, job, wav_path):
        from src.engine import Phrase
        job.status = "transcribing"
        job.total_sec = 10.0
        job.phrases.append(Phrase(0.0, 10.0, "stub text"))
        job.done_sec = 10.0
        job.status = "done"


def test_run_url_job_bad_url(tmp_path):
    job = Job(id="u1", filename="http://nope.invalid/xyz")
    pipeline.run_url_job(job, "http://nope.invalid/xyz", tmp_path, FakeEngine(), make_slides=False)
    assert job.status == "error"
    assert job.error != ""
