import json

from src.renderer import render
from src.workdir import WorkDir


def test_workdir_layout(tmp_path):
    wd = WorkDir("abc123", base=str(tmp_path))
    assert wd.video.name == "video.mp4"
    assert wd.transcript_md.name == "transcript.md"
    assert wd.frames_dir.is_dir() and wd.screenshots_dir.is_dir()


def test_render_empty_segments(tmp_path):
    jl = tmp_path / "t.jsonl"
    jl.write_text("")
    out = tmp_path / "transcript.md"
    shots = tmp_path / "shots"
    shots.mkdir()
    render(jl, shots, out)
    assert out.read_text() == ""


def test_render_segment_with_shot(tmp_path):
    jl = tmp_path / "t.jsonl"
    jl.write_text(json.dumps({"start": 0.0, "end": 10.0, "text": "hello world"}) + "\n")
    shots = tmp_path / "shots"
    shots.mkdir()
    (shots / "frame_5000.jpg").write_bytes(b"fake")
    out = tmp_path / "transcript.md"
    render(jl, shots, out)
    text = out.read_text()
    assert "hello" in text and "world" in text
    assert "frame_5000.jpg" in text
