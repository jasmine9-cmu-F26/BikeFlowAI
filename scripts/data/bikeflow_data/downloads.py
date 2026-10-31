"""Atomic downloads with source-size and SHA-256 verification."""
from datetime import datetime,timezone
import hashlib,json,time,urllib.request,urllib.error,zipfile
UA="BikeFlowAI-academic-data-audit/1.0"

def utc_now():
    return datetime.now(timezone.utc).isoformat()

def request(url, **kwargs):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), **kwargs)

def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    tmp.replace(path)

def download(url, destination, expected_bytes=None):
    destination.parent.mkdir(parents=True, exist_ok=True)
    sidecar = destination.with_suffix(destination.suffix + ".download.json")
    if destination.exists() and sidecar.exists():
        meta = json.loads(sidecar.read_text())
        size_ok = expected_bytes is None or destination.stat().st_size == expected_bytes
        if meta.get("url") == url and size_ok and sha256(destination) == meta.get("sha256"):
            print(f"Verified cached {destination.name}", flush=True)
            return meta
    temporary = destination.with_suffix(destination.suffix + ".part")
    error = None
    for attempt in range(3):
        try:
            start = time.monotonic()
            with request(url, timeout=120) as response:
                header_length = response.headers.get("Content-Length")
                etag, modified = response.headers.get("ETag"), response.headers.get("Last-Modified")
                with temporary.open("wb") as output:
                    while block := response.read(1024 * 1024):
                        output.write(block)
            actual = temporary.stat().st_size
            for expected in [expected_bytes, int(header_length) if header_length else None]:
                if expected is not None and actual != expected:
                    raise ValueError(f"Size mismatch {destination.name}: {actual} != {expected}")
            if destination.suffix == ".parquet":
                import pyarrow.parquet as pq
                pq.read_metadata(temporary)
            if destination.suffix == ".zip":
                with zipfile.ZipFile(temporary) as archive:
                    if not any(n.endswith(".csv") and not n.startswith("__MACOSX/") for n in archive.namelist()):
                        raise ValueError("No trip CSV in ZIP")
            meta = dict(url=url, bytes=actual, sha256=sha256(temporary), etag=etag,
                        source_last_modified=modified, downloaded_at_utc=utc_now())
            temporary.replace(destination)
            save_json(sidecar, meta)
            print(f"Downloaded {destination.name}: {actual:,} bytes ({time.monotonic()-start:.1f}s)", flush=True)
            return meta
        except (OSError, urllib.error.URLError, ValueError, zipfile.BadZipFile) as exc:
            error = exc
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Download failed after 3 attempts: {url}: {error}")
