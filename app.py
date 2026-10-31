import re
import shutil
import tempfile
from pathlib import Path

import streamlit as st
import yt_dlp

st.set_page_config(page_title="YouTube to MP3", page_icon="🎵", layout="centered")

YT_REGEX = re.compile(
    r"^(https?://)?(www\.|m\.|music\.)?(youtube\.com|youtu\.be)/.+", re.IGNORECASE
)


def convert_to_mp3(url: str, bitrate: str, progress_bar, status_text):
    """Download audio from the URL and convert it to MP3. Returns (bytes, filename)."""
    tmp_dir = Path(tempfile.mkdtemp())

    def hook(d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                pct = d.get("downloaded_bytes", 0) / total
                progress_bar.progress(min(pct, 0.95))
                status_text.text(f"Downloading... {pct * 100:.0f}%")
        elif d["status"] == "finished":
            progress_bar.progress(0.97)
            status_text.text("MP3 mai convert ho raha hai...")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(tmp_dir / "%(title)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [hook],
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": bitrate,
            }
        ],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "audio")

        mp3_files = list(tmp_dir.glob("*.mp3"))
        if not mp3_files:
            raise RuntimeError("MP3 file nahi bani. FFmpeg install hai?")

        mp3_path = mp3_files[0]
        return mp3_path.read_bytes(), mp3_path.name, title
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------- UI ----------------
st.title("🎵 YouTube to MP3")
st.caption("Bas link paste karein aur MP3 download karein.")

url = st.text_input("YouTube link", placeholder="https://www.youtube.com/watch?v=...")
bitrate = st.selectbox("Quality (kbps)", ["128", "192", "256", "320"], index=1)

if "result" not in st.session_state:
    st.session_state.result = None

if st.button("Convert", type="primary", use_container_width=True):
    st.session_state.result = None
    url = url.strip()

    if not url:
        st.warning("Pehle link daalein.")
    elif not YT_REGEX.match(url):
        st.error("Ye valid YouTube link nahi lag raha.")
    else:
        progress_bar = st.progress(0.0)
        status_text = st.empty()
        try:
            status_text.text("Shuru ho raha hai...")
            data, filename, title = convert_to_mp3(url, bitrate, progress_bar, status_text)
            progress_bar.progress(1.0)
            status_text.text("Ho gaya! ✅")
            st.session_state.result = (data, filename, title)
        except Exception as e:
            progress_bar.empty()
            status_text.empty()
            st.error(f"Error: {e}")

if st.session_state.result:
    data, filename, title = st.session_state.result
    st.success(f"Tayyar: {title}")
    st.audio(data, format="audio/mp3")
    st.download_button(
        label="⬇️ MP3 Download karein",
        data=data,
        file_name=filename,
        mime="audio/mpeg",
        use_container_width=True,
    )

st.divider()
st.caption("Sirf wo content download karein jis ka aap ko haq ho ya jo free/licensed ho.")
