import pytest

from server.ingest.youtube_url import InvalidYouTubeUrl, parse_youtube_url

VID = "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "url",
    [
        f"https://www.youtube.com/watch?v={VID}",
        f"http://youtube.com/watch?v={VID}",
        f"https://m.youtube.com/watch?v={VID}&t=10s&list=PLx",
        f"https://youtu.be/{VID}",
        f"https://youtu.be/{VID}?si=abc",
        f"https://www.youtube.com/shorts/{VID}",
        f"https://www.youtube.com/embed/{VID}",
        f"https://www.youtube.com/live/{VID}",
        f"  HTTPS://WWW.YouTube.com/watch?v={VID}  ",
    ],
)
def test_accepts_and_normalizes(url):
    parsed = parse_youtube_url(url)
    assert parsed.video_id == VID
    assert parsed.canonical_url == f"https://www.youtube.com/watch?v={VID}"


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not a url",
        VID,
        f"ftp://www.youtube.com/watch?v={VID}",
        f"file:///etc/passwd?v={VID}",
        f"/tmp/video.mp4",
        f"https://evil.example/watch?v={VID}",
        f"https://www.youtube.com.evil.example/watch?v={VID}",
        f"https://evilyoutube.com/watch?v={VID}",
        f"https://127.0.0.1/watch?v={VID}",
        f"https://192.168.0.10/watch?v={VID}",
        f"https://[::1]/watch?v={VID}",
        f"https://localhost/watch?v={VID}",
        f"https://www.youtube.com@evil.example/watch?v={VID}",
        f"https://user:pw@www.youtube.com/watch?v={VID}",
        f"https://www.youtube.com:8443/watch?v={VID}",
        f"https://www.youtube.com/redirect?q=https://evil.example&v={VID}",
        f"https://www.youtube.com/watch?v={VID}&v=AAAAAAAAAAA",
        "https://www.youtube.com/watch?v=short",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ; rm -rf",
        "https://www.youtube.com/watch?v=dQw4w9WgX$Q",
        "https://www.youtube.com/watch",
        f"https://youtu.be/{VID}/extra",
        f"https://www.youtube.com/watch?v={VID}\nHost: evil",
        "https://www.youtube.com/watch?v=" + "a" * 3000,
    ],
)
def test_rejects(url):
    with pytest.raises(InvalidYouTubeUrl):
        parse_youtube_url(url)
