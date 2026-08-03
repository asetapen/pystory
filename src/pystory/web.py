import argparse
import json
import logging
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from pystory.config import Config

log = logging.getLogger("pystory.web")

CAPTURE_RE = re.compile(r"^(screenshot|webcam)_(\d{8})_(\d{6})\.jpg$")
DAY_RE = re.compile(r"^\d{8}$")


def list_days(storage_dir: Path) -> list[str]:
    """Distinct capture days (YYYYMMDD) present in storage_dir, newest first."""
    days = set()
    for f in storage_dir.glob("*.jpg"):
        m = CAPTURE_RE.match(f.name)
        if m:
            days.add(m.group(2))
    return sorted(days, reverse=True)


def list_ticks_for_day(storage_dir: Path, day: str) -> list[dict]:
    """Capture ticks for a day, sorted by time. Each tick pairs the screenshot
    and webcam filenames that share a timestamp (a tick can be missing either
    if that capture failed)."""
    ticks: dict[str, dict] = {}
    for f in storage_dir.glob(f"*_{day}_*.jpg"):
        m = CAPTURE_RE.match(f.name)
        if not m or m.group(2) != day:
            continue
        kind, _, hhmmss = m.groups()
        ticks.setdefault(hhmmss, {"time": hhmmss})[kind] = f.name
    return [ticks[t] for t in sorted(ticks)]


def _json_bytes(data) -> bytes:
    return json.dumps(data).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    storage_dir: Path

    def log_message(self, fmt, *args) -> None:
        log.info("%s - %s", self.address_string(), fmt % args)

    def _send_json(self, data, status: int = 200) -> None:
        body = _json_bytes(data)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, body: str, status: int = 200) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_error_json(self, status: int, message: str) -> None:
        self._send_json({"error": message}, status=status)

    def do_GET(self) -> None:  # noqa: N802 (stdlib override)
        path = unquote(urlparse(self.path).path)

        if path == "/":
            self._send_html(INDEX_HTML)
            return

        if path == "/api/days":
            self._send_json({"days": list_days(self.storage_dir)})
            return

        m = re.match(r"^/api/days/(\d{8})$", path)
        if m:
            day = m.group(1)
            if not DAY_RE.match(day):
                self._send_error_json(400, "invalid day")
                return
            self._send_json({"day": day, "ticks": list_ticks_for_day(self.storage_dir, day)})
            return

        m = re.match(r"^/captures/([^/]+)$", path)
        if m:
            filename = m.group(1)
            if not CAPTURE_RE.match(filename):
                self._send_error_json(400, "invalid filename")
                return
            file_path = self.storage_dir / filename
            if not file_path.is_file():
                self._send_error_json(404, "not found")
                return
            data = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        self._send_error_json(404, "not found")


INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>pystory</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #14161a;
    color: #e6e6e6;
    display: flex;
    flex-direction: column;
    height: 100vh;
  }
  header {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 16px;
    border-bottom: 1px solid #2a2d33;
  }
  header h1 { font-size: 15px; font-weight: 600; margin: 0; opacity: 0.7; }
  #day-nav { display: flex; align-items: center; gap: 8px; margin-left: auto; }
  button {
    background: #23262c;
    color: #e6e6e6;
    border: 1px solid #33363c;
    border-radius: 6px;
    padding: 6px 12px;
    cursor: pointer;
    font-size: 14px;
  }
  button:hover:not(:disabled) { background: #2d3038; }
  button:disabled { opacity: 0.35; cursor: default; }
  #day-label { font-size: 15px; font-weight: 600; min-width: 110px; text-align: center; }
  main {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 16px;
    padding: 16px;
    overflow: hidden;
  }
  .frame {
    flex: 1;
    max-width: 47%;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    height: 100%;
  }
  .frame span { font-size: 12px; opacity: 0.5; text-transform: uppercase; letter-spacing: 0.05em; }
  .frame img {
    max-width: 100%;
    max-height: 100%;
    object-fit: contain;
    border-radius: 8px;
    background: #1c1e23;
  }
  .frame .empty {
    color: #555;
    font-size: 13px;
  }
  footer {
    padding: 14px 20px 20px;
    border-top: 1px solid #2a2d33;
  }
  #scrub { width: 100%; }
  #time-row { display: flex; justify-content: space-between; font-size: 13px; opacity: 0.7; margin-top: 6px; }
  #status { text-align: center; padding: 40px; opacity: 0.5; }
</style>
</head>
<body>
<header>
  <h1>pystory</h1>
  <div id="day-nav">
    <button id="prev-day">&lsaquo; prev</button>
    <div id="day-label">&mdash;</div>
    <button id="next-day">next &rsaquo;</button>
  </div>
</header>
<main id="main">
  <div id="status">Loading&hellip;</div>
</main>
<footer id="footer" style="display:none">
  <input type="range" id="scrub" min="0" max="0" value="0" step="1">
  <div id="time-row">
    <span id="time-label">&ndash;</span>
    <span id="tick-count"></span>
  </div>
</footer>
<script>
let days = [];
let dayIndex = 0;
let ticks = [];
let tickIndex = 0;

const mainEl = document.getElementById("main");
const footerEl = document.getElementById("footer");
const statusEl = document.getElementById("status");
const dayLabel = document.getElementById("day-label");
const prevDayBtn = document.getElementById("prev-day");
const nextDayBtn = document.getElementById("next-day");
const scrub = document.getElementById("scrub");
const timeLabel = document.getElementById("time-label");
const tickCount = document.getElementById("tick-count");

function fmtDay(day) {
  return day.slice(0, 4) + "-" + day.slice(4, 6) + "-" + day.slice(6, 8);
}

function fmtTime(hhmmss) {
  return hhmmss.slice(0, 2) + ":" + hhmmss.slice(2, 4) + ":" + hhmmss.slice(4, 6);
}

async function loadDays() {
  const res = await fetch("/api/days");
  const data = await res.json();
  days = data.days;
  if (days.length === 0) {
    statusEl.textContent = "No captures yet.";
    return;
  }
  dayIndex = 0;
  await loadDay();
}

async function loadDay() {
  const day = days[dayIndex];
  dayLabel.textContent = fmtDay(day);
  prevDayBtn.disabled = dayIndex >= days.length - 1;
  nextDayBtn.disabled = dayIndex <= 0;

  const res = await fetch(`/api/days/${day}`);
  const data = await res.json();
  ticks = data.ticks;
  tickIndex = ticks.length - 1;

  if (ticks.length === 0) {
    statusEl.style.display = "block";
    statusEl.textContent = "No captures for this day.";
    footerEl.style.display = "none";
    return;
  }

  statusEl.style.display = "none";
  footerEl.style.display = "block";
  scrub.max = ticks.length - 1;
  scrub.value = tickIndex;
  renderTick();
}

function renderTick() {
  const tick = ticks[tickIndex];
  timeLabel.textContent = fmtTime(tick.time);
  tickCount.textContent = `${tickIndex + 1} / ${ticks.length}`;

  mainEl.innerHTML = "";
  for (const kind of ["screenshot", "webcam"]) {
    const frame = document.createElement("div");
    frame.className = "frame";
    const label = document.createElement("span");
    label.textContent = kind;
    frame.appendChild(label);
    if (tick[kind]) {
      const img = document.createElement("img");
      img.src = `/captures/${tick[kind]}`;
      frame.appendChild(img);
    } else {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "(no capture this tick)";
      frame.appendChild(empty);
    }
    mainEl.appendChild(frame);
  }
}

scrub.addEventListener("input", () => {
  tickIndex = Number(scrub.value);
  renderTick();
});

prevDayBtn.addEventListener("click", () => {
  if (dayIndex < days.length - 1) {
    dayIndex++;
    loadDay();
  }
});

nextDayBtn.addEventListener("click", () => {
  if (dayIndex > 0) {
    dayIndex--;
    loadDay();
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "ArrowLeft" && tickIndex > 0) {
    tickIndex--;
    scrub.value = tickIndex;
    renderTick();
  } else if (e.key === "ArrowRight" && tickIndex < ticks.length - 1) {
    tickIndex++;
    scrub.value = tickIndex;
    renderTick();
  }
});

loadDays();
</script>
</body>
</html>
"""


def parse_args() -> tuple[Path, str, int]:
    p = argparse.ArgumentParser(description="Browse pystory captures in a web UI")
    p.add_argument("--storage-dir", type=Path, help="Where captures are stored")
    p.add_argument("--host", type=str, default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    p.add_argument("--port", type=int, default=8420, help="Bind port (default: 8420)")
    args = p.parse_args()

    config = Config()
    storage_dir = args.storage_dir or config.storage_dir
    return storage_dir, args.host, args.port


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    storage_dir, host, port = parse_args()

    handler = type("BoundHandler", (Handler,), {"storage_dir": storage_dir})
    server = ThreadingHTTPServer((host, port), handler)
    log.info("Serving %s at http://%s:%d/", storage_dir, host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
