import yt_dlp
from pathlib import Path


def _base_opts(browser: str | None) -> dict:
    opts: dict = {"quiet": False, "no_warnings": False}
    if browser:
        opts["cookiesfrombrowser"] = (browser, None, None, None)
    return opts


def download(url: str, output_path: Path, browser: str | None) -> dict:
    """Download video to output_path. Returns yt-dlp info dict."""
    ydl_opts = {
        **_base_opts(browser),
        "outtmpl": str(output_path),
        "format": "bestvideo[height<=720][ext=mp4][vcodec!^=av01]+bestaudio[ext=m4a]/bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]/best",
        "merge_output_format": "mp4",
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
    return info


def extract_video_id(url: str, browser: str | None) -> str:
    """Extract video id without downloading."""
    ydl_opts = {
        **_base_opts(browser),
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return info["id"]
