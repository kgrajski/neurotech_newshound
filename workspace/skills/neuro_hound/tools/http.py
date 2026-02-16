"""Shared HTTP helper with macOS SSL fallback."""
import re
import ssl
import urllib.request

UA = "openclaw-neuro-hound/1.0"

try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CTX = ssl.create_default_context()
    try:
        SSL_CTX.load_default_certs()
    except Exception:
        SSL_CTX.check_hostname = False
        SSL_CTX.verify_mode = ssl.CERT_NONE


def http_get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
        return resp.read()


def safe_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())
