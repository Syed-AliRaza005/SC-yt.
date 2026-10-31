import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import streamlit as st
import yt_dlp

st.set_page_config(page_title="YouTube to MP3", page_icon="🎵", layout="wide")

YT_REGEX = re.compile(
    r"^(https?://)?(www\.|m\.|music\.)?(youtube\.com|youtu\.be)/.+", re.IGNORECASE
)
ANSI_REGEX = re.compile(r"\x1b\[[0-9;]*m")
RESULTS_PER_SEARCH = 9
COLUMNS = 3


# ---------------- Helpers ----------------
def fmt_duration(seconds):
    if not seconds:
        return ""
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def shorten(text, limit=70):
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def js_runtime_found() -> bool:
    """YouTube ke liye yt-dlp ko Node.js / Deno jaisa JavaScript runtime chahiye."""
    return any(shutil.which(x) for x in ("deno", "node", "bun", "qjs"))


def ytdlp_version() -> str:
    try:
        return yt_dlp.version.__version__
    except Exception:
        return "unknown"


def explain_error(e):
    """Error ko aasan Roman Urdu mai samjhao. Returns (friendly, raw)."""
    raw = ANSI_REGEX.sub("", str(e)).replace("ERROR: ", "").strip()
    low = raw.lower()
    if "403" in low or "forbidden" in low:
        msg = (
            "YouTube ne download block kar diya (403 Forbidden). Sab se aam hal: left sidebar mai "
            "**🔄 yt-dlp update karein** dabayein, phir app band karke dobara chalayein. "
            "Phir bhi aaye to sidebar mai **Node.js** wali warning dekhein, ya Cookies ka option try karein."
        )
    elif "sign in" in low or "not a bot" in low or "cookies" in low:
        msg = (
            "YouTube login/bot-check maang raha hai. Sidebar mai **Cookies** ke neeche apna browser "
            "(Chrome/Firefox) chun kar dobara try karein."
        )
    elif "ffmpeg" in low or "ffprobe" in low:
        msg = "FFmpeg nahi mila. FFmpeg install karein aur PATH mai add karein, phir app dobara chalayein."
    elif "private" in low or "unavailable" in low or "removed" in low:
        msg = "Ye video private, hata di gayi ya aap ke ilaqe mai available nahi hai."
    elif "name or service not known" in low or "getaddrinfo" in low or "timed out" in low:
        msg = "Internet connection ka masla lag raha hai. Connection check karke dobara try karein."
    else:
        msg = "Download nahi ho saka. Neeche technical detail dekhein."
    return msg, raw


def is_403(e) -> bool:
    low = str(e).lower()
    return "403" in low or "forbidden" in low


def cookie_opts() -> dict:
    """Sidebar ki cookie settings ko yt-dlp options mai badlo."""
    path = st.session_state.get("cookie_file")
    browser = st.session_state.get("cookie_browser", "Koi nahi")
    if path:
        return {"cookiefile": path}
    if browser and browser != "Koi nahi":
        return {"cookiesfrombrowser": (browser.lower(),)}
    return {}


@st.cache_data(ttl=600, show_spinner=False)
def search_youtube(query: str, limit: int = RESULTS_PER_SEARCH):
    """YouTube par search karo aur video ki list (id, title, thumbnail...) wapas do."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)

    results = []
    for e in (info or {}).get("entries", []):
        if not e or not e.get("id"):
            continue
        vid = e["id"]
        results.append(
            {
                "id": vid,
                "title": e.get("title") or "Untitled",
                "channel": e.get("channel") or e.get("uploader") or "",
                "duration": e.get("duration"),
                "thumb": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
                "url": f"https://www.youtube.com/watch?v={vid}",
            }
        )
    return results


def build_opts(tmp_dir: Path, bitrate: str, hook) -> dict:
    return {
        "format": "bestaudio/best",
        "outtmpl": str(tmp_dir / "%(title)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "retries": 5,
        "progress_hooks": [hook],
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": bitrate,
            }
        ],
    }


def convert_to_mp3(url: str, bitrate: str, progress_bar, status_text):
    """Audio download karke MP3 banao. 403 aaye to IPv4 ke saath dobara koshish karta hai."""

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

    attempts = [{}, {"source_address": "0.0.0.0"}]  # 2nd attempt: IPv4 force
    last_error = None

    for n, extra in enumerate(attempts, start=1):
        if n > 1:
            status_text.text("403 aaya, IPv4 ke saath dobara koshish ho rahi hai...")
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            opts = build_opts(tmp_dir, bitrate, hook)
            opts.update(cookie_opts())
            opts.update(extra)
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get("title", "audio")

            mp3_files = list(tmp_dir.glob("*.mp3"))
            if not mp3_files:
                raise RuntimeError("MP3 file nahi bani. FFmpeg install hai?")
            return mp3_files[0].read_bytes(), mp3_files[0].name, title
        except Exception as e:
            last_error = e
            if not is_403(e):
                break
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    raise last_error


def run_conversion(url: str, bitrate: str, area):
    """Convert karo, progress `area` mai dikhao, result session_state mai rakho."""
    st.session_state.result = None
    with area:
        bar = st.progress(0.0)
        status = st.empty()
        try:
            status.text("Shuru ho raha hai...")
            data, filename, title = convert_to_mp3(url, bitrate, bar, status)
            st.session_state.result = (data, filename, title)
        except Exception as e:
            friendly, raw = explain_error(e)
            st.error(friendly)
            with st.expander("Technical detail"):
                st.code(raw)
        finally:
            bar.empty()
            status.empty()


# ---------------- State ----------------
st.session_state.setdefault("result", None)
st.session_state.setdefault("results", None)
st.session_state.setdefault("last_query", "")
st.session_state.setdefault("cookie_file", None)

# ---------------- Sidebar ----------------
with st.sidebar:
    st.header("⚙️ Madad / Settings")
    st.caption(f"yt-dlp version: **{ytdlp_version()}**")

    if not js_runtime_found():
        st.warning(
            "**Node.js ya Deno nahi mila.** YouTube ab download se pehle ek JavaScript challenge "
            "solve karwata hai, is ke bina 403 error aa sakta hai. https://nodejs.org se Node.js "
            "install karein, phir app dobara chalayein."
        )
    else:
        st.caption("✅ JavaScript runtime mojood hai")

    if st.button("🔄 yt-dlp update karein", width="stretch"):
        with st.spinner("Update ho raha hai..."):
            proc = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-U", "--pre", "yt-dlp[default]"],
                capture_output=True,
                text=True,
            )
        if proc.returncode == 0:
            st.success(
                "Update ho gaya! Ab terminal mai **Ctrl+C** dabayein aur "
                "`streamlit run app.py` dobara chalayein."
            )
        else:
            st.error("Update nahi ho saka:")
            st.code((proc.stderr or proc.stdout)[-500:])

    with st.expander("🍪 Cookies (403 / Sign-in error ho to)"):
        st.caption(
            "Ye sirf aap ke apne computer par use hote hain. Jab tak zaroorat na ho, band rakhein."
        )
        st.selectbox(
            "Browser se cookies lein",
            ["Koi nahi", "Chrome", "Firefox", "Edge", "Brave"],
            key="cookie_browser",
        )
        up = st.file_uploader("ya cookies.txt upload karein", type=["txt"])
        if up is not None:
            cpath = Path(tempfile.gettempdir()) / "yt_cookies.txt"
            cpath.write_bytes(up.getvalue())
            st.session_state.cookie_file = str(cpath)
        else:
            st.session_state.cookie_file = None

# ---------------- Main UI ----------------
st.title("🎵 YouTube to MP3")
st.caption("Link paste karein ya gaane ka naam search karein, phir MP3 download karein.")

bitrate = st.selectbox("Quality (kbps)", ["128", "192", "256", "320"], index=1)

# Progress aur final result yahan dikhenge (tabs ke upar), chahe kahin se bhi convert ho.
output_area = st.container()

tab_link, tab_search = st.tabs(["🔗 Link se", "🔍 Naam se search"])

# ---- Tab 1: Link ----
with tab_link:
    url = st.text_input("YouTube link", placeholder="https://www.youtube.com/watch?v=...")
    if st.button("Convert", type="primary", width="stretch", key="convert_link"):
        url = url.strip()
        if not url:
            st.warning("Pehle link daalein.")
        elif not YT_REGEX.match(url):
            st.error("Ye valid YouTube link nahi lag raha.")
        else:
            run_conversion(url, bitrate, output_area)

# ---- Tab 2: Search ----
with tab_search:
    with st.form("search_form", border=False):
        c1, c2 = st.columns([5, 1], vertical_alignment="bottom")
        query = c1.text_input(
            "Gaane ka naam ya artist", placeholder="e.g. Tajdar e Haram Atif Aslam"
        )
        submitted = c2.form_submit_button("🔍 Search", type="primary", width="stretch")

    if submitted:
        if not query.strip():
            st.warning("Pehle kuch likhein.")
        else:
            try:
                with st.spinner("Search ho raha hai..."):
                    st.session_state.results = search_youtube(query.strip())
                    st.session_state.last_query = query.strip()
            except Exception as e:
                st.session_state.results = None
                friendly, raw = explain_error(e)
                st.error(f"Search nahi ho saka. {friendly}")
                with st.expander("Technical detail"):
                    st.code(raw)

    results = st.session_state.results
    if results is not None:
        if not results:
            st.info("Koi result nahi mila. Kisi aur naam se try karein.")
        else:
            st.caption(f"“{st.session_state.last_query}” ke results — jo chahiye us par click karein")
            for i in range(0, len(results), COLUMNS):
                cols = st.columns(COLUMNS)
                for col, r in zip(cols, results[i : i + COLUMNS]):
                    with col, st.container(border=True):
                        st.image(r["thumb"], width="stretch")
                        st.markdown(f"**{shorten(r['title'])}**")
                        meta = " • ".join(
                            x for x in [r["channel"], fmt_duration(r["duration"])] if x
                        )
                        st.caption(meta)
                        if st.button("⬇️ MP3 banayein", key=f"dl_{r['id']}", width="stretch"):
                            run_conversion(r["url"], bitrate, output_area)

# ---- Result (upar output_area mai) ----
with output_area:
    if st.session_state.result:
        data, filename, title = st.session_state.result
        st.success(f"Tayyar: {title}")
        st.audio(data, format="audio/mp3")
        st.download_button(
            label="⬇️ MP3 Download karein",
            data=data,
            file_name=filename,
            mime="audio/mpeg",
            width="stretch",
            type="primary",
        )

st.divider()
st.caption("Sirf wo content download karein jis ka aap ko haq ho ya jo free/licensed ho.")
