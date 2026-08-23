#!/usr/bin/env python3
"""Dependency-free local web dashboard for PADD and Raspberry Pi telemetry."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import ssl
import subprocess
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import __version__


STATIC_DIR = Path(__file__).with_name("static")
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}


def nested(data: Any, path: str, default: Any = None) -> Any:
    """Return a dotted path from dictionaries/lists without raising."""
    current = data
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.strip("[]").isdigit():
            index = int(part.strip("[]"))
            if index >= len(current):
                return default
            current = current[index]
        else:
            return default
    return current


def number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def integer(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def run_command(*command: str, timeout: float = 1.5) -> str | None:
    if not shutil.which(command[0]):
        return None
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def read_text(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None


def local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 80))
        return str(sock.getsockname()[0])
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def memory_percent() -> float:
    meminfo = read_text("/proc/meminfo")
    if not meminfo:
        return 0.0
    values: dict[str, int] = {}
    for line in meminfo.splitlines():
        key, _, raw = line.partition(":")
        try:
            values[key] = int(raw.strip().split()[0])
        except (IndexError, ValueError):
            continue
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", values.get("MemFree", 0))
    return round((total - available) / total * 100, 1) if total else 0.0


def cpu_temperature() -> float | None:
    raw = read_text("/sys/class/thermal/thermal_zone0/temp")
    if raw:
        value = number(raw, -1)
        if value >= 0:
            return round(value / 1000 if value > 1000 else value, 1)
    measured = run_command("vcgencmd", "measure_temp")
    if measured and "=" in measured:
        return number(measured.split("=", 1)[1].split("'", 1)[0], -1)
    return None


def power_telemetry() -> dict[str, Any]:
    output = run_command("vcgencmd", "get_throttled")
    voltage_output = run_command("vcgencmd", "measure_volts", "core")
    voltage = None
    if voltage_output and "=" in voltage_output:
        voltage = voltage_output.split("=", 1)[1]
    if not output or not output.startswith("throttled=0x"):
        return {"state": "unavailable", "label": "N/A", "flags": None, "vcore": voltage}
    try:
        flags = int(output.split("=", 1)[1], 16)
    except ValueError:
        return {"state": "critical", "label": "READ ERR", "flags": None, "vcore": voltage}
    if flags & 0x5 == 0x5:
        state, label = "critical", "UV + throttled"
    elif flags & 0x1:
        state, label = "critical", "Undervoltage"
    elif flags & 0x4:
        state, label = "critical", "Throttled"
    elif flags & 0x2:
        state, label = "warning", "Frequency capped"
    elif flags & 0x8:
        state, label = "warning", "Temperature limit"
    elif flags & 0xF0000:
        state, label = "warning", "Historical event"
    else:
        state, label = "good", "Stable"
    return {"state": state, "label": label, "flags": f"0x{flags:x}", "vcore": voltage}


def ups_telemetry() -> dict[str, Any]:
    low = run_command("i2cget", "-y", "1", "0x17", "0x13", "b")
    high = run_command("i2cget", "-y", "1", "0x17", "0x14", "b")
    try:
        if low is None or high is None:
            raise ValueError
        percent = (int(high, 16) << 8) | int(low, 16)
        if not 0 <= percent <= 100:
            raise ValueError
    except ValueError:
        return {"state": "unavailable", "percent": None, "label": "N/A"}
    state = "good" if percent >= 50 else "warning" if percent >= 25 else "critical"
    return {"state": state, "percent": percent, "label": f"{percent}%"}


class PiHoleClient:
    def __init__(self, base_url: str, password: str | None = None, totp: str | None = None):
        self.base_url = base_url.rstrip("/") + "/"
        self.password = password or self._local_password()
        self.totp = totp
        self.sid: str | None = None
        self.context = ssl._create_unverified_context()

    @staticmethod
    def _local_password() -> str | None:
        return read_text("/etc/pihole/cli_pw")

    def _request(self, endpoint: str, method: str = "GET", payload: dict[str, Any] | None = None) -> Any:
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {"Accept": "application/json", "User-Agent": f"PADD-Web/{__version__}"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if self.sid:
            headers["sid"] = self.sid
        request = Request(self.base_url + endpoint.lstrip("/"), data=data, headers=headers, method=method)
        with urlopen(request, timeout=2.5, context=self.context) as response:
            return json.loads(response.read().decode("utf-8"))

    def authenticate(self) -> None:
        if not self.password:
            raise PermissionError("Pi-hole requires authentication; set PADDWEB_PASSWORD")
        response = self._request("auth", "POST", {"password": self.password, "totp": self.totp})
        if not nested(response, "session.valid", False):
            raise PermissionError(nested(response, "session.message", "Pi-hole authentication failed"))
        self.sid = nested(response, "session.sid")

    def padd(self) -> dict[str, Any]:
        try:
            return self._request("padd")
        except HTTPError as error:
            if error.code != HTTPStatus.UNAUTHORIZED:
                raise
        self.authenticate()
        return self._request("padd")


def demo_padd_data() -> dict[str, Any]:
    return {
        "active_clients": 18,
        "blocking": "enabled",
        "gravity_size": 184235,
        "queries": {"total": 43821, "blocked": 9734, "percent_blocked": 22.2},
        "cache": {"size": 10000, "inserted": 4821, "evicted": 12},
        "recent_blocked": "telemetry.example.net",
        "top_blocked": "ads.example.org",
        "top_domain": "api.raspberrypi.com",
        "top_client": "livingroom.lan",
        "system": {
            "uptime": 387421,
            "cpu": {"nprocs": 4, "load": {"raw": [0.19, 0.24, 0.31], "percent": [11.0]}},
            "memory": {"ram": {"%used": 38.4}},
        },
        "sensors": {"cpu_temp": 48.6, "unit": "C"},
        "host_model": "Raspberry Pi 5 Model B Rev 1.0",
        "node_name": "pihole",
        "iface": {
            "v4": {"name": "eth0", "addr": "192.168.1.53", "num_addrs": 1,
                   "tx_bytes": {"value": 684.2, "unit": "MB"}, "rx_bytes": {"value": 1.8, "unit": "GB"}},
            "v6": {"addr": "fe80::53", "num_addrs": 1},
        },
        "config": {"privacy_level": 0, "dns_port": 53, "dns_dnssec": True,
                   "dhcp_active": False, "dns_num_upstreams": 2},
        "%cpu": 0.8, "%mem": 1.6, "pid": 912,
        "versions": {"core": {"local": {"version": "v6.1"}}, "ftl": {"local": {"version": "v6.2"}},
                     "web": {"local": {"version": "v6.1"}}},
    }


class DashboardCollector:
    def __init__(self, client: PiHoleClient | None, demo: bool = False):
        self.client = client
        self.demo = demo

    def collect(self) -> dict[str, Any]:
        error: str | None = None
        try:
            raw = demo_padd_data() if self.demo else (self.client.padd() if self.client else {})
            connected = bool(raw)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, PermissionError) as exc:
            raw, connected, error = {}, False, str(exc)

        temperature = nested(raw, "sensors.cpu_temp")
        if temperature is None:
            temperature = cpu_temperature()
        loads = nested(raw, "system.cpu.load.raw", []) or []
        if not loads:
            try:
                loads = list(os.getloadavg())
            except (AttributeError, OSError):
                loads = [0, 0, 0]
        core_count = integer(nested(raw, "system.cpu.nprocs"), os.cpu_count() or 1)
        cpu = number(nested(raw, "system.cpu.load.percent.0"))
        if not cpu and loads:
            cpu = min(100.0, number(loads[0]) / max(core_count, 1) * 100)
        memory = number(nested(raw, "system.memory.ram.%used"), memory_percent())
        power = power_telemetry()
        ups = ups_telemetry()
        if self.demo:
            power = {"state": "good", "label": "Stable", "flags": "0x0", "vcore": "0.8500V"}
            ups = {"state": "good", "percent": 83, "label": "83%"}

        blocking_value = nested(raw, "blocking")
        blocking = blocking_value in (True, "enabled", "true", 1)
        dns_active = integer(nested(raw, "config.dns_port"), 53) != 0
        status_state, status_label = self._status(connected, blocking, dns_active, temperature, power)
        privacy = integer(nested(raw, "config.privacy_level"))
        hidden = "Hidden by privacy level"
        recent = hidden if privacy >= 1 else nested(raw, "recent_blocked", "—")
        top_blocked = hidden if privacy >= 1 else nested(raw, "top_blocked", "—")
        top_domain = hidden if privacy >= 1 else nested(raw, "top_domain", "—")
        top_client = hidden if privacy >= 2 else nested(raw, "top_client", "—")

        return {
            "meta": {"version": __version__, "generated_at": int(time.time()), "demo": self.demo,
                     "source": "Pi-hole v6 /api/padd", "error": error},
            "status": {"state": status_state, "label": status_label, "connected": connected,
                       "blocking": blocking, "dns_active": dns_active},
            "summary": {"queries": integer(nested(raw, "queries.total")),
                        "blocked": integer(nested(raw, "queries.blocked")),
                        "blocked_percent": round(number(nested(raw, "queries.percent_blocked")), 1),
                        "domains": integer(nested(raw, "gravity_size")),
                        "clients": integer(nested(raw, "active_clients"))},
            "system": {"hostname": nested(raw, "node_name", socket.gethostname()),
                       "model": nested(raw, "host_model", platform.machine() or "Unknown device"),
                       "uptime": integer(nested(raw, "system.uptime"), self._local_uptime()),
                       "temperature": temperature, "temperature_unit": nested(raw, "sensors.unit", "C"),
                       "cpu_percent": round(cpu, 1), "memory_percent": round(memory, 1),
                       "loads": [round(number(item), 2) for item in list(loads)[:3]], "cores": core_count,
                       "ftl_cpu": round(number(nested(raw, "%cpu")), 1),
                       "ftl_memory": round(number(nested(raw, "%mem")), 1)},
            "network": {"interface": nested(raw, "iface.v4.name", "—"),
                        "ipv4": nested(raw, "iface.v4.addr", local_ip()),
                        "ipv6": nested(raw, "iface.v6.addr", "—"),
                        "tx": self._traffic(raw, "tx_bytes"), "rx": self._traffic(raw, "rx_bytes"),
                        "dnssec": bool(nested(raw, "config.dns_dnssec", False)),
                        "dhcp": bool(nested(raw, "config.dhcp_active", False)),
                        "upstreams": integer(nested(raw, "config.dns_num_upstreams"))},
            "hardware": {"power": power, "ups": ups},
            "activity": {"recent_blocked": recent or "—", "top_blocked": top_blocked or "—",
                         "top_domain": top_domain or "—", "top_client": top_client or "—"},
            "cache": {"size": integer(nested(raw, "cache.size")),
                      "inserted": integer(nested(raw, "cache.inserted")),
                      "evicted": integer(nested(raw, "cache.evicted"))},
            "versions": {"padd_web": f"v{__version__}",
                         "core": nested(raw, "versions.core.local.version", "—"),
                         "web": nested(raw, "versions.web.local.version", "—"),
                         "ftl": nested(raw, "versions.ftl.local.version", "—")},
        }

    @staticmethod
    def _local_uptime() -> int:
        raw = read_text("/proc/uptime")
        return integer(raw.split()[0]) if raw else 0

    @staticmethod
    def _traffic(raw: dict[str, Any], key: str) -> str:
        value = nested(raw, f"iface.v4.{key}.value")
        unit = nested(raw, f"iface.v4.{key}.unit", "")
        return f"{number(value):.1f} {unit}".strip() if value is not None else "—"

    @staticmethod
    def _status(connected: bool, blocking: bool, dns_active: bool,
                temperature: Any, power: dict[str, Any]) -> tuple[str, str]:
        if number(temperature, -274) > 80:
            return "critical", "System is hot"
        if power["state"] == "critical":
            return "critical", power["label"]
        if connected and not dns_active:
            return "critical", "DNS is offline"
        if not connected:
            return "warning", "Pi-hole unavailable"
        if not blocking:
            return "warning", "Blocking is disabled"
        if power["state"] == "warning":
            return "warning", power["label"]
        return "good", "System is healthy"


class TimedCache:
    def __init__(self, producer: Callable[[], dict[str, Any]], ttl: float):
        self.producer, self.ttl = producer, ttl
        self.value: dict[str, Any] | None = None
        self.expires = 0.0
        self.lock = threading.Lock()

    def get(self) -> dict[str, Any]:
        now = time.monotonic()
        if self.value is not None and now < self.expires:
            return self.value
        with self.lock:
            now = time.monotonic()
            if self.value is None or now >= self.expires:
                self.value = self.producer()
                self.expires = now + self.ttl
            return self.value


def make_handler(cache: TimedCache) -> type[BaseHTTPRequestHandler]:
    class DashboardHandler(BaseHTTPRequestHandler):
        server_version = f"PADD-Web/{__version__}"

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/favicon.ico":
                self.send_response(HTTPStatus.NO_CONTENT)
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                return
            if path == "/api/status":
                self._json(cache.get())
                return
            if path == "/api/health":
                self._json({"ok": True, "version": __version__})
                return
            static = STATIC_FILES.get(path)
            if not static:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            name, content_type = static
            try:
                body = (STATIC_DIR / name).read_bytes()
            except OSError:
                self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache" if name == "index.html" else "public, max-age=300")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; style-src 'self'; script-src 'self'")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload: Any) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: Any) -> None:
            if getattr(self.server, "quiet", False):
                return
            super().log_message(fmt, *args)

    return DashboardHandler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run PADD Web on a Raspberry Pi")
    parser.add_argument("--host", default=os.getenv("PADDWEB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PADDWEB_PORT", "8080")))
    parser.add_argument("--api", default=os.getenv("PADDWEB_API", "http://localhost/api/"), help="Pi-hole v6 API base URL")
    parser.add_argument("--password", default=os.getenv("PADDWEB_PASSWORD"))
    parser.add_argument("--totp", default=os.getenv("PADDWEB_TOTP"))
    parser.add_argument("--refresh", type=float, default=float(os.getenv("PADDWEB_REFRESH", "2")))
    parser.add_argument("--demo", action="store_true", help="show representative data without Pi-hole")
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    client = None if args.demo else PiHoleClient(args.api, args.password, args.totp)
    collector = DashboardCollector(client, demo=args.demo)
    cache = TimedCache(collector.collect, max(0.5, args.refresh))
    server = ThreadingHTTPServer((args.host, args.port), make_handler(cache))
    server.quiet = args.quiet  # type: ignore[attr-defined]
    display_host = "localhost" if args.host in ("127.0.0.1", "0.0.0.0") else args.host
    print(f"PADD Web v{__version__} is running at http://{display_host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping PADD Web.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
