import sys
import os
from pathlib import Path
sys.path.append(os.path.abspath("apps/api"))
from main import download_youtube_video
import yt_dlp
print(yt_dlp.version.__version__)
