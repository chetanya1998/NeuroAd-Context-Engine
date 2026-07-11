import sys
import os
import yt_dlp
from pathlib import Path

def test_download(url, use_extractor_args):
    options = {
        "format": "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/bv*[height<=720]+ba/best[height<=720]/best",
        "merge_output_format": "mp4",
        "quiet": False,
        "no_warnings": False,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.youtube.com/",
        },
    }
    if use_extractor_args:
        options["extractor_args"] = {"youtube": {"player_client": ["ios", "android", "web_safari", "web"]}}

    with yt_dlp.YoutubeDL(options) as ydl:
        try:
            ydl.extract_info(url, download=False)
            print("SUCCESS with use_extractor_args=", use_extractor_args)
        except Exception as e:
            print("FAILED with use_extractor_args=", use_extractor_args)
            print("Error:", e)

test_download("https://www.youtube.com/watch?v=ntz2c2z54dg", True)
test_download("https://www.youtube.com/watch?v=ntz2c2z54dg", False)
