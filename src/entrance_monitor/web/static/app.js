async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${url} failed: ${response.status}`);
  }
  return response.json();
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

function renderWarnings(flags) {
  if (!flags || flags.length === 0) {
    return "none";
  }
  return flags.join(", ");
}

function setStatusMessage(message, isError = false) {
  const el = byId("settings-status");
  if (el) {
    el.textContent = message;
    el.style.color = isError ? "var(--danger)" : "var(--accent)";
  }
}

function renderSnapshot(snapshot) {
  setText("system-state", snapshot.system_state);
  setText("entry-rate", snapshot.entry_rate_per_min);
  setText("exit-rate", snapshot.exit_rate_per_min);
  setText("net-flow", snapshot.net_flow_per_min);
  setText("load-level", snapshot.entrance_load_level);
  setText("camera-status", snapshot.camera_status);
  setText("mmwave-status", snapshot.mmwave_status);
  setText("frame-resolution", `${snapshot.frame_width}x${snapshot.frame_height}`);
  setText("presence-state", snapshot.presence_corroboration_state);
  setText("freshness-ms", `${snapshot.freshness_ms} ms`);
  setText("delivered-fps", snapshot.delivered_fps.toFixed(1));
  setText("detector-fps", snapshot.detector_fps.toFixed(1));
  setText("gated-mode", snapshot.gated_mode ? "yes" : "no");
  setText("count-confidence", snapshot.count_confidence);
  setText("warnings", renderWarnings(snapshot.warning_flags));
}

function renderStatus(status) {
  setText("cpu-percent", `${status.cpu_percent.toFixed(1)} %`);
  setText("ram-mb", `${status.ram_mb.toFixed(0)} MB`);
  setText("temperature-c", status.temperature_c == null ? "-" : `${status.temperature_c.toFixed(1)} C`);
  setText("audio-disabled", String(status.audio_disabled));
}

function renderEvents(items) {
  const body = byId("events-body");
  if (!body) {
    return;
  }
  body.innerHTML = "";
  if (!items || items.length === 0) {
    body.innerHTML = `<tr><td colspan="3">No recent events</td></tr>`;
    return;
  }
  items.slice(0, 12).forEach((event) => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${event.ts}</td>
      <td>${event.direction}</td>
      <td>${event.track_id}</td>
    `;
    body.appendChild(row);
  });
}

async function bootstrapDashboard() {
  try {
    const [snapshot, status, events] = await Promise.all([
      fetchJson("/api/v1/metrics/latest"),
      fetchJson("/api/v1/status"),
      fetchJson("/api/v1/events/recent?limit=12"),
    ]);
    renderSnapshot(snapshot);
    renderStatus(status);
    renderEvents(events.items);
  } catch (err) {
    console.error(err);
  }

  const source = new EventSource("/api/v1/stream");
  source.onmessage = async (event) => {
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
  byId("detector-fps-normal").value = payload.camera.detector_fps_normal;
  byId("detector-fps-gated").value = payload.camera.detector_fps_gated;
  byId("confidence-threshold").value = payload.detector.confidence_threshold;
  byId("imgsz").value = payload.detector.imgsz;
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
      detector_fps_normal: Number(byId("detector-fps-normal").value),
      detector_fps_gated: Number(byId("detector-fps-gated").value),
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
    setStatusMessage("Saving settingsâ€¦");
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
      setStatusMessage("Reloading settingsâ€¦");
      await loadSettings();
    });
  }

  await loadSettings();
}

if (window.location.pathname === "/debug") {
  bootstrapDebug();
} else if (window.location.pathname === "/settings") {
  bootstrapSettings();
} else {
  bootstrapDashboard();
}
