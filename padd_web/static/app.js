"use strict";

const $ = (id) => document.getElementById(id);
const nf = new Intl.NumberFormat();
const state = { lastUpdate: 0, lastHealth: "", timer: null };

function setText(id, value, fallback = "—") {
  const element = $(id);
  if (element) element.textContent = value === null || value === undefined || value === "" ? fallback : String(value);
}
function percent(value) { return Math.max(0, Math.min(100, Number(value) || 0)); }
function setBar(id, value) { $(id).style.width = `${percent(value)}%`; }
function enabled(value) { return value ? "Enabled" : "Disabled"; }
function duration(seconds) {
  let remaining = Math.max(0, Number(seconds) || 0);
  const days = Math.floor(remaining / 86400); remaining %= 86400;
  const hours = Math.floor(remaining / 3600); remaining %= 3600;
  const minutes = Math.floor(remaining / 60);
  return [days && `${days}d`, hours && `${hours}h`, `${minutes}m`].filter(Boolean).join(" ");
}

function render(data) {
  const { status, summary, system, network, hardware, activity, versions, meta } = data;
  $("dashboard").setAttribute("aria-busy", "false");
  $("health-label").textContent = status.label;
  $("health-label").closest(".health").dataset.state = status.state;
  setText("hostname", system.hostname); setText("ipv4", network.ipv4);
  setText("blocked-percent", Number(summary.blocked_percent).toFixed(1));
  setText("blocked-count", nf.format(summary.blocked)); setText("query-count", nf.format(summary.queries));
  setText("domains", nf.format(summary.domains)); setText("clients", nf.format(summary.clients)); setBar("blocked-bar", summary.blocked_percent);
  setText("model", system.model); setText("cpu", `${Number(system.cpu_percent).toFixed(1)}%`); setBar("cpu-bar", system.cpu_percent);
  setText("memory", `${Number(system.memory_percent).toFixed(1)}%`); setBar("memory-bar", system.memory_percent);
  setText("loads", `load ${system.loads.map((x) => Number(x).toFixed(2)).join(" / ")}`);
  setText("temperature", system.temperature == null ? "N/A" : `${Number(system.temperature).toFixed(1)}°${system.temperature_unit}`);
  setText("uptime", `uptime ${duration(system.uptime)}`);
  $("power-card").dataset.state = hardware.power.state; setText("power", hardware.power.label); setText("vcore", `Vcore ${hardware.power.vcore || "N/A"}`);
  $("ups-card").dataset.state = hardware.ups.state; setText("ups", hardware.ups.label); setBar("ups-fill", hardware.ups.percent);
  setText("recent-blocked", activity.recent_blocked); setText("top-blocked", activity.top_blocked);
  setText("top-domain", activity.top_domain); setText("top-client", activity.top_client);
  setText("interface", network.interface); setText("network-ipv4", network.ipv4); setText("network-ipv6", network.ipv6);
  setText("rx", network.rx); setText("tx", network.tx); setText("dnssec", enabled(network.dnssec)); setText("dhcp", enabled(network.dhcp));
  setText("version-padd", versions.padd_web); setText("version-core", versions.core); setText("version-web", versions.web); setText("version-ftl", versions.ftl);
  setText("connection-text", status.connected ? (meta.demo ? "Demo signal" : "Pi-hole connected") : "Local telemetry only");
  state.lastUpdate = Date.now(); $("dashboard").dataset.stale = "false";
  if (state.lastHealth !== status.label) { $("announcer").textContent = `PADD status: ${status.label}`; state.lastHealth = status.label; }
}

async function refresh() {
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    render(await response.json());
  } catch (error) {
    $("dashboard").dataset.stale = "true";
    $("health-label").textContent = "Dashboard data unavailable";
    $("health-label").closest(".health").dataset.state = "critical";
    setText("connection-text", "Server disconnected");
  } finally {
    clearTimeout(state.timer); state.timer = setTimeout(refresh, 3000);
  }
}

function tick() {
  const now = new Date();
  $("clock").textContent = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  $("date").textContent = now.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
  if (state.lastUpdate) {
    const age = Math.floor((Date.now() - state.lastUpdate) / 1000);
    $("freshness").textContent = age < 2 ? "now" : `${age}s ago`;
    if (age > 10) $("dashboard").dataset.stale = "true";
  }
}

const mode = $("mode");
const savedMode = localStorage.getItem("padd-mode") || "auto";
mode.value = savedMode; document.documentElement.dataset.mode = savedMode;
mode.addEventListener("change", () => { document.documentElement.dataset.mode = mode.value; localStorage.setItem("padd-mode", mode.value); });
tick(); setInterval(tick, 1000); refresh();

