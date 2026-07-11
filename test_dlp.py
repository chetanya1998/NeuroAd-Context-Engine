import sys
import os
from pathlib import Path
sys.path.append(os.path.abspath("apps/api"))

from main import download_youtube_video
try:
    print(download_youtube_video("https://www.youtube.com/watch?v=ntz2c2z54dg", "test_vid"))
except Exception as e:
    print(e)
