"use strict";

function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) return;
  if (!/^https?:$/.test(window.location.protocol)) return;
  navigator.serviceWorker.register("./sw.js").catch(() => {});
}

function isStandalone() {
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    window.matchMedia("(display-mode: minimal-ui)").matches ||
    window.matchMedia("(display-mode: window-controls-overlay)").matches ||
    window.navigator.standalone === true
  );
}

function setupInstallPrompt() {
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    installPrompt = event;
    renderSystem();
  });
  window.addEventListener("appinstalled", () => {
    installPrompt = null;
    toast("ADECK INSTALLED", "success");
    renderSystem();
  });
}

async function promptInstall() {
  if (!installPrompt) {
    toast("USE BROWSER MENU → INSTALL ADECK", "info");
    return;
  }
  const prompt = installPrompt;
  installPrompt = null;
  try {
    prompt.prompt();
    const choice = await prompt.userChoice;
    if (choice && choice.outcome === "accepted") toast("ADDING ADECK TO WINDOWS", "success");
  } catch (_) {
    toast("INSTALL PROMPT UNAVAILABLE", "error");
  }
  renderSystem();
}

function readServiceHint() {
  try {
    return JSON.parse(localStorage.getItem(SERVICE_HINT_KEY) || "{}") || {};
  } catch (_) {
    return {};
  }
}

function writeServiceHint(hint) {
  try {
    localStorage.setItem(SERVICE_HINT_KEY, JSON.stringify(hint));
  } catch (_) {}
}

function formatUptime(seconds) {
  const total = Math.max(0, Number(seconds) || 0);
  if (total < 60) return total + "S";
  if (total < 3600) return Math.floor(total / 60) + "M";
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  return hours + "H " + minutes + "M";
}

function setSysValue(el, text, tone) {
  if (!el) return;
  el.textContent = text;
  el.classList.remove("is-ok", "is-warn", "is-bad");
  if (tone) el.classList.add(tone);
}

function activeServiceTask() {
  if (!taskWatch || taskWatch.finished) return null;
  return SERVICE_TASKS.has(taskWatch.action) ? taskWatch.action : null;
}

function renderOfflineOverlay() {
  if (!els.offlineOverlay) return;
  const hint = readServiceHint();
  const running = activeServiceTask();
  if (running) {
    els.offlineKicker.textContent = running.toUpperCase().replace(/-/g, " ");
    els.offlineTitle.textContent = "SERVICE IS RESTARTING";
    els.offlineMessage.textContent =
      "The maintenance task is still running and the local service is down for a moment. This window reconnects on its own.";
    els.offlineHint.textContent = "Nothing to do — hold on.";
    els.offlineStartBtn.hidden = true;
  } else {
    els.offlineKicker.textContent = "SERVICE";
    els.offlineTitle.textContent = "ADECK SERVICE IS NOT RUNNING";
    els.offlineMessage.textContent =
      "This window is open, but the local ADeck service is not answering on 127.0.0.1:8765. Saved profiles and device settings are untouched.";
    els.offlineHint.textContent = hint.protocol
      ? "Use START SERVICE, or open ADeck from its desktop icon."
      : "Open ADeck from its desktop icon, or run Start ADeck.bat in the project folder.";
    els.offlineStartBtn.hidden = !hint.protocol;
  }
}

function showOfflineOverlay() {
  if (!els.offlineOverlay) return;
  renderOfflineOverlay();
  els.offlineOverlay.hidden = false;
}

function hideOfflineOverlay() {
  if (els.offlineOverlay) els.offlineOverlay.hidden = true;
}

function setBackendReachable(ok) {
  const backend = state.backend;
  if (ok) {
    const recovered = !backend.reachable;
    backend.reachable = true;
    backend.failures = 0;
    hideOfflineOverlay();
    if (recovered) {
      toast("SERVICE RECONNECTED", "success");
      refreshSystem();
    }
  } else {
    backend.failures += 1;
    backend.status = null;
    if (backend.failures >= 2) {
      backend.reachable = false;
      showOfflineOverlay();
    }
  }
  updateNavDot();
  updateStatusBar();
}

function startService() {
  const hint = readServiceHint();
  if (!hint.protocol) {
    toast("OPEN ADECK FROM ITS DESKTOP ICON", "info");
    return;
  }
  toast("STARTING ADECK SERVICE", "info");
  window.location.href = "adeck://start";
}

async function apiPost(path, body, timeoutMs) {
  const response = await fetchWithTimeout(
    localBridge + path,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    },
    timeoutMs || 15000
  );
  const data = await response.json().catch(() => ({}));
  if (!response.ok || !data.ok) {
    throw new Error(data.error || "Request failed (HTTP " + response.status + ")");
  }
  return data;
}

async function apiGet(path, timeoutMs) {
  const response = await fetchWithTimeout(
    localBridge + path,
    { cache: "no-store" },
    timeoutMs || 6000
  );
  const data = await response.json().catch(() => ({}));
  if (!response.ok || !data.ok) {
    throw new Error(data.error || "Request failed (HTTP " + response.status + ")");
  }
  return data;
}

async function refreshSystem() {
  try {
    const data = await apiGet("/api/system", 8000);
    state.backend.system = data;
    const integration = data.integration || {};
    writeServiceHint({
      protocol: !!integration.protocol_handler,
      desktop: !!integration.desktop_shortcut,
    });
  } catch (_) {
    state.backend.system = null;
  }
  renderSystem();
  updateNavDot();
  return state.backend.system;
}

function systemAttention() {
  const system = state.backend.system;
  if (!state.backend.reachable) {
    return {
      tone: "is-bad",
      title: "SERVICE OFFLINE",
      text: "The local ADeck service is not answering. Profiles stay saved on this PC.",
      action: null,
    };
  }
  if (system && system.environment && system.environment.setup_complete === false) {
    const missing = [];
    if (!system.environment.venv) missing.push("Python environment");
    if (!system.environment.pyserial) missing.push("PySerial");
    if (!system.environment.arduino_cli) missing.push("Arduino CLI");
    return {
      tone: "is-bad",
      title: "SETUP INCOMPLETE",
      text: "Missing: " + (missing.join(", ") || "setup components") + ".",
      action: { label: "INSTALL / REPAIR", handler: () => runTask("repair") },
    };
  }
  const device = (system && system.device) || state.backend.status;
  if (device && !device.connected) {
    return {
      tone: "is-warn",
      title: "HARDWARE OFFLINE",
      text:
        (device.error ? device.error + ". " : "") +
        "Connect the UNO R4 WiFi with a data USB cable. Editing still works and syncs when it returns.",
      action: { label: "RECONNECT BOARD", handler: () => reconnectDevice() },
    };
  }
  if (device && device.connected && device.last_sync === false) {
    return {
      tone: "is-warn",
      title: "LAST SYNC FAILED",
      text: device.error || "The board did not acknowledge the last configuration.",
      action: { label: "RESYNC TO DEVICE", handler: () => resyncDevice() },
    };
  }
  if (system && system.config && system.config.saved === false) {
    return {
      tone: "is-warn",
      title: "NOTHING SAVED YET",
      text: "Use SAVE & JSON on the dashboard to store profiles and push them to the board.",
      action: null,
    };
  }
  return null;
}

function updateNavDot() {
  if (!els.navSystemDot) return;
  els.navSystemDot.hidden = !systemAttention();
}

function renderSystemBanner() {
  if (!els.systemBanner) return;
  const attention = systemAttention();
  els.systemBanner.classList.remove("is-bad", "is-ok");
  if (!attention) {
    els.systemBanner.hidden = true;
    return;
  }
  els.systemBanner.hidden = false;
  if (attention.tone === "is-bad") els.systemBanner.classList.add("is-bad");
  els.systemBannerTitle.textContent = attention.title;
  els.systemBannerText.textContent = attention.text;
  if (attention.action) {
    els.systemBannerAction.hidden = false;
    els.systemBannerAction.textContent = attention.action.label;
    els.systemBannerAction.onclick = attention.action.handler;
  } else {
    els.systemBannerAction.hidden = true;
    els.systemBannerAction.onclick = null;
  }
}

function renderPortOptions(system) {
  const select = els.sysPortSelect;
  if (!select) return;
  const ports = (system && system.serial_ports) || [];
  const wanted = select.dataset.pending || (system && system.requested_port) || "";
  select.innerHTML = "";
  const auto = document.createElement("option");
  auto.value = "";
  auto.textContent = ports.length
    ? "AUTO-DETECT (" + ports.length + " PORT" + (ports.length === 1 ? "" : "S") + ")"
    : "AUTO-DETECT";
  select.appendChild(auto);
  ports.forEach((port) => {
    const option = document.createElement("option");
    option.value = port.device;
    const tag = port.arduino ? " — ARDUINO" : port.description ? " — " + port.description : "";
    option.textContent = (port.device + tag).slice(0, 48);
    select.appendChild(option);
  });
  if (wanted && !ports.some((port) => port.device === wanted)) {
    const option = document.createElement("option");
    option.value = wanted;
    option.textContent = wanted + " — NOT PRESENT";
    select.appendChild(option);
  }
  select.value = wanted || "";
}

function renderSystem() {
  if (!els.sysBackend) return;
  const system = state.backend.system;
  const status = state.backend.status;

  const device = !state.backend.reachable
    ? null
    : status || (system && system.device) || null;

  if (!state.backend.reachable) {
    setSysValue(els.sysBackend, "NOT RUNNING", "is-bad");
  } else if (system && system.backend) {
    setSysValue(
      els.sysBackend,
      "RUNNING — v" +
        system.bridge_version +
        " · PID " +
        system.backend.pid +
        " · UP " +
        formatUptime(system.backend.uptime_seconds),
      "is-ok"
    );
  } else if (status) {
    setSysValue(els.sysBackend, "RUNNING — v" + (status.bridge_version || "?"), "is-ok");
  } else {
    setSysValue(els.sysBackend, "CHECKING…", null);
  }

  if (!device) {
    setSysValue(els.sysHardware, "UNKNOWN", null);
    setSysValue(els.sysPort, "—", null);
    setSysValue(els.sysFirmware, "—", null);
    setSysValue(els.sysSync, "—", null);
  } else if (device.connected) {
    setSysValue(els.sysHardware, "CONNECTED", "is-ok");
    setSysValue(els.sysPort, String(device.port || "—"), "is-ok");
    setSysValue(els.sysFirmware, "PROTOCOL " + (device.firmware || "?"), "is-ok");
    if (device.last_sync === true) {
      setSysValue(
        els.sysSync,
        "IN SYNC" + (device.last_transaction_id ? " · " + device.last_transaction_id : ""),
        "is-ok"
      );
    } else if (device.last_sync === false) {
      setSysValue(els.sysSync, "NOT SYNCED — " + (device.error || "no acknowledgement"), "is-warn");
    } else {
      setSysValue(els.sysSync, "WAITING FOR FIRST SAVE", null);
    }
  } else {
    setSysValue(els.sysHardware, "OFFLINE — " + (device.error || "not connected"), "is-warn");
    const ports = (system && system.serial_ports) || [];
    const arduino = ports.filter((port) => port.arduino).length;
    setSysValue(
      els.sysPort,
      ports.length
        ? "NOT CONNECTED · " + ports.length + " PORT(S) SEEN" + (arduino ? ", " + arduino + " ARDUINO" : "")
        : "NO SERIAL PORTS FOUND",
      "is-warn"
    );
    setSysValue(els.sysFirmware, "UNKNOWN — BOARD OFFLINE", "is-warn");
    setSysValue(els.sysSync, "PENDING — SYNCS WHEN CONNECTED", "is-warn");
  }

  if (system && system.config) {
    if (system.config.saved) {
      setSysValue(
        els.sysConfig,
        "SAVED — " +
          system.config.profile_count +
          " PROFILE(S) · ACTIVE " +
          (system.config.active_profile || "—"),
        "is-ok"
      );
    } else {
      setSysValue(els.sysConfig, "NOT SAVED YET", "is-warn");
    }
  } else {
    setSysValue(els.sysConfig, "—", null);
  }

  if (system && system.environment) {
    const env = system.environment;
    if (env.setup_complete) {
      setSysValue(
        els.sysSetup,
        "COMPLETE — PYSERIAL " + (env.pyserial || "?") + " · ARDUINO CLI READY",
        "is-ok"
      );
    } else {
      const missing = [];
      if (!env.venv) missing.push("PYTHON ENV");
      if (!env.pyserial) missing.push("PYSERIAL");
      if (!env.arduino_cli) missing.push("ARDUINO CLI");
      setSysValue(els.sysSetup, "INCOMPLETE — MISSING " + missing.join(", "), "is-bad");
    }
  } else {
    setSysValue(els.sysSetup, "—", null);
  }

  const integration = (system && system.integration) || {};
  const standalone = isStandalone();
  setSysValue(
    els.sysInstalled,
    standalone ? "INSTALLED APP WINDOW" : "BROWSER TAB",
    standalone ? "is-ok" : null
  );
  setSysValue(
    els.sysDesktop,
    integration.desktop_shortcut ? "CREATED" : "NOT CREATED",
    integration.desktop_shortcut ? "is-ok" : null
  );
  setSysValue(
    els.sysAutostart,
    integration.autostart ? "ON" : "OFF",
    integration.autostart ? "is-ok" : null
  );
  if (els.sysAutostartBtn) {
    els.sysAutostartBtn.textContent = integration.autostart
      ? "TURN OFF START WITH WINDOWS"
      : "START WITH WINDOWS";
  }
  if (els.sysShortcutBtn) {
    els.sysShortcutBtn.textContent = integration.desktop_shortcut
      ? "RECREATE DESKTOP ICON"
      : "CREATE DESKTOP ICON";
  }
  if (els.sysInstallBtn) els.sysInstallBtn.hidden = standalone || !installPrompt;
  if (els.sysInstallHint) {
    els.sysInstallHint.textContent = standalone
      ? "Running in its own window. The desktop icon starts the service and reopens this window."
      : installPrompt
      ? "INSTALL APP adds ADeck to Windows and opens it in its own window."
      : "No install prompt available yet — use your browser menu (Install ADeck), or the desktop icon created by setup.";
  }

  renderPortOptions(system);
  renderSystemBanner();
}

function setSystemBusy(busy) {
  state.backend.busy = !!busy;
  const panel = document.querySelector(".panel-system");
  if (panel) panel.classList.toggle("sys-busy", !!busy);
}

function renderTaskOutput(task) {
  if (!els.sysOutput) return;
  const lines = (task && task.output) || [];
  els.sysOutput.textContent = lines.join("\n");
  els.sysOutput.scrollTop = els.sysOutput.scrollHeight;
  if (!els.sysTaskLabel) return;
  const action = (task && task.action) || (taskWatch && taskWatch.action) || "TASK";
  if (task && task.state === "done") {
    els.sysTaskLabel.textContent =
      action.toUpperCase() + (task.exit_code === 0 ? " — FINISHED OK" : " — FINISHED WITH ERRORS");
  } else if (task && task.state === "unknown") {
    els.sysTaskLabel.textContent = action.toUpperCase() + " — NO LONGER REPORTING";
  } else {
    els.sysTaskLabel.textContent = action.toUpperCase() + " — RUNNING…";
  }
}

function persistTaskWatch(value) {
  try {
    if (value) localStorage.setItem(TASK_WATCH_KEY, JSON.stringify(value));
    else localStorage.removeItem(TASK_WATCH_KEY);
  } catch (_) {}
}

function stopTaskWatch() {
  if (taskWatch && taskWatch.timer) window.clearTimeout(taskWatch.timer);
  taskWatch = null;
}

function finishTaskWatch(task) {
  const action = (taskWatch && taskWatch.action) || (task && task.action) || "task";
  if (taskWatch) taskWatch.finished = true;
  stopTaskWatch();
  persistTaskWatch(null);
  setSystemBusy(false);
  renderTaskOutput(task);
  if (task && task.exit_code === 0) {
    toast(action.toUpperCase().replace(/-/g, " ") + " FINISHED", "success");
  } else {
    toast(action.toUpperCase().replace(/-/g, " ") + " REPORTED PROBLEMS", "error");
  }
  pollBridgeStatus();
  refreshSystem();
}

async function pollTask() {
  if (!taskWatch) return;
  let task = null;
  try {
    const data = await apiGet("/api/tasks/" + encodeURIComponent(taskWatch.id), 5000);
    task = data.task;
  } catch (_) {

  }
  if (!taskWatch) return;
  if (task) {
    renderTaskOutput(task);
    if (task.state === "done" || task.state === "unknown") {
      finishTaskWatch(task);
      return;
    }
  }
  taskWatch.timer = window.setTimeout(pollTask, 1200);
}

function watchTask(taskId, action) {
  stopTaskWatch();
  taskWatch = { id: taskId, action: action, timer: null, finished: false };
  persistTaskWatch({ id: taskId, action: action });
  setSystemBusy(true);
  if (els.sysTaskLabel) els.sysTaskLabel.textContent = action.toUpperCase() + " — RUNNING…";
  if (els.sysOutput) els.sysOutput.textContent = "";
  pollTask();
}

async function resumeTaskWatch() {
  let saved = null;
  try {
    saved = JSON.parse(localStorage.getItem(TASK_WATCH_KEY) || "null");
  } catch (_) {
    saved = null;
  }
  if (!saved || !saved.id) return;
  try {
    const data = await apiGet("/api/tasks/" + encodeURIComponent(saved.id), 5000);
    if (data.task && data.task.state === "running") {
      watchTask(saved.id, data.task.action || saved.action || "task");
      return;
    }
    renderTaskOutput(data.task);
  } catch (_) {

  }
  persistTaskWatch(null);
}

async function runTask(action, options) {
  const settings = options || {};
  if (settings.confirm) {
    const ok = await askConfirm(settings.confirm);
    if (!ok) return;
  }
  if (state.currentPage !== "system" && settings.reveal !== false) showPage("system");
  try {
    const data = await apiPost("/api/control", { action: action });
    if (data.task && data.task.id) {
      watchTask(data.task.id, action);
      toast(action.toUpperCase().replace(/-/g, " ") + " STARTED", "info");
    } else {
      toast(action.toUpperCase() + " STARTED", "info");
    }
  } catch (error) {
    toast("COULD NOT START " + action.toUpperCase() + " — " + error.message, "error");
  }
}

async function stopService() {
  const ok = await askConfirm({
    kicker: "SERVICE",
    title: "STOP ADECK SERVICE",
    message:
      "The board stops responding to key presses and this window loses its connection until ADeck is started again.",
    confirmLabel: "STOP",
    danger: true,
  });
  if (!ok) return;
  try {
    await apiPost("/api/control", { action: "stop" });
    toast("STOPPING ADECK SERVICE", "info");


    state.backend.failures = 2;
    setBackendReachable(false);
  } catch (error) {
    toast("COULD NOT STOP SERVICE — " + error.message, "error");
  }
}

async function reconnectDevice() {
  const port = els.sysPortSelect ? els.sysPortSelect.value : "";
  try {
    const data = await apiPost("/api/control", { action: "reconnect", port: port }, 8000);
    toast((data.message || "RECONNECTING").toUpperCase(), "info");
    window.setTimeout(() => {
      pollBridgeStatus();
      refreshSystem();
    }, 2500);
  } catch (error) {
    toast("RECONNECT FAILED — " + error.message, "error");
  }
}

async function resyncDevice() {
  try {
    const data = await apiPost("/api/control", { action: "resync" }, 12000);
    if (data.sync_state === "synced") toast("DEVICE SYNCHRONIZED", "success");
    else if (data.sync_state === "offline") toast("ADECK IS OFFLINE", "info");
    else toast("SYNC FAILED — " + (data.sync_error || "no acknowledgement"), "error");
    refreshSystem();
  } catch (error) {
    toast("RESYNC FAILED — " + error.message, "error");
  }
}

async function desktopAction(action, successMessage) {
  try {
    await apiPost("/api/control", { action: action }, 25000);
    toast(successMessage, "success");
    refreshSystem();
  } catch (error) {
    toast(action.toUpperCase().replace(/-/g, " ") + " FAILED — " + error.message, "error");
  }
}

async function toggleAutostart() {
  const system = state.backend.system;
  const on = !!(system && system.integration && system.integration.autostart);
  await desktopAction(
    on ? "autostart-off" : "autostart-on",
    on ? "ADECK WILL NOT START WITH WINDOWS" : "ADECK WILL START WITH WINDOWS"
  );
}

async function viewLog() {
  try {
    const data = await apiGet("/api/logs?source=app&lines=200", 8000);
    if (els.sysOutput) {
      els.sysOutput.textContent = (data.lines || []).join("\n") || "The log file is empty.";
      els.sysOutput.scrollTop = els.sysOutput.scrollHeight;
    }
    if (els.sysTaskLabel) els.sysTaskLabel.textContent = "APP LOG — " + data.path;
  } catch (error) {
    toast("COULD NOT READ LOG — " + error.message, "error");
  }
}

function wireSystemEvents() {
  if (els.sysRefreshBtn) {
    els.sysRefreshBtn.addEventListener("click", () => {
      pollBridgeStatus();
      refreshSystem();
      toast("STATUS REFRESHED", "info");
    });
  }
  if (els.sysReconnectBtn) els.sysReconnectBtn.addEventListener("click", reconnectDevice);
  if (els.sysResyncBtn) els.sysResyncBtn.addEventListener("click", resyncDevice);
  if (els.sysPortSelect) {
    els.sysPortSelect.addEventListener("change", (event) => {
      els.sysPortSelect.dataset.pending = event.target.value;
    });
  }
  if (els.sysRestartBtn) {
    els.sysRestartBtn.addEventListener("click", () =>
      runTask("restart", {
        confirm: {
          kicker: "SERVICE",
          title: "RESTART ADECK SERVICE",
          message:
            "The service stops and starts again. This window reconnects automatically after a few seconds.",
          confirmLabel: "RESTART",
        },
      })
    );
  }
  if (els.sysStopBtn) els.sysStopBtn.addEventListener("click", stopService);
  if (els.sysViewLogBtn) els.sysViewLogBtn.addEventListener("click", viewLog);
  if (els.sysLogsBtn) {
    els.sysLogsBtn.addEventListener("click", () =>
      desktopAction("open-logs", "LOG FOLDER OPENED")
    );
  }
  if (els.sysInstallBtn) els.sysInstallBtn.addEventListener("click", promptInstall);
  if (els.sysShortcutBtn) {
    els.sysShortcutBtn.addEventListener("click", () =>
      desktopAction("create-shortcuts", "DESKTOP AND START MENU ICONS CREATED")
    );
  }
  if (els.sysAutostartBtn) els.sysAutostartBtn.addEventListener("click", toggleAutostart);
  if (els.sysCheckBtn) els.sysCheckBtn.addEventListener("click", () => runTask("check"));
  if (els.sysErrorsBtn) els.sysErrorsBtn.addEventListener("click", () => runTask("errors"));
  if (els.sysRepairBtn) {
    els.sysRepairBtn.addEventListener("click", () =>
      runTask("repair", {
        confirm: {
          kicker: "MAINTENANCE",
          title: "INSTALL / REPAIR",
          message:
            "Rebuilds the Python environment and Arduino CLI if needed, reflashes firmware only when the board does not answer, then restarts the service. This can take several minutes.",
          confirmLabel: "RUN REPAIR",
        },
      })
    );
  }
  if (els.sysFirmwareBtn) {
    els.sysFirmwareBtn.addEventListener("click", () =>
      runTask("reinstall-firmware", {
        confirm: {
          kicker: "FIRMWARE",
          title: "REINSTALL FIRMWARE",
          message:
            "Stops the service and reflashes the UNO R4 WiFi. Keep the board plugged in with a data USB cable until it finishes.",
          confirmLabel: "REFLASH",
          danger: true,
        },
      })
    );
  }
  if (els.sysClearOutputBtn) {
    els.sysClearOutputBtn.addEventListener("click", () => {
      if (els.sysOutput) els.sysOutput.textContent = "";
      if (els.sysTaskLabel) els.sysTaskLabel.textContent = "Nothing has been run yet.";
    });
  }
  if (els.offlineRetryBtn) {
    els.offlineRetryBtn.addEventListener("click", () => {
      toast("CHECKING SERVICE", "info");
      pollBridgeStatus();
    });
  }
  if (els.offlineStartBtn) els.offlineStartBtn.addEventListener("click", startService);
}

let installedAppsCache = null;
let installedAppsError = "";
let installedAppsPromise = null;

function isAppPickerOpen() {
  return !!(els.appPickerModal && !els.appPickerModal.hidden);
}

function closeAppPicker() {
  if (!els.appPickerModal) return;
  els.appPickerModal.hidden = true;
}

function matchesPickerQuery(text, query) {
  if (!query) return true;
  return String(text || "").toLowerCase().includes(query);
}

function pickerItemIcon(item) {
  const icon = document.createElement("span");
  icon.className = "app-picker-icon";
  icon.setAttribute("aria-hidden", "true");
  if (item.kind === "app") {
    const img = document.createElement("img");
    img.alt = "";
    img.decoding = "async";
    img.loading = "lazy";
    img.src =
      localBridge + "/api/app-icon?command=" + encodeURIComponent(item.command);
    img.addEventListener("error", () => {
      img.remove();
      icon.classList.add("is-fallback");
    });
    icon.appendChild(img);
  } else {
    icon.classList.add("is-command");
  }
  return icon;
}

function renderPickerList(container, items, emptyText) {
  if (!container) return;
  container.innerHTML = "";
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "app-picker-empty mono";
    empty.textContent = emptyText;
    container.appendChild(empty);
    return;
  }
  items.forEach((item) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "app-picker-item";
    btn.setAttribute("role", "option");
    btn.title = item.command;
    const text = document.createElement("span");
    text.className = "app-picker-item-text";
    const name = document.createElement("span");
    name.className = "app-picker-item-name";
    name.textContent = item.name;
    const cmd = document.createElement("span");
    cmd.className = "app-picker-item-cmd mono";
    cmd.textContent = item.command;
    text.appendChild(name);
    text.appendChild(cmd);
    btn.appendChild(pickerItemIcon(item));
    btn.appendChild(text);
    btn.addEventListener("click", () => applyPickerItem(item));
    container.appendChild(btn);
  });
}

function renderAppPickerLists() {
  const query = String((els.appPickerSearch && els.appPickerSearch.value) || "")
    .trim()
    .toLowerCase();
  const commands = COMMON_COMMANDS.filter(
    (item) =>
      matchesPickerQuery(item.name, query) || matchesPickerQuery(item.command, query)
  );
  const apps = (installedAppsCache || []).filter(
    (item) =>
      matchesPickerQuery(item.name, query) || matchesPickerQuery(item.command, query)
  );
  renderPickerList(els.appPickerCommands, commands, "NO MATCHING COMMANDS");
  renderPickerList(
    els.appPickerApps,
    apps,
    installedAppsCache ? "NO MATCHING APPS" : "LOADING APPS…"
  );
  if (els.appPickerStatus) {
    if (installedAppsError && !(installedAppsCache && installedAppsCache.length)) {
      els.appPickerStatus.hidden = false;
      els.appPickerStatus.textContent =
        "APP DISCOVERY FAILED — TYPE A COMMAND / PATH MANUALLY";
    } else {
      els.appPickerStatus.hidden = true;
      els.appPickerStatus.textContent = "";
    }
  }
}

async function loadInstalledApps() {
  if (installedAppsCache) {
    renderAppPickerLists();
    return installedAppsCache;
  }
  if (installedAppsPromise) return installedAppsPromise;
  installedAppsPromise = (async () => {
    try {
      const response = await fetchWithTimeout(
        localBridge + "/api/apps",
        { cache: "no-store" },
        12000
      );
      const data = await response.json().catch(() => ({}));
      const apps = Array.isArray(data.apps) ? data.apps : [];
      installedAppsCache = apps
        .map((item) => ({
          kind: "app",
          name: String(item.name || "").trim(),
          command: String(item.command || "").trim(),
        }))
        .filter((item) => item.name && item.command);
      installedAppsError = String(data.error || "");
      if (!response.ok) {
        installedAppsError = installedAppsError || "Could not load installed apps";
      }
    } catch (error) {
      installedAppsCache = installedAppsCache || [];
      installedAppsError = error && error.message ? error.message : "Could not load installed apps";
    } finally {
      installedAppsPromise = null;
      if (isAppPickerOpen()) renderAppPickerLists();
    }
    return installedAppsCache;
  })();
  return installedAppsPromise;
}

async function applyPickerItem(item) {
  const s = activeSlot();
  if (!s || !item || !item.command) return;
  s.command = String(item.command).slice(0, COMMAND_MAX);
  s.kind = item.kind === "app" ? "app" : "command";
  const nextLabel = item.label || pickerLabel(item.name);
  if (nextLabel) s.label = nextLabel.slice(0, LABEL_MAX);
  if (s.kind === "app") {
    await refreshSlotIconColor(s);
  } else {
    s.color = DEFAULT_COLOR;
  }
  closeAppPicker();
  renderEditor();
  renderGrid();
  renderProfiles();
  markDirty(true);
  persistProfiles();
  toast(s.kind === "app" ? "APP SELECTED" : "COMMAND SELECTED", "success");
}

function openAppPicker() {
  if (!activeSlot() || !els.appPickerModal) return;
  els.appPickerModal.hidden = false;
  if (els.appPickerSearch) {
    els.appPickerSearch.value = "";
    els.appPickerSearch.focus();
  }
  renderAppPickerLists();
  loadInstalledApps();
}

function wireEvents() {
  els.navBtns.forEach((btn) => btn.addEventListener("click", () => showPage(btn.dataset.page)));
  els.gotoBtns.forEach((btn) => btn.addEventListener("click", () => showPage(btn.dataset.goto)));

  els.editorForm.addEventListener("submit", (e) => e.preventDefault());
  if (els.settingsForm) els.settingsForm.addEventListener("submit", (e) => e.preventDefault());

  els.addProfileBtn.addEventListener("click", addProfile);
  els.renameProfileBtn.addEventListener("click", renameProfile);
  els.duplicateProfileBtn.addEventListener("click", duplicateProfile);
  els.deleteProfileBtn.addEventListener("click", deleteProfile);
  els.exportProfileBtn.addEventListener("click", exportActiveProfile);
  if (els.themeBtn) els.themeBtn.addEventListener("click", openThemeModal);
  if (els.rotateBtn) els.rotateBtn.addEventListener("click", cycleActiveRotation);
  if (els.themeApplyBtn) els.themeApplyBtn.addEventListener("click", applySelectedTheme);
  if (els.themeCancelBtn) els.themeCancelBtn.addEventListener("click", closeThemeModal);
  if (els.themeModal) {
    els.themeModal.addEventListener("click", (e) => {
      if (e.target === els.themeModal) closeThemeModal();
    });
  }
  els.importProfileBtn.addEventListener("click", () => els.importProfileFile.click());
  els.importProfileFile.addEventListener("change", async (e) => {
    const file = e.target.files && e.target.files[0];
    e.target.value = "";
    if (file) await importProfileFromFile(file);
  });
  els.profileSearch.addEventListener("input", (e) => {
    state.profileFilter = e.target.value;
    renderProfiles();
  });

  els.labelInput.addEventListener("input", (e) => {
    const s = activeSlot();
    if (!s) return;
    s.label = e.target.value.slice(0, LABEL_MAX);
    if (e.target.value !== s.label) e.target.value = s.label;
    els.labelCount.textContent = String(s.label.length);
    els.slotInfoState.textContent = !s.label && !s.command ? "EMPTY" : "CONFIGURED";
    afterSlotFieldEdit();
  });

  els.commandInput.addEventListener("input", (e) => {
    const s = activeSlot();
    if (!s) return;
    s.command = e.target.value.slice(0, COMMAND_MAX);
    if (e.target.value !== s.command) e.target.value = s.command;
    s.kind = "";
    els.commandCount.textContent = String(s.command.length);
    updateCommandKindUI(s.command, s.kind);
    const v = validateCommand(s.command);
    els.commandError.hidden = v.ok;
    els.commandError.textContent = v.message;
    els.commandInput.classList.toggle("invalid", !v.ok);
    afterSlotFieldEdit();
  });

  els.commandInput.addEventListener("change", async () => {
    const s = activeSlot();
    if (!s) return;
    const kind = detectCommandKind(s.command);
    if (s.command && (kind === "path" || /\.(exe|lnk|app)$/i.test(s.command))) {
      s.kind = "app";
      await refreshSlotIconColor(s);
    } else if (!s.command) {
      s.color = DEFAULT_COLOR;
    }
    updateCommandKindUI(s.command, s.kind);
    renderEditor();
    renderGrid();
    persistProfiles();
  });

  els.customColorBtn.addEventListener("click", () => {
    if (els.customColorBtn.disabled) return;
    els.customColorInput.click();
  });
  els.customColorInput.addEventListener("input", (e) => applyColor(e.target.value));
  els.customColorInput.addEventListener("change", (e) => applyColor(e.target.value));

  els.clearSlotBtn.addEventListener("click", () => clearActiveSlot(false));
  if (els.appPickerBtn) els.appPickerBtn.addEventListener("click", openAppPicker);
  if (els.appPickerCloseBtn) els.appPickerCloseBtn.addEventListener("click", closeAppPicker);
  if (els.appPickerSearch) {
    els.appPickerSearch.addEventListener("input", renderAppPickerLists);
  }
  if (els.appPickerModal) {
    els.appPickerModal.addEventListener("click", (e) => {
      if (e.target === els.appPickerModal) closeAppPicker();
    });
  }
  els.saveBtn.addEventListener("click", saveConfig);
  els.closeModalBtn.addEventListener("click", closeJsonModal);
  els.formatJsonBtn.addEventListener("click", formatJsonInModal);
  els.validateJsonBtn.addEventListener("click", validateJsonInModal);
  els.copyJsonBtn.addEventListener("click", copyJson);
  els.downloadJsonBtn.addEventListener("click", downloadJson);
  els.importJsonBtn.addEventListener("click", () => els.importJsonFile.click());
  els.importJsonFile.addEventListener("change", async (e) => {
    const file = e.target.files && e.target.files[0];
    e.target.value = "";
    if (file) await importConfigFromFile(file);
  });
  els.jsonOutput.addEventListener("input", updateJsonMeta);
  els.jsonModal.addEventListener("click", (e) => {
    if (e.target === els.jsonModal) closeJsonModal();
  });

  els.dialogCancel.addEventListener("click", () => closeDialog(dialogState && dialogState.mode === "prompt" ? null : false));
  els.dialogConfirm.addEventListener("click", () => {
    if (!dialogState) return;
    if (dialogState.mode === "prompt") closeDialog(els.dialogInput.value);
    else closeDialog(true);
  });
  els.dialogInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      closeDialog(els.dialogInput.value);
    }
  });

  els.settingBrightness.addEventListener("input", (e) => {
    els.brightnessVal.textContent = e.target.value + "%";
  });
  els.settingsSaveBtn.addEventListener("click", saveSettings);
  els.settingsResetBtn.addEventListener("click", resetSettings);
  if (els.themeToggleBtn) els.themeToggleBtn.addEventListener("click", toggleTheme);
  if (els.appearanceBtn) els.appearanceBtn.addEventListener("click", openAppearanceModal);
  if (els.appearanceApplyBtn) els.appearanceApplyBtn.addEventListener("click", applySelectedAppearance);
  if (els.appearanceCancelBtn) els.appearanceCancelBtn.addEventListener("click", closeAppearanceModal);
  if (els.appearanceModal) {
    els.appearanceModal.addEventListener("click", (e) => {
      if (e.target === els.appearanceModal) closeAppearanceModal();
    });
  }
  if (els.settingTheme) {
    els.settingTheme.addEventListener("change", (e) => {
      applyTheme(e.target.value);
      persistSettings();
      toast(e.target.value === "dark" ? "DARK MODE" : "LIGHT MODE", "info");
    });
  }
  if (els.settingAppearance) {
    els.settingAppearance.addEventListener("change", (e) => {
      applyAppearance(e.target.value);
    });
  }

  document.addEventListener("keydown", onGlobalKeydown);
}

function onGlobalKeydown(e) {
  if (e.key === "Escape") {
    if (isDialogOpen()) {
      e.preventDefault();
      closeDialog(dialogState.mode === "prompt" ? null : false);
      return;
    }
    if (!els.jsonModal.hidden) {
      e.preventDefault();
      closeJsonModal();
      return;
    }
    if (themeModal.open) {
      e.preventDefault();
      closeThemeModal();
      return;
    }
    if (appearanceModal.open) {
      e.preventDefault();
      closeAppearanceModal();
      return;
    }
    if (isAppPickerOpen()) {
      e.preventDefault();
      closeAppPicker();
      return;
    }
  }
  if (isDialogOpen()) return;
  if ((e.ctrlKey || e.metaKey) && (e.key === "s" || e.key === "S")) {
    e.preventDefault();
    saveConfig();
    return;
  }
  if ((e.ctrlKey || e.metaKey) && (e.key === "n" || e.key === "N")) {
    if (state.currentPage === "dashboard" && !isTypingTarget(e.target)) {
      e.preventDefault();
      addProfile();
    }
    return;
  }
  if (state.currentPage !== "dashboard") return;
  if (!els.jsonModal.hidden) return;
  if (isTypingTarget(e.target)) return;

  if (
    e.key === "ArrowUp" ||
    e.key === "ArrowDown" ||
    e.key === "ArrowLeft" ||
    e.key === "ArrowRight"
  ) {
    e.preventDefault();
    moveSlotSelection(e.key);
    return;
  }
  if (e.key === "Delete") {
    e.preventDefault();
    clearActiveSlot(false);
  }
}

function tickClock() {
  els.clock.textContent = formatTime(new Date());
}

async function boot() {
  loadSettings();
  await loadThemes();
  const hadLocalConfig = loadProfiles();
  if (!hadLocalConfig) seed();
  const backend = await fetchConfigFromBridge();
  if (backend.ok && backend.has_config) {
    hydrateConfig(backend.config);
  } else if (backend.ok && !backend.has_config && hadLocalConfig) {
    await postConfigToBridge(buildConfigObject());
  }
  if (state.settings.deviceName) state.device.name = state.settings.deviceName;
  if (!state.settings.defaultProfileId) state.settings.defaultProfileId = state.activeProfileId;
  state.device.connected = false;
  state.device.port = "NOT CONNECTED";
  state.device.firmware = "—";
  applyTheme(state.settings.theme || "light", false);
  renderAll();
  renderAbout();
  markDirty(false);
  wireEvents();
  wireSystemEvents();
  setupInstallPrompt();
  showPage("dashboard");
  setInterval(tickClock, 1000);
  setInterval(pollBridgeStatus, 2000);
  let systemTick = 0;
  setInterval(() => {
    if (!state.backend.reachable) return;
    systemTick += 1;

    if (state.currentPage === "system" || systemTick % 3 === 0) refreshSystem();
  }, 5000);
  tickClock();
  await pollBridgeStatus();
  await refreshSystem();
  await resumeTaskWatch();
  registerServiceWorker();
}

boot();
