"use strict";

let toastTimer = null;
const TOAST_LIFE = 3000;
const TOAST_OUT = 240;

function dismissToast(node) {
  if (!node || !node.parentNode || node.classList.contains("is-leaving")) return;
  if (toastTimer) {
    clearTimeout(toastTimer);
    toastTimer = null;
  }
  node.classList.add("is-leaving");
  setTimeout(() => {
    if (node.parentNode) node.remove();
  }, TOAST_OUT);
}

function toast(message, type) {
  if (!els.toastHost) return;
  if (toastTimer) {
    clearTimeout(toastTimer);
    toastTimer = null;
  }
  const existing = els.toastHost.querySelector(".toast");
  const mount = () => {
    els.toastHost.innerHTML = "";
    const node = document.createElement("div");
    node.className = "toast " + (type || "info");
    node.setAttribute("role", "status");

    const msg = document.createElement("span");
    msg.className = "toast-msg";
    msg.textContent = message;

    const close = document.createElement("button");
    close.type = "button";
    close.className = "toast-close";
    close.setAttribute("aria-label", "Dismiss");
    close.textContent = "×";
    close.addEventListener("click", () => dismissToast(node));

    node.appendChild(msg);
    node.appendChild(close);
    els.toastHost.appendChild(node);
    toastTimer = setTimeout(() => dismissToast(node), TOAST_LIFE);
  };

  if (existing) {
    existing.classList.add("is-leaving");
    setTimeout(mount, 180);
  } else {
    mount();
  }
}

function closeDialog(result) {
  if (!dialogState) return;
  const finish = dialogState.finish;
  dialogState = null;
  els.appDialog.hidden = true;
  finish(result);
}

function showDialog(options) {
  const mode = options.mode === "prompt" ? "prompt" : "confirm";
  return new Promise((resolve) => {
    dialogState = {
      mode,
      finish: resolve,
    };

    if (options.kicker === "") {
      els.dialogKicker.hidden = true;
    } else {
      els.dialogKicker.hidden = false;
      els.dialogKicker.textContent = options.kicker || (mode === "prompt" ? "INPUT" : "CONFIRM");
    }
    els.dialogTitle.textContent = options.title || "—";
    els.dialogMessage.textContent = options.message || "";
    els.dialogMessage.hidden = !(options.message || "");

    const isPrompt = mode === "prompt";
    els.dialogInputWrap.hidden = !isPrompt;
    if (!isPrompt) els.dialogInput.value = "";
    if (isPrompt) {
      els.dialogInputLabel.textContent = options.inputLabel || "VALUE";
      els.dialogInput.maxLength = options.maxLength || 255;
      els.dialogInput.value = options.defaultValue != null ? String(options.defaultValue) : "";
    }

    els.dialogCancel.hidden = options.hideCancel === true;
    els.dialogConfirm.textContent = options.confirmLabel || (isPrompt ? "OK" : "CONFIRM");
    els.dialogConfirm.className = options.danger ? "ghost-btn danger" : "save-btn";

    els.appDialog.hidden = false;
    requestAnimationFrame(() => {
      if (isPrompt) {
        els.dialogInput.focus();
        els.dialogInput.select();
      } else {
        els.dialogConfirm.focus();
      }
    });
  });
}

function askConfirm(options) {
  return showDialog({ ...options, mode: "confirm" }).then((ok) => !!ok);
}

function askPrompt(options) {
  return showDialog({ ...options, mode: "prompt" }).then((value) => {
    if (value === null || value === false) return null;
    return String(value);
  });
}

function isDialogOpen() {
  return !!dialogState;
}

const localBridge =
  /^https?:$/.test(window.location.protocol) &&
  ["127.0.0.1", "localhost"].includes(window.location.hostname)
    ? window.location.origin
    : "http://127.0.0.1:8765";

async function fetchWithTimeout(url, options, timeoutMs) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...(options || {}), signal: controller.signal });
  } finally {
    window.clearTimeout(timer);
  }
}

async function postConfigToBridge(config) {
  try {
    const res = await fetchWithTimeout(
      localBridge + "/api/config",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(config),
      },
      7000
    );
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.ok) {
      return {
        ok: false,
        reachable: true,
        error: data.error || "Could not save config",
      };
    }
    return { ...data, reachable: true };
  } catch (error) {
    return { ok: false, reachable: false, error: error.message };
  }
}

async function fetchConfigFromBridge() {
  try {
    const response = await fetchWithTimeout(
      localBridge + "/api/config",
      { cache: "no-store" },
      2500
    );
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) {
      return { ok: false, reachable: true, error: data.error || "Could not load config" };
    }
    return { ...data, reachable: true };
  } catch (error) {
    return { ok: false, reachable: false, error: error.message };
  }
}

function syncWasAcknowledged(result) {
  return (
    result.sync_state === "synced" &&
    !!result.transaction_id &&
    result.acknowledged_transaction_id === result.transaction_id
  );
}


async function saveConfig() {
  const config = buildConfigObject();
  persistProfiles();
  els.statusLine.textContent = "SAVING";

  const result = await postConfigToBridge(config);
  if (!result.ok) {
    if (state.storageOk) {
      markDirty(false);
      toast(
        result.reachable ? "SAVED LOCALLY — BACKEND REJECTED" : "SAVED LOCALLY — SERVICE OFFLINE",
        result.reachable ? "error" : "info"
      );
    } else {
      markDirty(true);
      toast("SAVE FAILED", "error");
    }
    return;
  }

  markDirty(false);
  if (syncWasAcknowledged(result)) {
    toast("SAVED — SYNCHRONIZED", "success");
  } else if (result.sync_state === "offline") {
    toast("SAVED — ADECK OFFLINE", "info");
  } else {
    toast("SAVED — SYNC FAILED", "error");
  }
  pollBridgeStatus();
}

let profileSyncChain = Promise.resolve();

function syncActiveProfile() {
  const config = buildConfigObject();
  profileSyncChain = profileSyncChain.then(async () => {
    const result = await postConfigToBridge(config);
    if (!result.ok) {
      toast(
        result.reachable ? "PROFILE SAVE REJECTED" : "PROFILE SAVED LOCALLY — SERVICE OFFLINE",
        result.reachable ? "error" : "info"
      );
    } else if (syncWasAcknowledged(result)) {
      toast("PROFILE SYNCHRONIZED", "success");
    } else if (result.sync_state === "offline") {
      toast("PROFILE SAVED — ADECK OFFLINE", "info");
    } else {
      toast("PROFILE SAVED — SYNC FAILED", "error");
    }
    pollBridgeStatus();
  });
  return profileSyncChain;
}

async function pollBridgeStatus() {
  let status = null;
  try {
    const response = await fetchWithTimeout(
      localBridge + "/api/status",
      { cache: "no-store" },
      2000
    );
    if (!response.ok) throw new Error("Bridge unavailable");
    status = await response.json();
    state.device.connected = !!status.connected;
    state.device.port = status.port || "NOT CONNECTED";
    state.device.firmware = status.firmware || "—";
    state.backend.status = status;
    setBackendReachable(true);
  } catch (_) {
    state.device.connected = false;
    state.device.port = "NOT CONNECTED";
    state.device.firmware = "—";
    setBackendReachable(false);
  }
  renderDeviceMeta();
  if (state.currentPage === "system") renderSystem();
  return status;
}

function updateStatusBar() {
  const p = activeProfile();
  const offline = state.backend && !state.backend.reachable;
  els.footerDirty.textContent = state.dirty ? "UNSAVED" : "SAVED";
  els.footerDirty.classList.toggle("dirty", state.dirty);
  els.footerProfile.textContent = p ? p.name : "—";
  if (els.statusLine) {
    els.statusLine.textContent = offline ? "SERVICE OFF" : state.dirty ? "EDITING" : "READY";
  }
  if (els.topStateDot) {
    els.topStateDot.classList.toggle("warn", state.dirty && !offline);
    els.topStateDot.classList.toggle("bad", !!offline);
  }
  if (els.profileCount) els.profileCount.textContent = String(state.profiles.length);
}

function renderDeviceMeta() {
  const d = state.device;
  const p = activeProfile();
  const s = activeSlot();
  const online = !!d.connected;
  if (els.deviceConnBadge) {
    els.deviceConnBadge.textContent = online ? "ONLINE" : "OFFLINE";
    els.deviceConnBadge.classList.toggle("offline", !online);
  }
  if (els.screenActiveKey) {
    els.screenActiveKey.textContent = s != null ? "K" + pad2(s.index + 1) : "K—";
  }
  if (els.screenProfileName) {
    els.screenProfileName.textContent = p ? p.name.toUpperCase().slice(0, 16) : "—";
  }

  if (els.deviceScreen) {
    els.deviceScreen.style.background = profileBackground(p);
  }
  updateRotationUi();
}

function renderProfiles() {
  const filter = state.profileFilter.trim().toLowerCase();
  els.profileList.innerHTML = "";
  let visible = 0;

  state.profiles.forEach((p, i) => {
    if (filter && !p.name.toLowerCase().includes(filter)) return;
    visible += 1;

    const li = document.createElement("li");
    li.dataset.id = p.id;
    li.setAttribute("role", "option");
    li.setAttribute("aria-selected", p.id === state.activeProfileId ? "true" : "false");
    li.tabIndex = 0;
    if (p.id === state.activeProfileId) li.classList.add("active");

    const keys = configuredKeyCount(p);
    li.innerHTML =
      '<span class="p-idx">' + pad2(i + 1) + "</span>" +
      '<span class="p-body"><span class="p-name">' + escapeHtml(p.name) + "</span>" +
      '<span class="p-meta">' + keys + " / " + SLOTS_PER_PROFILE + " KEYS</span></span>" +
      '<span class="p-state">' + (p.id === state.activeProfileId ? "ACTIVE" : "IDLE") + "</span>";

    const select = () => {
      if (state.activeProfileId === p.id) return;
      state.activeProfileId = p.id;
      state.activeSlotIndex = 0;
      renderAll();
      persistProfiles();
      syncActiveProfile();
    };
    li.addEventListener("click", select);
    li.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        select();
      }
    });
    els.profileList.appendChild(li);
  });

  if (visible === 0) {
    const empty = document.createElement("li");
    empty.className = "empty-state";
    empty.innerHTML = filter
      ? "<strong>NO MATCHES</strong> Try another profile name."
      : "<strong>NO PROFILES</strong> Create your first configuration profile.";
    els.profileList.appendChild(empty);
  }
  updateStatusBar();
}

function renderGrid() {
  const p = activeProfile();
  els.buttonGrid.innerHTML = "";
  if (!p) return;
  applyPreviewOrientation(els.buttonGrid, p.rotation);

  p.slots.forEach((slot) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "slot";
    btn.setAttribute(
      "aria-label",
      "Key " + (slot.index + 1) + (slot.label ? ": " + slot.label : " empty")
    );
    if (!slot.label && !slot.command) btn.classList.add("empty");
    if (slot.index === state.activeSlotIndex) {
      btn.classList.add("active");
      btn.setAttribute("aria-pressed", "true");
    } else {
      btn.setAttribute("aria-pressed", "false");
    }
    btn.style.background = slot.color;
    btn.style.color = pickTextColor(slot.color);

    const idx = document.createElement("div");
    idx.className = "slot-idx";
    idx.textContent = pad2(slot.index + 1);

    const activeTag = document.createElement("div");
    activeTag.className = "slot-active-tag";
    activeTag.textContent = "ACTIVE";

    const lbl = document.createElement("div");
    lbl.className = "slot-label";
    lbl.textContent = slot.label || "EMPTY";

    btn.appendChild(idx);
    btn.appendChild(activeTag);
    btn.appendChild(lbl);

    btn.addEventListener("click", () => {
      state.activeSlotIndex = slot.index;
      refreshSlotUI();
      persistProfiles();
    });
    els.buttonGrid.appendChild(btn);
  });
}

function updateBackgroundPicker(hex) {
  const value = hex ? normalizeHex(hex) : DEFAULT_BACKGROUND;
  if (els.customColorBtn) {
    els.customColorBtn.style.setProperty("--picked-color", value);
  }
  if (els.bgColorSwatch) {
    els.bgColorSwatch.style.background = value;
  }
  if (els.customColorInput) {
    els.customColorInput.value = value;
  }
}


function applyColor(hex) {
  const p = activeProfile();
  if (!p) return;
  p.background = normalizeHex(hex);
  updateBackgroundPicker(p.background);
  renderGrid();
  renderEditor();
  renderDeviceMeta();
  markDirty(true);
  persistProfiles();
}

async function refreshSlotIconColor(slot) {
  if (!slot) return;
  const command = String(slot.command || "").trim();
  if (!command || slot.kind !== "app") {
    if (!command) slot.color = DEFAULT_COLOR;
    return;
  }
  try {
    const res = await fetchWithTimeout(
      "/api/app-color?command=" + encodeURIComponent(command),
      {},
      6000
    );
    if (!res || !res.ok) return;
    const data = await res.json();
    if (data && data.color) {
      slot.color = normalizeHex(data.color);
    }
  } catch (_) {

  }
}

function renderEditor() {
  const s = activeSlot();
  const p = activeProfile();
  const disabled = !s;

  els.labelInput.disabled = disabled;
  els.commandInput.disabled = disabled;
  if (els.appPickerBtn) els.appPickerBtn.disabled = disabled;
  els.clearSlotBtn.disabled = disabled;

  if (els.customColorBtn) els.customColorBtn.disabled = !p;
  els.editorForm.classList.toggle("is-disabled", disabled);

  if (!s || !p) {
    els.activeSlotTag.textContent = "—";
    els.slotInfoKey.textContent = "—";
    els.slotInfoState.textContent = "—";
    els.slotInfoState.className = "slot-state-badge mono";
    els.labelInput.value = "";
    els.commandInput.value = "";
    els.labelCount.textContent = "0";
    els.commandCount.textContent = "0";
    els.commandError.hidden = true;
    updateCommandKindUI("", "");
    updateBackgroundPicker(p ? profileBackground(p) : null);
    return;
  }

  const isEmpty = !s.label && !s.command;
  els.activeSlotTag.textContent = p.name.toUpperCase().slice(0, 12) + " / " + pad2(s.index + 1);
  els.slotInfoKey.textContent = pad2(s.index + 1);
  els.slotInfoState.textContent = isEmpty ? "EMPTY" : "CONFIGURED";
  els.slotInfoState.className =
    "slot-state-badge mono " + (isEmpty ? "is-empty" : "is-configured");
  const label = String(s.label || "").slice(0, LABEL_MAX);
  const command = String(s.command || "").slice(0, COMMAND_MAX);
  if (label !== s.label || command !== s.command) {
    s.label = label;
    s.command = command;
  }
  els.labelInput.value = label;
  els.commandInput.value = command;
  els.labelCount.textContent = String(label.length);
  els.commandCount.textContent = String(command.length);
  updateCommandKindUI(command, s.kind);

  const v = validateCommand(command);
  els.commandError.hidden = v.ok;
  els.commandError.textContent = v.message;
  els.commandInput.classList.toggle("invalid", !v.ok);
  updateBackgroundPicker(profileBackground(p));
  updateStatusBar();
}

const SLEEP_IMAGE_W = 128;
const SLEEP_IMAGE_H = 96;

function paintSleepPreview(hex) {
  const canvas = els.sleepImagePreview;
  if (!canvas || !canvas.getContext) return;
  const text = String(hex || "").trim().toUpperCase();
  if (text.length !== SLEEP_IMAGE_W * SLEEP_IMAGE_H * 4) return;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#000000";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  const scaleX = canvas.width / SLEEP_IMAGE_W;
  const scaleY = canvas.height / SLEEP_IMAGE_H;
  for (let y = 0; y < SLEEP_IMAGE_H; y++) {
    for (let x = 0; x < SLEEP_IMAGE_W; x++) {
      const i = (y * SLEEP_IMAGE_W + x) * 4;
      const rgb = parseInt(text.slice(i, i + 4), 16);
      if (Number.isNaN(rgb)) return;
      const r = ((rgb >> 11) & 31) * 8;
      const g = ((rgb >> 5) & 63) * 4;
      const b = (rgb & 31) * 8;
      ctx.fillStyle = "rgb(" + r + "," + g + "," + b + ")";
      ctx.fillRect(x * scaleX, y * scaleY, scaleX, scaleY);
    }
  }
}

function updateSleepImageUi() {
  const custom = !!(els.settingSleepMode && els.settingSleepMode.value === "image");
  const hex = String(state.settings.sleepImage || "").trim();
  const hasImage = custom && hex.length === SLEEP_IMAGE_W * SLEEP_IMAGE_H * 4;
  if (els.sleepImageField) els.sleepImageField.hidden = !custom;
  if (els.sleepImagePreview) {
    els.sleepImagePreview.hidden = !hasImage;
    if (hasImage) paintSleepPreview(hex);
  }
  if (els.sleepImagePickBtn) els.sleepImagePickBtn.textContent = hasImage ? "CHANGE IMAGE" : "ADD IMAGE";
}

function encodeSleepImageFile(file) {
  return new Promise((resolve, reject) => {
    if (!file) {
      reject(new Error("No file"));
      return;
    }
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      URL.revokeObjectURL(url);
      const canvas = document.createElement("canvas");
      canvas.width = SLEEP_IMAGE_W;
      canvas.height = SLEEP_IMAGE_H;
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = "#000000";
      ctx.fillRect(0, 0, SLEEP_IMAGE_W, SLEEP_IMAGE_H);
      const scale = Math.max(SLEEP_IMAGE_W / img.width, SLEEP_IMAGE_H / img.height);
      const w = img.width * scale;
      const h = img.height * scale;
      ctx.drawImage(img, (SLEEP_IMAGE_W - w) / 2, (SLEEP_IMAGE_H - h) / 2, w, h);
      const data = ctx.getImageData(0, 0, SLEEP_IMAGE_W, SLEEP_IMAGE_H).data;
      let hex = "";
      for (let i = 0; i < data.length; i += 4) {
        const r = data[i] >> 3;
        const g = data[i + 1] >> 2;
        const b = data[i + 2] >> 3;
        const rgb = (r << 11) | (g << 5) | b;
        hex += rgb.toString(16).padStart(4, "0");
      }
      resolve(hex.toUpperCase());
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Bad image"));
    };
    img.src = url;
  });
}

async function onSleepImagePicked(file) {
  try {
    state.settings.sleepMode = "image";
    if (els.settingSleepMode) els.settingSleepMode.value = "image";
    state.settings.sleepImage = await encodeSleepImageFile(file);
    persistSettings();
    updateSleepImageUi();
    toast("SLEEP IMAGE READY — SAVE SETTINGS", "info");
  } catch (_) {
    toast("SLEEP IMAGE FAILED", "error");
  }
}

function renderSettingsForm() {
  const s = state.settings;
  els.settingTheme.value = s.theme || "light";
  if (els.settingAppearance) els.settingAppearance.value = normalizeAppearance(s.appearance);
  els.settingDeviceName.value = s.deviceName || "";
  els.settingSleep.value = String(s.sleepTimeout ?? "60");
  if (els.settingSleepMode) {
    els.settingSleepMode.value = s.sleepMode === "image" ? "image" : "black";
  }
  updateSleepImageUi();
  if (els.settingAppRelaunch) {
    els.settingAppRelaunch.value =
      s.appRelaunchMode === "minimize" || s.appRelaunchMode === "close"
        ? s.appRelaunchMode
        : "new";
  }
  els.settingDefaultProfile.innerHTML = "";
  state.profiles.forEach((p) => {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.textContent = p.name;
    els.settingDefaultProfile.appendChild(opt);
  });
  const defId = s.defaultProfileId || state.activeProfileId;
  if (state.profiles.some((p) => p.id === defId)) els.settingDefaultProfile.value = defId;
}

function renderAbout() {
  if (els.aboutVersion) els.aboutVersion.textContent = APP_VERSION;
  if (els.aboutBuild) els.aboutBuild.textContent = BUILD_NUMBER;
}

function renderAll() {
  renderProfiles();
  renderGrid();
  renderEditor();
  renderDeviceMeta();
  applyActiveDeckTheme();
  updateStatusBar();
}

function showPage(pageId) {
  const id = pageId || "dashboard";
  state.currentPage = id;
  els.pages.forEach((page) => {
    page.hidden = page.dataset.page !== id;
  });
  els.navBtns.forEach((btn) => {
    const active = btn.dataset.page === id;
    btn.classList.toggle("active", active);
    if (active) btn.setAttribute("aria-current", "page");
    else btn.removeAttribute("aria-current");
  });
  if (id === "settings") renderSettingsForm();
  if (id === "about") renderAbout();
  if (id === "system") {
    renderSystem();
    refreshSystem();
  }
}

async function addProfile() {
  const name = await askPrompt({
    kicker: "",
    title: "NEW PROFILE",
    message: "Name this workspace profile.",
    defaultValue: "Profile " + (state.profiles.length + 1),
    maxLength: PROFILE_NAME_MAX,
    inputLabel: "PROFILE NAME",
    confirmLabel: "CREATE",
  });
  if (name === null) return;
  const profileName = name.trim().slice(0, PROFILE_NAME_MAX) || "Untitled";
  if (profileNameExists(profileName)) {
    toast("PROFILE NAME ALREADY EXISTS", "error");
    return;
  }
  const p = makeProfile(profileName);
  state.profiles.push(p);
  state.activeProfileId = p.id;
  state.activeSlotIndex = 0;
  renderAll();
  markDirty(true);
  persistProfiles();
  toast('PROFILE "' + p.name.toUpperCase() + '" CREATED', "success");
}

async function renameProfile() {
  const p = activeProfile();
  if (!p) return;
  const name = await askPrompt({
    kicker: "",
    title: "RENAME PROFILE",
    message: "Update the active profile name.",
    defaultValue: p.name,
    maxLength: PROFILE_NAME_MAX,
    inputLabel: "PROFILE NAME",
    confirmLabel: "RENAME",
  });
  if (name === null) return;
  const profileName = name.trim().slice(0, PROFILE_NAME_MAX) || p.name;
  if (profileNameExists(profileName, p.id)) {
    toast("PROFILE NAME ALREADY EXISTS", "error");
    return;
  }
  p.name = profileName;
  renderProfiles();
  renderEditor();
  renderDeviceMeta();
  markDirty(true);
  persistProfiles();
  toast("PROFILE RENAMED", "success");
}

function duplicateProfile() {
  const p = activeProfile();
  if (!p) return;
  const copy = cloneProfile(p, uniqueProfileName(p.name + " Copy"));
  state.profiles.push(copy);
  state.activeProfileId = copy.id;
  state.activeSlotIndex = 0;
  renderAll();
  markDirty(true);
  persistProfiles();
  toast('DUPLICATED AS "' + copy.name.toUpperCase() + '"', "success");
}

async function deleteProfile() {
  if (state.profiles.length <= 1) {
    toast("CANNOT DELETE LAST PROFILE", "error");
    return;
  }
  const p = activeProfile();
  if (!p) return;
  const ok = await askConfirm({
    kicker: "",
    title: "DELETE PROFILE",
    message: "Remove this profile from your workspace? This cannot be undone.",
    confirmLabel: "DELETE",
    danger: true,
  });
  if (!ok) return;
  state.profiles = state.profiles.filter((x) => x.id !== p.id);
  state.activeProfileId = state.profiles[0].id;
  state.activeSlotIndex = 0;
  renderAll();
  markDirty(true);
  persistProfiles();
  toast('PROFILE "' + p.name.toUpperCase() + '" DELETED', "success");
}

function exportActiveProfile() {
  const p = activeProfile();
  if (!p) return;
  const payload = {
    type: "adeck.profile",
    version: 1,
    exported_at: new Date().toISOString(),
    profile: {
      name: p.name,
      theme: normalizeThemeId(p.theme),
      rotation: normalizeRotation(p.rotation),
      background: profileBackground(p),
      slots: p.slots.map((s) => ({
        index: s.index,
        label: s.label,
        command: s.command,
        kind: s.kind === "app" || s.kind === "command" ? s.kind : "",
        color: s.color,
      })),
    },
  };
  const safeName = p.name.replace(/[^\w\-]+/g, "_").toLowerCase() || "profile";
  downloadText("adeck-profile-" + safeName + ".json", JSON.stringify(payload, null, 2));
  toast("PROFILE EXPORTED", "success");
}

async function importProfileFromFile(file) {
  try {
    const data = JSON.parse(await readFileAsText(file));
    let raw = null;
    if (data && data.type === "adeck.profile" && data.profile) raw = data.profile;
    else if (data && data.name && (data.slots || data.buttons)) raw = data;
    else throw new Error("Unrecognized profile format");

    const p = normalizeProfile(raw);
    p.id = newProfileId();
    p.name = uniqueProfileName(p.name);
    state.profiles.push(p);
    state.activeProfileId = p.id;
    state.activeSlotIndex = 0;
    renderAll();
    markDirty(true);
    persistProfiles();
    toast('IMPORTED "' + p.name.toUpperCase() + '"', "success");
  } catch (_) {
    toast("IMPORT FAILED", "error");
  }
}

async function clearActiveSlot(skipConfirm) {
  const s = activeSlot();
  if (!s) return;
  if (!skipConfirm) {
    const ok = await askConfirm({
      kicker: "SLOT",
      title: "CLEAR SLOT",
      message: "Clear key K" + pad2(s.index + 1) + "? Label, command, and color will reset.",
      confirmLabel: "CLEAR",
      danger: true,
    });
    if (!ok) return;
  }
  s.label = "";
  s.command = "";
  s.kind = "";
  s.color = DEFAULT_COLOR;
  renderEditor();
  renderGrid();
  renderProfiles();
  markDirty(true);
  persistProfiles();
  toast("SLOT K" + pad2(s.index + 1) + " CLEARED", "info");
}

function moveSlotSelection(key) {
  const delta = ARROW_DELTA[key];
  if (delta === undefined) return;
  const cur = state.activeSlotIndex;
  if (cur == null) return;
  if (key === "ArrowLeft" && cur % GRID_COLS === 0) return;
  if (key === "ArrowRight" && cur % GRID_COLS === GRID_COLS - 1) return;
  const next = cur + delta;
  if (next < 0 || next >= SLOTS_PER_PROFILE) return;
  state.activeSlotIndex = next;
  refreshSlotUI();
  persistProfiles();
}

function buildConfigObject() {
  return {
    device: "ADECK",
    hardware: "Arduino UNO R4 WiFi + 2.4 TFT + 6 keys",
    version: 2,
    app_version: APP_VERSION,
    generated_at: new Date().toISOString(),
    active_profile: (activeProfile() || {}).name || null,
    settings: {
      theme: state.settings.theme,
      appearance: normalizeAppearance(state.settings.appearance),
      deviceName: state.settings.deviceName,
      sleepTimeout: Number(state.settings.sleepTimeout),
      sleepMode: state.settings.sleepMode === "image" ? "image" : "black",
      sleepImage: String(state.settings.sleepImage || ""),
      defaultProfile: (
        state.profiles.find((p) => p.id === state.settings.defaultProfileId) ||
        activeProfile() ||
        {}
      ).name || null,
      appRelaunchMode:
        state.settings.appRelaunchMode === "minimize" ||
        state.settings.appRelaunchMode === "close"
          ? state.settings.appRelaunchMode
          : "new",
    },
    profiles: state.profiles.map((p) => ({
      id: p.id,
      name: p.name,
      theme: normalizeThemeId(p.theme),
      rotation: normalizeRotation(p.rotation),
      background: profileBackground(p),
      buttons: p.slots.map((s) => {
        const button = {
          key: s.index + 1,
          label: s.label,
          command: s.command,
          color: s.color,
        };
        if (s.kind === "app" || s.kind === "command") button.kind = s.kind;
        return button;
      }),
    })),
  };
}

function buildConfigJson() {
  return JSON.stringify(buildConfigObject(), null, 2);
}

function updateJsonMeta() {
  els.jsonCharCount.textContent = (els.jsonOutput.value || "").length + " bytes";
}

function openJsonModal(jsonText) {
  els.jsonOutput.value = jsonText != null ? jsonText : buildConfigJson();
  els.jsonModal.hidden = false;
  els.jsonModalStatus.textContent = "Ready for Python bridge";
  updateJsonMeta();
  els.jsonOutput.focus();
}

function closeJsonModal() {
  els.jsonModal.hidden = true;
}


const themeModal = { open: false, selectedId: null, savedId: null, previousFocus: null };
const appearanceModal = { open: false, selectedId: null, savedId: null, savedTheme: null, previousFocus: null };

function renderThemeCards() {
  if (!els.themeList) return;
  els.themeList.innerHTML = "";
  const list = themeList();

  if (!list.length) {
    const note = document.createElement("p");
    note.className = "field-hint mono muted";
    note.textContent = "Theme list unavailable — the ADeck service has not answered.";
    els.themeList.appendChild(note);
    return;
  }

  list.forEach((theme) => {
    const selected = theme.id === themeModal.selectedId;
    const saved = theme.id === themeModal.savedId;
    const card = document.createElement("button");
    card.type = "button";
    card.className = "theme-card" + (selected ? " is-selected" : "");
    card.dataset.themeId = theme.id;
    card.setAttribute("role", "radio");
    card.setAttribute("aria-checked", selected ? "true" : "false");

    card.innerHTML =
      '<span class="theme-card-head">' +
      '<span class="theme-card-name">' + escapeHtml(theme.name) + "</span>" +
      '<span class="theme-card-tag mono">' + (saved ? "IN USE" : "") + "</span>" +
      "</span>" +
      '<span class="theme-card-desc">' + escapeHtml(theme.description) + "</span>";

    card.addEventListener("click", () => selectThemePreview(theme.id));
    els.themeList.appendChild(card);
  });
}


function renderThemeTft(theme) {
  if (!els.themeTft) return;
  const tft = theme.tft || {};
  const profile = activeProfile();

  const screenBg =
    String(theme.bgEffect || "").toLowerCase() === "stars"
      ? tft.background || "#080d0e"
      : profile
        ? profileBackground(profile)
        : tft.background || "#000000";
  els.themeTft.style.background = screenBg;
  els.themeTft.style.setProperty("--tft-line", tft.accent || "#888888");


  els.themeTft.querySelectorAll(".theme-tft-stars").forEach((node) => node.remove());

  if (String(theme.bgEffect || "").toLowerCase() === "stars") {
    const layer = document.createElement("div");
    layer.className = "theme-tft-stars";
    layer.setAttribute("aria-hidden", "true");

    const dots = [
      [8, 10], [22, 6], [48, 12], [72, 8], [90, 14],
      [12, 48], [38, 52], [62, 46], [88, 50],
      [6, 88], [28, 92], [54, 86], [78, 90], [94, 84],
      [18, 28], [82, 32], [50, 70], [34, 74],
      [42, 18], [66, 28], [14, 64], [86, 66], [58, 96],
    ];
    dots.forEach(([x, y], index) => {
      const dot = document.createElement("i");
      dot.style.left = x + "%";
      dot.style.top = y + "%";
      dot.style.animationDelay = (index * 0.35) + "s";
      layer.appendChild(dot);
    });
    els.themeTft.insertBefore(layer, els.themeTftGrid || els.themeTft.firstChild);
  }

  const rotation = normalizeRotation(profile ? profile.rotation : DEFAULT_ROTATION);
  applyPreviewOrientation(els.themeTft, rotation);
  applyPreviewOrientation(els.themeTftGrid, rotation);

  const slots = profile ? profile.slots : [];
  els.themeTftGrid.innerHTML = "";

  for (let i = 0; i < SLOTS_PER_PROFILE; i++) {
    const slot = slots[i] || {};
    const cell = document.createElement("span");
    cell.className = "theme-tft-cell";

    const icon = document.createElement("span");
    icon.className = "theme-tft-icon";
    if (slot.command) {
      icon.style.background = normalizeHex(slot.color);
      icon.style.borderColor = tft.accent || "transparent";
    } else {
      icon.style.borderColor = tft.textMuted || "transparent";
    }
    cell.appendChild(icon);

    const label = document.createElement("span");
    label.className = "theme-tft-label mono";
    label.textContent = slot.command || slot.label ? (slot.label || "—") : "EMPTY";
    label.style.color = slot.command || slot.label
      ? (i === state.activeSlotIndex ? tft.selected : tft.text) || "#ffffff"
      : tft.textMuted || "#666666";
    cell.appendChild(label);
    els.themeTftGrid.appendChild(cell);
  }
}

function renderThemePreview() {
  const theme = deckTheme(themeModal.selectedId) || deckTheme(defaultDeckThemeId());
  if (!theme) return;
  renderThemeTft(theme);
  if (els.themeStatus) {
    els.themeStatus.textContent =
      theme.id === themeModal.savedId
        ? "In use by this workspace"
        : "Selected — press APPLY to save it here";
  }
}

function selectThemePreview(themeId) {
  if (!deckTheme(themeId) || themeId === themeModal.selectedId) return;
  themeModal.selectedId = themeId;
  applyActiveDeckTheme();
  renderThemeCards();
  renderThemePreview();
}

function openThemeModal() {
  if (!els.themeModal) return;
  themeModal.previousFocus = document.activeElement;
  themeModal.savedId = activeDeckThemeId();
  themeModal.selectedId = themeModal.savedId;
  themeModal.open = true;
  els.themeModal.hidden = false;
  renderThemeCards();
  renderThemePreview();
}

function closeThemeModal() {
  if (!themeModal.open) return;
  themeModal.open = false;
  els.themeModal.hidden = true;
  applyActiveDeckTheme();
  if (themeModal.previousFocus && themeModal.previousFocus.focus) {
    themeModal.previousFocus.focus();
  }
  themeModal.previousFocus = null;
}

function applySelectedTheme() {
  const p = activeProfile();
  if (!p || !themeModal.selectedId) return;
  const changed = activeDeckThemeId() !== themeModal.selectedId;
  p.theme = themeModal.selectedId;
  themeModal.open = false;
  els.themeModal.hidden = true;
  themeModal.savedId = p.theme;
  themeModal.previousFocus = null;

  markDirty(true);
  persistProfiles();
  applyActiveDeckTheme();
  renderThemeCards();

  syncActiveProfile();
  toast(
    changed ? "THEME: " + deckThemeName(p.theme).toUpperCase() : "THEME UNCHANGED",
    changed ? "success" : "info"
  );
}

function renderAppearanceCards() {
  if (!els.appearanceList) return;
  els.appearanceList.innerHTML = "";
  appearanceList().forEach((item) => {
    const selected = item.id === appearanceModal.selectedId;
    const saved = item.id === appearanceModal.savedId;
    const card = document.createElement("button");
    card.type = "button";
    card.className = "theme-card" + (selected ? " is-selected" : "");
    card.dataset.appearance = item.id;
    card.setAttribute("role", "radio");
    card.setAttribute("aria-checked", selected ? "true" : "false");
    card.innerHTML =
      '<span class="theme-card-head">' +
      '<span class="theme-card-name">' + escapeHtml(item.name) + "</span>" +
      '<span class="theme-card-tag mono">' + (saved ? "IN USE" : "") + "</span>" +
      "</span>" +
      '<span class="theme-card-desc">' + escapeHtml(item.description) + "</span>";
    card.addEventListener("click", () => selectAppearancePreview(item.id));
    els.appearanceList.appendChild(card);
  });
}

function renderAppearancePreview() {
  const id = normalizeAppearance(appearanceModal.selectedId);
  const mode = state.settings.theme === "dark" ? "dark" : "light";
  const palette = appearancePalette(id, mode);
  if (els.appearancePreview) {
    els.appearancePreview.style.setProperty("--preview-bg", palette["--bg-2"] || "#1c1917");
    els.appearancePreview.style.setProperty("--preview-line", palette["--accent"] || "#e11d48");
    els.appearancePreview.style.setProperty("--preview-bar", palette["--bg"] || "#141210");
    els.appearancePreview.style.setProperty("--preview-ink", palette["--ink"] || "#eee8e2");
    els.appearancePreview.style.setProperty("--preview-track", palette["--screen"] || "#0c0b0a");
    els.appearancePreview.style.setProperty("--preview-accent", palette["--accent"] || "#e11d48");
  }
  if (els.appearanceStatus) {
    els.appearanceStatus.textContent =
      id === appearanceModal.savedId
        ? "In use"
        : "Selected — press APPLY to save it";
  }
}

function selectAppearancePreview(id) {
  const next = normalizeAppearance(id);
  if (next === appearanceModal.selectedId) return;
  appearanceModal.selectedId = next;
  if (appearanceForcesDark(next)) applyTheme("dark", false);
  else applyTheme(appearanceModal.savedTheme || state.settings.theme, false);
  renderAppearanceCards();
  renderAppearancePreview();
}

function openAppearanceModal() {
  if (!els.appearanceModal) return;
  appearanceModal.previousFocus = document.activeElement;
  appearanceModal.savedId = normalizeAppearance(state.settings.appearance);
  appearanceModal.savedTheme = state.settings.theme === "dark" ? "dark" : "light";
  appearanceModal.selectedId = appearanceModal.savedId;
  appearanceModal.open = true;
  els.appearanceModal.hidden = false;
  if (els.appearanceBtn) els.appearanceBtn.setAttribute("aria-expanded", "true");
  renderAppearanceCards();
  renderAppearancePreview();
}

function closeAppearanceModal() {
  if (!appearanceModal.open) return;
  appearanceModal.open = false;
  els.appearanceModal.hidden = true;
  appearanceModal.selectedId = appearanceModal.savedId;
  applyTheme(appearanceModal.savedTheme || state.settings.theme, false);
  appearanceModal.savedTheme = null;
  if (els.appearanceBtn) els.appearanceBtn.setAttribute("aria-expanded", "false");
  if (appearanceModal.previousFocus && appearanceModal.previousFocus.focus) {
    appearanceModal.previousFocus.focus();
  }
  appearanceModal.previousFocus = null;
}

function applySelectedAppearance() {
  if (!appearanceModal.selectedId) return;
  const next = normalizeAppearance(appearanceModal.selectedId);
  const changed = normalizeAppearance(state.settings.appearance) !== next;
  state.settings.appearance = next;
  appearanceModal.open = false;
  els.appearanceModal.hidden = true;
  appearanceModal.savedId = next;
  appearanceModal.savedTheme = null;
  appearanceModal.previousFocus = null;
  if (appearanceForcesDark(next)) applyTheme("dark", false);
  else applyActiveDeckTheme();
  persistSettings();
  if (els.appearanceBtn) els.appearanceBtn.setAttribute("aria-expanded", "false");
  toast(
    changed ? "APPEARANCE " + appearanceLabel(next) : "APPEARANCE UNCHANGED",
    changed ? "success" : "info"
  );
}

function formatJsonInModal() {
  try {
    els.jsonOutput.value = JSON.stringify(JSON.parse(els.jsonOutput.value), null, 2);
    els.jsonModalStatus.textContent = "formatted";
    updateJsonMeta();
    toast("JSON FORMATTED", "success");
  } catch (_) {
    toast("INVALID JSON", "error");
  }
}

function validateJsonInModal() {
  try {
    const parsed = JSON.parse(els.jsonOutput.value);
    if (!parsed || typeof parsed !== "object") throw new Error("Root must be an object");
    if (parsed.profiles && !Array.isArray(parsed.profiles)) {
      throw new Error('"profiles" must be an array');
    }
    els.jsonModalStatus.textContent = "valid";
    toast("JSON IS VALID", "success");
    return true;
  } catch (err) {
    els.jsonModalStatus.textContent = "invalid: " + err.message;
    toast("VALIDATION ERROR", "error");
    return false;
  }
}

async function copyJson() {
  const text = els.jsonOutput.value;
  try {
    await navigator.clipboard.writeText(text);
  } catch (_) {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand("copy");
    } catch (__) {}
    ta.remove();
  }
  toast("COPIED", "success");
}

function downloadJson() {
  downloadText("adeck.config.json", els.jsonOutput.value);
  toast("DOWNLOAD STARTED", "success");
}

async function importConfigFromFile(file) {
  try {
    const data = JSON.parse(await readFileAsText(file));
    if (!data || !Array.isArray(data.profiles) || data.profiles.length === 0) {
      throw new Error('Expected "profiles" array');
    }
    const imported = data.profiles.map((p) =>
      normalizeProfile({ name: p.name, slots: p.slots || p.buttons })
    );
    const names = new Set();
    if (
      imported.some((profile) => {
        const name = profile.name.trim().toLowerCase();
        if (names.has(name)) return true;
        names.add(name);
        return false;
      })
    ) {
      throw new Error("Profile names must be unique");
    }
    if (!(await askConfirm({
      kicker: "IMPORT",
      title: "REPLACE PROFILES",
      message: "Replace all local profiles with imported JSON (" + imported.length + " profiles)?",
      confirmLabel: "REPLACE",
      danger: true,
    }))) {
      return;
    }
    state.profiles = imported;
    state.activeProfileId = state.profiles[0].id;
    state.activeSlotIndex = 0;
    renderAll();
    markDirty(true);
    persistProfiles();
    openJsonModal(buildConfigJson());
    toast("CONFIG IMPORTED", "success");
  } catch (_) {
    toast("IMPORT FAILED", "error");
  }
}

function collectSettingsFromForm() {
  return {
    theme: els.settingTheme.value || "light",
    appearance: normalizeAppearance(els.settingAppearance && els.settingAppearance.value),
    deviceName: (els.settingDeviceName.value || "ADECK-UNO").trim().slice(0, 24),
    sleepTimeout: els.settingSleep.value || "60",
    sleepMode: els.settingSleepMode && els.settingSleepMode.value === "image" ? "image" : "black",
    sleepImage: String(state.settings.sleepImage || ""),
    defaultProfileId: els.settingDefaultProfile.value || null,
    appRelaunchMode: ["minimize", "close"].includes(
      els.settingAppRelaunch && els.settingAppRelaunch.value
    )
      ? els.settingAppRelaunch.value
      : "new",
  };
}

async function saveSettings() {
  state.settings = collectSettingsFromForm();
  applyTheme(state.settings.theme);
  persistSettings();
  renderDeviceMeta();
  const result = await postConfigToBridge(buildConfigObject());
  if (!result.ok) {
    toast(
      result.reachable ? "SETTINGS SAVED LOCALLY" : "SETTINGS SAVED LOCALLY — SERVICE OFFLINE",
      result.reachable ? "error" : "info"
    );
    return;
  }
  toast("SETTINGS SAVED", "success");
}

async function resetSettings() {
  const ok = await askConfirm({
    kicker: "SETTINGS",
    title: "RESET DEFAULTS",
    message: "Restore all settings to factory defaults?",
    confirmLabel: "RESET",
    danger: true,
  });
  if (!ok) return;
  state.settings = { ...DEFAULT_SETTINGS, defaultProfileId: state.activeProfileId };
  applyTheme(state.settings.theme);
  persistSettings();
  renderSettingsForm();
  renderDeviceMeta();
  toast("SETTINGS RESET", "info");
}


