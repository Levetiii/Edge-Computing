async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${url} failed: ${response.status}`);
  }
  return response.json();
}

async function postJson(url, body = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || `${url} failed: ${response.status}`);
  }
  return payload;
}

function byId(id) {
  return document.getElementById(id);
}

function setText(id, value) {
  const el = byId(id);
  if (el) {
    el.textContent = value;
  }
}

function setTone(id, tone) {
  const el = byId(id);
  if (el) {
    el.dataset.tone = tone;
  }
}

function setDisabled(id, disabled) {
  const el = byId(id);
  if (el) {
    el.disabled = disabled;
  }
}

function classifyTone(value) {
  const text = String(value ?? "").toUpperCase();
  if (!text) {
    return "muted";
  }
  if (text === "OK" || text === "NORMAL" || text === "HIGH") {
    return "ok";
  }
  if (text.includes("DISCONNECTED") || text.includes("STALE")) {
    return "danger";
  }
  if (text.includes("DEGRADED") || text === "REDUCED" || text === "UNKNOWN") {
    return "warn";
  }
  return "muted";
}

function humanizeLabel(value) {
  const text = String(value ?? "");
  if (!text) {
    return "-";
  }
  if (text === "OK") {
    return "OK";
  }
  if (text === text.toUpperCase()) {
    return text
      .toLowerCase()
      .split("_")
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(" ");
  }
  return text;
}

function renderWarnings(flags) {
  if (!flags || flags.length === 0) {
    return "None";
  }
  return flags.map((flag) => humanizeLabel(flag)).join(", ");
}

function formatLastUpdated(snapshot) {
  const date = new Date(snapshot.ts);
  if (Number.isNaN(date.getTime())) {
    return `${snapshot.freshness_ms} ms old`;
  }
  const time = date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  return `${time} - ${snapshot.freshness_ms} ms old`;
}

function setStatusMessage(message, isError = false) {
  ["settings-status", "validation-status"].forEach((id) => {
    const el = byId(id);
    if (el) {
      el.textContent = message;
      el.style.color = isError ? "var(--danger)" : "var(--accent)";
    }
  });
}

function renderSnapshot(snapshot) {
  setText("system-state", humanizeLabel(snapshot.system_state));
  setTone("system-state", classifyTone(snapshot.system_state));
  setText("last-updated", formatLastUpdated(snapshot));
  setText("operator-confidence", humanizeLabel(snapshot.count_confidence));
  setTone("operator-confidence", classifyTone(snapshot.count_confidence));
  setText("entry-rate", snapshot.entry_rate_per_min);
  setText("exit-rate", snapshot.exit_rate_per_min);
  setText("net-flow", snapshot.net_flow_per_min);
  setText("load-level", snapshot.entrance_load_level);
  setText("entry-count-30s", snapshot.entry_count_30s);
  setText("exit-count-30s", snapshot.exit_count_30s);
  setText("net-count-30s", snapshot.net_count_30s);
  setText("crossing-count-30s", snapshot.crossing_count_30s);
  setText("camera-status", humanizeLabel(snapshot.camera_status));
  setTone("camera-status", classifyTone(snapshot.camera_status));
  setText("mmwave-status", humanizeLabel(snapshot.mmwave_status));
  setTone("mmwave-status", classifyTone(snapshot.mmwave_status));
  setText("frame-resolution", `${snapshot.frame_width}x${snapshot.frame_height}`);
  setText("presence-state", humanizeLabel(snapshot.presence_corroboration_state));
  setTone("presence-state", snapshot.presence_corroboration_state === "PRESENT" ? "ok" : "muted");
  setText("freshness-ms", `${snapshot.freshness_ms} ms`);
  setText("delivered-fps", snapshot.delivered_fps.toFixed(1));
  setText("detector-fps", snapshot.detector_fps.toFixed(1));
  setText("gated-mode", snapshot.gated_mode ? "yes" : "no");
  setText("count-confidence", humanizeLabel(snapshot.count_confidence));
  setTone("count-confidence", classifyTone(snapshot.count_confidence));
  setText("warnings", renderWarnings(snapshot.warning_flags));
  setTone("warnings", snapshot.warning_flags && snapshot.warning_flags.length > 0 ? "warn" : "ok");
  setTone("load-level", snapshot.entrance_load_level === "High" ? "danger" : snapshot.entrance_load_level === "Medium" ? "warn" : "ok");
}

function renderStatus(status) {
  setText("cpu-percent", `${status.cpu_percent.toFixed(1)} %`);
  setText("ram-mb", `${status.ram_mb.toFixed(0)} MB`);
  setText("temperature-c", status.temperature_c == null ? "-" : `${status.temperature_c.toFixed(1)} C`);
  setText("audio-disabled", String(status.audio_disabled));
}

function renderEvents(items) {
  const list = byId("events-body");
  if (!list) {
    return;
  }
  list.innerHTML = "";
  if (!items || items.length === 0) {
    list.innerHTML = `<li class="event-empty">No recent confirmed crossings.</li>`;
    setText("last-activity", "No recent events");
    return;
  }
  const latestEvent = items[0];
  setText("last-activity", `${humanizeLabel(latestEvent.direction)} ${formatRelativeTime(latestEvent.ts)}`);
  items.slice(0, 5).forEach((event) => {
    const item = document.createElement("li");
    const directionLabel = humanizeLabel(event.direction);
    item.className = "event-item";
    item.innerHTML = `
      <div class="event-time">
        <time datetime="${event.ts}">${formatEventTimestamp(event.ts)}</time>
        <span>${formatRelativeTime(event.ts)}</span>
      </div>
      <div class="event-body">
        <strong>${directionLabel} confirmed</strong>
        <p>Track ${event.track_id} crossed the counting line.</p>
      </div>
      <span class="event-badge" data-tone="${toneForDirection(event.direction)}">${directionLabel}</span>
    `;
    list.appendChild(item);
  });
}

function formatTimeLabel(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatEventTimestamp(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatDateTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value ?? "-";
  }
  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatDuration(seconds) {
  if (!Number.isFinite(seconds)) {
    return "-";
  }
  if (seconds < 60) {
    return `${seconds.toFixed(1)} s`;
  }
  const totalSeconds = Math.round(seconds);
  const minutes = Math.floor(totalSeconds / 60);
  const remainder = totalSeconds % 60;
  return `${minutes}m ${remainder}s`;
}

function formatRelativeTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  const diffSeconds = Math.round((date.getTime() - Date.now()) / 1000);
  const absSeconds = Math.abs(diffSeconds);
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  if (absSeconds < 60) {
    return formatter.format(diffSeconds, "second");
  }
  const diffMinutes = Math.round(diffSeconds / 60);
  if (Math.abs(diffMinutes) < 60) {
    return formatter.format(diffMinutes, "minute");
  }
  const diffHours = Math.round(diffMinutes / 60);
  if (Math.abs(diffHours) < 24) {
    return formatter.format(diffHours, "hour");
  }
  const diffDays = Math.round(diffHours / 24);
  return formatter.format(diffDays, "day");
}

function toneForDirection(direction) {
  const text = String(direction ?? "").toUpperCase();
  if (text === "ENTRY") {
    return "ok";
  }
  if (text === "EXIT") {
    return "warn";
  }
  return "muted";
}

function minutesSinceLocalMidnight() {
  const now = new Date();
  const midnight = new Date(now);
  midnight.setHours(0, 0, 0, 0);
  return Math.max(15, Math.ceil((now.getTime() - midnight.getTime()) / 60000));
}

function getTrendRangeConfig(rangeKey) {
  if (rangeKey === "1h") {
    return { key: rangeKey, minutes: 60, label: "Last 1 hour" };
  }
  if (rangeKey === "today") {
    return { key: rangeKey, minutes: minutesSinceLocalMidnight(), label: "Today" };
  }
  return { key: "15m", minutes: 15, label: "Last 15 min" };
}

function polylinePoints(items, accessor, timeMin, timeMax, width, height, padding, maxY) {
  return items.map((item, index) => {
    const timeValue = new Date(item.ts).getTime();
    const normalizedX = timeMax === timeMin
      ? (items.length <= 1 ? 0 : index / (items.length - 1))
      : (timeValue - timeMin) / (timeMax - timeMin);
    const normalizedY = maxY <= 0 ? 0 : accessor(item) / maxY;
    const x = padding.left + normalizedX * (width - padding.left - padding.right);
    const y = padding.top + (1 - normalizedY) * (height - padding.top - padding.bottom);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}

function renderTrendChart(items, rangeLabel = "Last 15 min") {
  const svg = byId("trend-chart");
  const empty = byId("trend-empty");
  const range = byId("trend-range-label");
  if (!svg || !empty || !range) {
    return;
  }

  if (!items || items.length < 2) {
    svg.innerHTML = "";
    empty.textContent = "Collecting enough history to show a trend.";
    empty.style.display = "flex";
    range.textContent = rangeLabel;
    setText("peak-crossings", "0");
    setText("peak-crossings-context", rangeLabel);
    return;
  }

  const width = 760;
  const height = 240;
  const padding = { top: 16, right: 16, bottom: 28, left: 36 };
  const values = items.flatMap((item) => [
    item.entry_count_30s ?? 0,
    item.exit_count_30s ?? 0,
    item.crossing_count_30s ?? 0,
  ]);
  const maxY = Math.max(1, ...values);
  setText("peak-crossings", String(Math.max(...items.map((item) => item.crossing_count_30s ?? 0))));
  setText("peak-crossings-context", rangeLabel);
  const times = items.map((item) => new Date(item.ts).getTime()).filter((value) => !Number.isNaN(value));
  const timeMin = Math.min(...times);
  const timeMax = Math.max(...times);
  const leftLabel = formatTimeLabel(items[0].ts);
  const rightLabel = formatTimeLabel(items[items.length - 1].ts);

  const gridLevels = 4;
  const innerHeight = height - padding.top - padding.bottom;
  const grid = [];
  for (let index = 0; index <= gridLevels; index += 1) {
    const ratio = index / gridLevels;
    const y = padding.top + ratio * innerHeight;
    const value = Math.round((1 - ratio) * maxY);
    grid.push(`
      <line x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}" class="trend-grid-line" />
      <text x="${padding.left - 8}" y="${y + 4}" text-anchor="end" class="trend-axis-label">${value}</text>
    `);
  }

  const entryPoints = polylinePoints(items, (item) => item.entry_count_30s ?? 0, timeMin, timeMax, width, height, padding, maxY);
  const exitPoints = polylinePoints(items, (item) => item.exit_count_30s ?? 0, timeMin, timeMax, width, height, padding, maxY);
  const crossingPoints = polylinePoints(items, (item) => item.crossing_count_30s ?? 0, timeMin, timeMax, width, height, padding, maxY);

  svg.innerHTML = `
    <rect x="0" y="0" width="${width}" height="${height}" rx="14" class="trend-bg"></rect>
    ${grid.join("")}
    <polyline points="${entryPoints}" class="trend-line trend-line-entry"></polyline>
    <polyline points="${exitPoints}" class="trend-line trend-line-exit"></polyline>
    <polyline points="${crossingPoints}" class="trend-line trend-line-crossings"></polyline>
    <text x="${padding.left}" y="${height - 8}" text-anchor="start" class="trend-axis-label">${leftLabel}</text>
    <text x="${width - padding.right}" y="${height - 8}" text-anchor="end" class="trend-axis-label">${rightLabel}</text>
  `;
  range.textContent = rangeLabel;
  empty.style.display = "none";
}

function renderValidation(validation) {
  setText("validation-session-id", validation.session_id ?? "-");
  setText("validation-state", validation.state);
  setText("validation-active", validation.active ? "yes" : "no");
  setText("validation-started-at", validation.started_at ? formatDateTime(validation.started_at) : "-");
  setText("validation-ended-at", validation.ended_at ? formatDateTime(validation.ended_at) : "-");
  setText("validation-saved-at", validation.saved_at ? formatDateTime(validation.saved_at) : "-");
  setText("validation-duration", formatDuration(validation.duration_seconds));
  setText("validation-manual-entry-count", validation.manual_entry_count);
  setText("validation-manual-exit-count", validation.manual_exit_count);
  setText("validation-manual-total", validation.manual_total_count);
  setText("validation-system-entry-count", validation.system_entry_count);
  setText("validation-system-exit-count", validation.system_exit_count);
  setText("validation-system-total", validation.system_total_count);
  setText("validation-entry-error", validation.entry_error);
  setText("validation-exit-error", validation.exit_error);
  setText("validation-total-error", validation.total_error);
  const hasSession = Boolean(validation.session_id) || validation.state !== "NOT_STARTED";
  setDisabled("validation-start", validation.active);
  setDisabled("validation-stop", !validation.active);
  setDisabled("validation-manual-entry", !validation.active);
  setDisabled("validation-manual-exit", !validation.active);
  setDisabled("validation-reset", !hasSession);

  const body = byId("validation-events-body");
  if (!body) {
    return;
  }
  body.innerHTML = "";
  if (!validation.recent_events || validation.recent_events.length === 0) {
    body.innerHTML = `<tr><td colspan="3">No session events</td></tr>`;
    return;
  }
  validation.recent_events.forEach((event) => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${formatEventTimestamp(event.ts)}</td>
      <td>${humanizeLabel(event.direction)}</td>
      <td>${event.track_id}</td>
    `;
    body.appendChild(row);
  });
}

function renderValidationHistory(items) {
  const body = byId("validation-history-body");
  const exportButton = byId("validation-export");
  if (exportButton) {
    exportButton.disabled = !items || items.length === 0;
  }
  if (!body) {
    return;
  }
  body.innerHTML = "";
  if (!items || items.length === 0) {
    body.innerHTML = `<tr><td colspan="6">No saved sessions</td></tr>`;
    return;
  }
  items.forEach((item) => {
    const config = item.config_snapshot ?? {};
    const camera = config.camera ?? {};
    const detector = config.detector ?? {};
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>
        <strong>${formatDateTime(item.saved_at)}</strong>
        <span class="history-meta">${formatRelativeTime(item.saved_at)}</span>
      </td>
      <td>
        <strong>${item.session_id}</strong>
        <span class="history-meta">${humanizeLabel(item.state)} &middot; ${formatDuration(item.duration_seconds)}</span>
      </td>
      <td>
        <strong>${item.manual_total_count}</strong>
        <span class="history-meta">E ${item.manual_entry_count} / X ${item.manual_exit_count}</span>
      </td>
      <td>
        <strong>${item.system_total_count}</strong>
        <span class="history-meta">E ${item.system_entry_count} / X ${item.system_exit_count}</span>
      </td>
      <td data-tone="${item.total_error === 0 ? "ok" : "warn"}">
        <strong>${item.total_error}</strong>
        <span class="history-meta">Entry ${item.entry_error}, Exit ${item.exit_error}</span>
      </td>
      <td>
        <strong>${humanizeLabel(detector.backend ?? "-")}</strong>
        <span class="history-meta">
          ROI ${camera.roi?.x1 ?? "-"},${camera.roi?.y1 ?? "-"}-${camera.roi?.x2 ?? "-"},${camera.roi?.y2 ?? "-"}
        </span>
      </td>
    `;
    body.appendChild(row);
  });
}

async function bootstrapDashboard() {
  const dashboardState = {
    paused: false,
    rangeKey: "15m",
  };

  const freezeButton = byId("toggle-live-updates");
  const rangeButtons = Array.from(document.querySelectorAll("[data-range]"));

  const syncDashboardControls = () => {
    setText("live-mode-state", dashboardState.paused ? "Paused" : "Live");
    setTone("live-mode-state", dashboardState.paused ? "warn" : "ok");
    if (freezeButton) {
      freezeButton.textContent = dashboardState.paused ? "Resume" : "Freeze";
    }
    rangeButtons.forEach((button) => {
      button.classList.toggle("is-active", button.dataset.range === dashboardState.rangeKey);
    });
  };

  const refreshDashboard = async (force = false) => {
    if (dashboardState.paused && !force) {
      return;
    }
    const range = getTrendRangeConfig(dashboardState.rangeKey);
    try {
      const [snapshot, status, events, history] = await Promise.all([
        fetchJson("/api/v1/metrics/latest"),
        fetchJson("/api/v1/status"),
        fetchJson("/api/v1/events/recent?limit=12"),
        fetchJson(`/api/v1/metrics/history?minutes=${range.minutes}`),
      ]);
      renderSnapshot(snapshot);
      renderStatus(status);
      renderEvents(events.items);
      renderTrendChart(history.items, range.label);
    } catch (err) {
      console.error(err);
    }
  };

  syncDashboardControls();
  await refreshDashboard(true);

  if (freezeButton) {
    freezeButton.addEventListener("click", async () => {
      dashboardState.paused = !dashboardState.paused;
      syncDashboardControls();
      if (!dashboardState.paused) {
        await refreshDashboard(true);
      }
    });
  }

  rangeButtons.forEach((button) => {
    button.addEventListener("click", async () => {
      dashboardState.rangeKey = button.dataset.range;
      syncDashboardControls();
      await refreshDashboard(true);
    });
  });

  setInterval(() => {
    refreshDashboard(false);
  }, 5000);

  const source = new EventSource("/api/v1/stream");
  source.onmessage = async (event) => {
    if (dashboardState.paused) {
      return;
    }
    const snapshot = JSON.parse(event.data);
    renderSnapshot(snapshot);
    try {
      const [status, events] = await Promise.all([
        fetchJson("/api/v1/status"),
        fetchJson("/api/v1/events/recent?limit=12"),
      ]);
      renderStatus(status);
      renderEvents(events.items);
    } catch (err) {
      console.error(err);
    }
  };
}

async function bootstrapDebug() {
  const debugJson = byId("debug-json");
  const debugFrame = byId("debug-frame");
  if (!debugJson) {
    return;
  }
  const tick = async () => {
    try {
      const snapshot = await fetchJson("/api/v1/metrics/latest");
      debugJson.textContent = JSON.stringify(snapshot, null, 2);
      if (debugFrame) {
        debugFrame.src = `/api/v1/debug/frame.jpg?t=${Date.now()}`;
      }
    } catch (err) {
      debugJson.textContent = String(err);
    }
  };
  await tick();
  setInterval(tick, 200);
}

function populateSettingsForm(payload) {
  setText("settings-status", `Loaded from ${payload.config_path ?? "active config"}`);
  byId("roi-x1").value = payload.camera.roi.x1;
  byId("roi-y1").value = payload.camera.roi.y1;
  byId("roi-x2").value = payload.camera.roi.x2;
  byId("roi-y2").value = payload.camera.roi.y2;
  byId("line-x1").value = payload.camera.line.x1;
  byId("line-y1").value = payload.camera.line.y1;
  byId("line-x2").value = payload.camera.line.x2;
  byId("line-y2").value = payload.camera.line.y2;
  byId("crossing-cooldown").value = payload.camera.crossing_cooldown_seconds;
  byId("line-hysteresis").value = payload.camera.line_hysteresis_px;
  byId("min-track-hits").value = payload.camera.min_track_hits_for_crossing;
  byId("crossing-confirm-frames").value = payload.camera.crossing_confirm_frames;
  byId("detector-fps-normal").value = payload.camera.detector_fps_normal;
  byId("detector-fps-gated").value = payload.camera.detector_fps_gated;
  byId("confidence-threshold").value = payload.detector.confidence_threshold;
  byId("imgsz").value = payload.detector.imgsz;
  byId("min-detection-width").value = payload.camera.min_detection_width_px;
  byId("min-detection-height").value = payload.camera.min_detection_height_px;
  byId("detection-edge-margin").value = payload.camera.detection_edge_margin_px;
  byId("crossing-band-medium").value = payload.runtime.crossing_band_medium_threshold;
  byId("crossing-band-high").value = payload.runtime.crossing_band_high_threshold;
  byId("promote-threshold").value = payload.camera.active_track_promote_threshold;
  byId("promote-seconds").value = payload.camera.active_track_promote_seconds;
}

function collectSettingsPayload() {
  return {
    camera: {
      roi: {
        x1: Number(byId("roi-x1").value),
        y1: Number(byId("roi-y1").value),
        x2: Number(byId("roi-x2").value),
        y2: Number(byId("roi-y2").value),
      },
      line: {
        x1: Number(byId("line-x1").value),
        y1: Number(byId("line-y1").value),
        x2: Number(byId("line-x2").value),
        y2: Number(byId("line-y2").value),
      },
      crossing_cooldown_seconds: Number(byId("crossing-cooldown").value),
      line_hysteresis_px: Number(byId("line-hysteresis").value),
      min_track_hits_for_crossing: Number(byId("min-track-hits").value),
      crossing_confirm_frames: Number(byId("crossing-confirm-frames").value),
      detector_fps_normal: Number(byId("detector-fps-normal").value),
      detector_fps_gated: Number(byId("detector-fps-gated").value),
      min_detection_width_px: Number(byId("min-detection-width").value),
      min_detection_height_px: Number(byId("min-detection-height").value),
      detection_edge_margin_px: Number(byId("detection-edge-margin").value),
      active_track_promote_threshold: Number(byId("promote-threshold").value),
      active_track_promote_seconds: Number(byId("promote-seconds").value),
    },
    detector: {
      confidence_threshold: Number(byId("confidence-threshold").value),
      imgsz: Number(byId("imgsz").value),
    },
    runtime: {
      crossing_band_medium_threshold: Number(byId("crossing-band-medium").value),
      crossing_band_high_threshold: Number(byId("crossing-band-high").value),
    },
  };
}

async function bootstrapSettings() {
  const form = byId("settings-form");
  const reloadButton = byId("settings-reload");
  if (!form) {
    return;
  }

  const loadSettings = async () => {
    try {
      const payload = await fetchJson("/api/v1/settings");
      populateSettingsForm(payload);
    } catch (err) {
      setStatusMessage(String(err), true);
    }
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    setStatusMessage("Saving settings...");
    try {
      const response = await fetch("/api/v1/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(collectSettingsPayload()),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || `save failed: ${response.status}`);
      }
      populateSettingsForm(payload);
      setStatusMessage("Saved and applied.");
    } catch (err) {
      setStatusMessage(String(err), true);
    }
  });

  if (reloadButton) {
    reloadButton.addEventListener("click", async () => {
      setStatusMessage("Reloading settings...");
      await loadSettings();
    });
  }

  await loadSettings();
}

async function bootstrapValidation() {
  const loadValidation = async () => {
    try {
      const [validation, history] = await Promise.all([
        fetchJson("/api/v1/validation"),
        fetchJson("/api/v1/validation/history?limit=12"),
      ]);
      renderValidation(validation);
      renderValidationHistory(history.items);
      setStatusMessage("Validation session ready.");
    } catch (err) {
      setStatusMessage(String(err), true);
    }
  };

  const wireAction = (id, url, successMessage) => {
    const button = byId(id);
    if (!button) {
      return;
    }
    button.addEventListener("click", async () => {
      setStatusMessage(successMessage.replace("done", "working..."));
      try {
        const validation = await postJson(url);
        const history = await fetchJson("/api/v1/validation/history?limit=12");
        renderValidation(validation);
        renderValidationHistory(history.items);
        setStatusMessage(successMessage);
      } catch (err) {
        setStatusMessage(String(err), true);
      }
    });
  };

  wireAction("validation-start", "/api/v1/validation/start", "Validation session started.");
  wireAction("validation-stop", "/api/v1/validation/stop", "Validation session stopped.");
  wireAction("validation-reset", "/api/v1/validation/reset", "Validation session reset.");
  wireAction("validation-manual-entry", "/api/v1/validation/manual-entry", "Manual entry recorded.");
  wireAction("validation-manual-exit", "/api/v1/validation/manual-exit", "Manual exit recorded.");

  const exportButton = byId("validation-export");
  if (exportButton) {
    exportButton.addEventListener("click", () => {
      window.location.href = "/api/v1/validation/export.csv?limit=100";
    });
  }

  try {
    const [snapshot, validation, history] = await Promise.all([
      fetchJson("/api/v1/metrics/latest"),
      fetchJson("/api/v1/validation"),
      fetchJson("/api/v1/validation/history?limit=12"),
    ]);
    renderSnapshot(snapshot);
    renderValidation(validation);
    renderValidationHistory(history.items);
    setStatusMessage("Validation session ready.");
  } catch (err) {
    setStatusMessage(String(err), true);
  }

  const source = new EventSource("/api/v1/stream");
  source.onmessage = async (event) => {
    const snapshot = JSON.parse(event.data);
    renderSnapshot(snapshot);
    try {
      const validation = await fetchJson("/api/v1/validation");
      renderValidation(validation);
    } catch (err) {
      setStatusMessage(String(err), true);
    }
  };
}

if (window.location.pathname === "/debug") {
  bootstrapDebug();
} else if (window.location.pathname === "/settings") {
  bootstrapSettings();
} else if (window.location.pathname === "/validation") {
  bootstrapValidation();
} else {
  bootstrapDashboard();
}
