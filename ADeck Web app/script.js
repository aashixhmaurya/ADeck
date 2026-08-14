(() => {
    "use strict";

    const APP_VERSION = "1.2.0";
    const BUILD_NUMBER = "2026.08.13-local";
    const SLOTS_PER_PROFILE = 6;
    const LABEL_MAX = 10;
    const COMMAND_MAX = 128;
    const PROFILE_NAME_MAX = 32;
    const STORAGE_KEY = "adeck.cfg.v1";
    const LEGACY_STORAGE_KEY = "macropad.cfg.v1";
    const SETTINGS_KEY = "adeck.settings.v1";

    const COLORS = [
        { name: "ash", hex: "#c5c5c3" },
        { name: "steel", hex: "#255a8c" },
        { name: "teal", hex: "#1f6b52" },
        { name: "signal", hex: "#b42318" },
        { name: "slate", hex: "#2c3238" },
        { name: "ink", hex: "#0a0a0a" },
    ];
    const DEFAULT_COLOR = COLORS[0].hex;

    const SLOT_NEIGHBORS = {
        ArrowUp: [-2, -2, -2, -2, -2, -2],
        ArrowDown: [2, 2, 2, 2, 2, 2],
        ArrowLeft: [-1, -1, -1, -1, -1, -1],
        ArrowRight: [1, 1, 1, 1, 1, 1],
    };

    const DEFAULT_SETTINGS = {
        theme: "light",
        language: "en",
        deviceName: "ADECK-UNO",
        brightness: 80,
        sleepTimeout: "60",
        defaultProfileId: null,
        wifiMode: "off",
    };

    const DEVICE_PLACEHOLDER = {
        connected: false,
        firmware: "—",
        port: "NOT CONNECTED",
        name: "ADECK-UNO",
    };

    const state = {
        profiles: [],
        activeProfileId: null,
        activeSlotIndex: null,
        dirty: false,
        profileFilter: "",
        currentPage: "dashboard",
        settings: {...DEFAULT_SETTINGS },
        storageOk: true,
        device: {...DEVICE_PLACEHOLDER },
    };

    function makeSlot(i) {
        return { index: i, label: "", command: "", color: DEFAULT_COLOR };
    }

    function makeProfile(name) {
        return {
            id: "p_" + Math.random().toString(36).slice(2, 9),
            name: String(name || "Untitled").slice(0, PROFILE_NAME_MAX),
            slots: Array.from({ length: SLOTS_PER_PROFILE }, (_, i) => makeSlot(i)),
        };
    }

    function cloneProfile(source, newName) {
        const p = makeProfile(newName || source.name + " Copy");
        p.slots = source.slots.map((s, i) => ({
            index: i,
            label: String(s.label || "").slice(0, LABEL_MAX),
            command: String(s.command || "").slice(0, COMMAND_MAX),
            color: COLORS.some((c) => c.hex === s.color) ? s.color : DEFAULT_COLOR,
        }));
        return p;
    }

    function activeProfile() {
        return state.profiles.find((p) => p.id === state.activeProfileId) || null;
    }

    function activeSlot() {
        const p = activeProfile();
        if (!p || state.activeSlotIndex == null) return null;
        return p.slots[state.activeSlotIndex] || null;
    }

    function configuredKeyCount(profile) {
        if (!profile || !profile.slots) return 0;
        return profile.slots.filter((s) => s.label || s.command).length;
    }

    function normalizeProfile(raw) {
        return {
            id: raw.id || "p_" + Math.random().toString(36).slice(2, 9),
            name: String(raw.name || "Untitled").slice(0, PROFILE_NAME_MAX),
            slots: Array.from({ length: SLOTS_PER_PROFILE }, (_, i) => {
                const s = (raw.slots && raw.slots[i]) || (raw.buttons && raw.buttons[i]) || {};
                const color = s.color || DEFAULT_COLOR;
                return {
                    index: i,
                    label: String(s.label || "").slice(0, LABEL_MAX),
                    command: String(s.command || "").slice(0, COMMAND_MAX),
                    color: COLORS.some((c) => c.hex === color) ? color : DEFAULT_COLOR,
                };
            }),
        };
    }

    const $ = (id) => document.getElementById(id);

    const els = {
        navBtns: document.querySelectorAll(".nav-btn"),
        pages: document.querySelectorAll(".page"),
        gotoBtns: document.querySelectorAll("[data-goto]"),
        profileList: $("profileList"),
        profileCount: $("profileCount"),
        profileSearch: $("profileSearch"),
        addProfileBtn: $("addProfileBtn"),
        renameProfileBtn: $("renameProfileBtn"),
        duplicateProfileBtn: $("duplicateProfileBtn"),
        exportProfileBtn: $("exportProfileBtn"),
        importProfileBtn: $("importProfileBtn"),
        importProfileFile: $("importProfileFile"),
        deleteProfileBtn: $("deleteProfileBtn"),
        buttonGrid: $("buttonGrid"),
        deviceNameLabel: $("deviceNameLabel"),
        deviceFirmware: $("deviceFirmware"),
        devicePort: $("devicePort"),
        deviceConnText: $("deviceConnText"),
        deviceConnBadge: $("deviceConnBadge"),
        deviceConnStatus: $("deviceConnStatus"),
        screenActiveKey: $("screenActiveKey"),
        screenProfileName: $("screenProfileName"),
        topStateDot: $("topStateDot"),
        activeSlotTag: $("activeSlotTag"),
        slotInfoKey: $("slotInfoKey"),
        slotInfoState: $("slotInfoState"),
        slotColorPreview: $("slotColorPreview"),
        slotColorHex: $("slotColorHex"),
        editorForm: $("editorForm"),
        labelInput: $("labelInput"),
        labelCount: $("labelCount"),
        commandInput: $("commandInput"),
        commandCount: $("commandCount"),
        commandError: $("commandError"),
        commandKindBadge: $("commandKindBadge"),
        colorSelect: $("colorSelect"),
        swatchRow: $("swatchRow"),
        clearSlotBtn: $("clearSlotBtn"),
        statusLine: $("statusLine"),
        clock: $("clock"),
        footerDirty: $("footerDirty"),
        footerProfile: $("footerProfile"),
        footerKey: $("footerKey"),
        footerStorage: $("footerStorage"),
        footerClock: $("footerClock"),
        saveBtn: $("saveBtn"),
        themeToggleBtn: $("themeToggleBtn"),
        themeToggleLabel: $("themeToggleLabel"),
        jsonModal: $("jsonModal"),
        jsonOutput: $("jsonOutput"),
        jsonModalStatus: $("jsonModalStatus"),
        jsonCharCount: $("jsonCharCount"),
        formatJsonBtn: $("formatJsonBtn"),
        validateJsonBtn: $("validateJsonBtn"),
        copyJsonBtn: $("copyJsonBtn"),
        downloadJsonBtn: $("downloadJsonBtn"),
        importJsonBtn: $("importJsonBtn"),
        importJsonFile: $("importJsonFile"),
        closeModalBtn: $("closeModalBtn"),
        settingTheme: $("settingTheme"),
        settingLanguage: $("settingLanguage"),
        settingDeviceName: $("settingDeviceName"),
        settingBrightness: $("settingBrightness"),
        brightnessVal: $("brightnessVal"),
        settingSleep: $("settingSleep"),
        settingDefaultProfile: $("settingDefaultProfile"),
        settingWifi: $("settingWifi"),
        settingsSaveBtn: $("settingsSaveBtn"),
        settingsResetBtn: $("settingsResetBtn"),
        aboutVersion: $("aboutVersion"),
        aboutBuild: $("aboutBuild"),
        toastHost: $("toastHost"),
    };

    function seed() {
        const dev = makeProfile("Dev Mode");
        dev.slots[0] = { index: 0, label: "BUILD", command: "make build", color: "#1f6b52" };
        dev.slots[1] = { index: 1, label: "TEST", command: "npm test", color: "#255a8c" };
        dev.slots[2] = { index: 2, label: "GIT", command: "git status", color: "#2c3238" };
        dev.slots[3] = { index: 3, label: "LOGS", command: "tail -f app.log", color: "#c5c5c3" };
        dev.slots[4] = { index: 4, label: "DEPLOY", command: "./scripts/deploy.sh", color: "#b42318" };
        dev.slots[5] = { index: 5, label: "KILL", command: "pkill node", color: "#0a0a0a" };
        state.profiles.push(dev);
        state.profiles.push(makeProfile("Gaming"));
        state.profiles.push(makeProfile("Media"));
        state.activeProfileId = dev.id;
        state.activeSlotIndex = 0;
    }

    function loadProfiles() {
        try {
            let raw = localStorage.getItem(STORAGE_KEY);
            let fromLegacy = false;
            if (!raw) {
                raw = localStorage.getItem(LEGACY_STORAGE_KEY);
                fromLegacy = !!raw;
            }
            if (!raw) return false;
            const parsed = JSON.parse(raw);
            if (!parsed || !Array.isArray(parsed.profiles) || parsed.profiles.length === 0) return false;
            state.profiles = parsed.profiles.map(normalizeProfile);
            state.activeProfileId = state.profiles.find((p) => p.id === parsed.activeProfileId) ?
                parsed.activeProfileId :
                state.profiles[0].id;
            state.activeSlotIndex = Number.isInteger(parsed.activeSlotIndex) ?
                Math.max(0, Math.min(SLOTS_PER_PROFILE - 1, parsed.activeSlotIndex)) :
                0;
            state.storageOk = true;
            if (fromLegacy) persistProfiles();
            return true;
        } catch (_) {
            state.storageOk = false;
            return false;
        }
    }

    function persistProfiles() {
        try {
            localStorage.setItem(
                STORAGE_KEY,
                JSON.stringify({
                    profiles: state.profiles,
                    activeProfileId: state.activeProfileId,
                    activeSlotIndex: state.activeSlotIndex,
                })
            );
            state.storageOk = true;
        } catch (_) {
            state.storageOk = false;
            toast("STORAGE UNAVAILABLE", "error");
        }
        updateStatusBar();
    }

    function loadSettings() {
        try {
            const raw = localStorage.getItem(SETTINGS_KEY);
            if (!raw) return;
            state.settings = {...DEFAULT_SETTINGS, ...JSON.parse(raw) };
        } catch (_) { /* keep defaults */ }
    }

    function persistSettings() {
        try {
            localStorage.setItem(SETTINGS_KEY, JSON.stringify(state.settings));
            state.storageOk = true;
        } catch (_) {
            state.storageOk = false;
            toast("COULD NOT SAVE SETTINGS", "error");
        }
        updateStatusBar();
    }

    function escapeHtml(str) {
        return String(str).replace(/[&<>"']/g, (ch) =>
            ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]
        );
    }

    function pickTextColor(hex) {
        const h = String(hex || "").replace("#", "");
        if (h.length < 6) return "#000000";
        const r = parseInt(h.substring(0, 2), 16);
        const g = parseInt(h.substring(2, 4), 16);
        const b = parseInt(h.substring(4, 6), 16);
        const yiq = (r * 299 + g * 587 + b * 114) / 1000;
        return yiq >= 150 ? "#000000" : "#f2f1ee";
    }

    function pad2(n) {
        return String(n).padStart(2, "0");
    }

    function formatTime(d) {
        return pad2(d.getHours()) + ":" + pad2(d.getMinutes()) + ":" + pad2(d.getSeconds());
    }

    function downloadText(filename, text, mime) {
        const blob = new Blob([text], { type: mime || "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    function readFileAsText(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(String(reader.result || ""));
            reader.onerror = () => reject(reader.error);
            reader.readAsText(file);
        });
    }

    function isTypingTarget(el) {
        if (!el) return false;
        const tag = el.tagName;
        return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
    }

    function validateCommand(cmd) {
        if (!cmd) return { ok: true, message: "" };
        if (cmd.length > COMMAND_MAX) return { ok: false, message: "Command too long" };
        if (/[\u0000-\u001F]/.test(cmd)) return { ok: false, message: "Control characters not allowed" };
        return { ok: true, message: "" };
    }

    function detectCommandKind(cmd) {
        const value = String(cmd || "").trim();
        if (!value) return "empty";
        if (/^https?:\/\//i.test(value) || /^www\./i.test(value)) return "url";
        if (
            /^[A-Za-z]:[\\/]/.test(value) ||
            /^\\\\/.test(value) ||
            /^~\//.test(value) ||
            /^\/(?!\/)/.test(value) ||
            /\.(exe|bat|cmd|sh|ps1|app|lnk)$/i.test(value)
        ) return "path";
        return "command";
    }

    function commandKindLabel(kind) {
        if (kind === "url") return "URL";
        if (kind === "path") return "PATH";
        if (kind === "command") return "CMD";
        return "—";
    }

    function colorName(hex) {
        const found = COLORS.find((c) => c.hex === hex);
        return found ? found.name.toUpperCase() : "CUSTOM";
    }

    function updateCommandKindUI(cmd) {
        if (!els.commandKindBadge) return;
        const kind = detectCommandKind(cmd);
        els.commandKindBadge.dataset.kind = kind;
        els.commandKindBadge.textContent = commandKindLabel(kind);
    }

    function markDirty(flag) {
        state.dirty = flag !== false;
        updateStatusBar();
    }

    function normalizeTheme(theme) {
        return theme === "dark" ? "dark" : "light";
    }

    function applyTheme(theme) {
        const mode = normalizeTheme(theme);
        state.settings.theme = mode;
        document.documentElement.setAttribute("data-theme", mode);
        document.body.setAttribute("data-theme", mode);
        if (els.themeToggleLabel) els.themeToggleLabel.textContent = mode === "dark" ? "NIGHT" : "DAY";
        if (els.themeToggleBtn) {
            els.themeToggleBtn.setAttribute("aria-pressed", mode === "dark" ? "true" : "false");
        }
        if (els.settingTheme) els.settingTheme.value = mode;
    }

    function toggleTheme() {
        const next = state.settings.theme === "dark" ? "light" : "dark";
        applyTheme(next);
        persistSettings();
        toast(next === "dark" ? "NIGHT MODE" : "DAY MODE", "info");
    }

    function toast(message, type) {
        if (!els.toastHost) return;
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
        close.addEventListener("click", () => node.remove());
        node.appendChild(msg);
        node.appendChild(close);
        els.toastHost.appendChild(node);
        setTimeout(() => { if (node.parentNode) node.remove(); }, 3000);
    }

    window.ADeckBridge = {
        connectDevice() { /* TODO: Python bridge */ },
        disconnectDevice() { /* TODO: Python bridge */ },
        sendConfig() { /* TODO: Python bridge */ },
        receiveStatus() { /* TODO: Python bridge */ },
        syncProfiles() { /* TODO: Python bridge */ },
    };

    function updateStatusBar() {
        const p = activeProfile();
        const s = activeSlot();
        els.footerDirty.textContent = state.dirty ? "UNSAVED" : "SAVED";
        els.footerDirty.classList.toggle("dirty", state.dirty);
        els.footerProfile.textContent = p ? p.name : "—";
        els.footerKey.textContent = s != null ? "K" + pad2(s.index + 1) : "—";
        els.footerStorage.textContent = state.storageOk ? "OK" : "ERROR";
        els.footerStorage.classList.toggle("error", !state.storageOk);
        if (els.statusLine) els.statusLine.textContent = state.dirty ? "EDITING" : "READY";
        if (els.topStateDot) els.topStateDot.classList.toggle("warn", state.dirty);
        if (els.profileCount) els.profileCount.textContent = String(state.profiles.length);
    }

    function renderDeviceMeta() {
        const d = state.device;
        const name = state.settings.deviceName || d.name;
        const p = activeProfile();
        const s = activeSlot();
        els.deviceNameLabel.textContent = name;
        els.deviceFirmware.textContent = d.firmware && d.firmware !== "—" ? "Firmware " + d.firmware : "Firmware —";
        els.devicePort.textContent = d.port || "NOT CONNECTED";
        const online = !!d.connected;
        els.deviceConnText.textContent = online ? "CONNECTED" : "LOCAL ONLY";
        els.deviceConnBadge.textContent = online ? "ONLINE" : "LOCAL";
        els.deviceConnBadge.classList.toggle("offline", !online);
        els.deviceConnStatus.classList.toggle("offline", !online);
        if (els.screenActiveKey) els.screenActiveKey.textContent = s != null ? "K" + pad2(s.index + 1) : "K—";
        if (els.screenProfileName) els.screenProfileName.textContent = p ? p.name.toUpperCase().slice(0, 16) : "—";
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
            empty.innerHTML = filter ?
                "<strong>NO MATCHES</strong>Try another profile name." :
                "<strong>NO PROFILES</strong>Create your first configuration profile.";
            els.profileList.appendChild(empty);
        }
        updateStatusBar();
    }

    function renderGrid() {
        const p = activeProfile();
        els.buttonGrid.innerHTML = "";
        if (!p) return;
        p.slots.forEach((slot) => {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "slot";
            btn.setAttribute("aria-label", "Key " + (slot.index + 1) + (slot.label ? ": " + slot.label : " empty"));
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
            idx.textContent = "K" + pad2(slot.index + 1);
            const activeTag = document.createElement("div");
            activeTag.className = "slot-active-tag";
            activeTag.textContent = "ACTIVE";
            const lbl = document.createElement("div");
            lbl.className = "slot-label";
            lbl.textContent = slot.label || "EMPTY";
            const cmd = document.createElement("div");
            cmd.className = "slot-cmd";
            cmd.textContent = slot.command || "—";
            btn.appendChild(idx);
            btn.appendChild(activeTag);
            btn.appendChild(lbl);
            btn.appendChild(cmd);
            btn.addEventListener("click", () => {
                state.activeSlotIndex = slot.index;
                renderGrid();
                renderEditor();
                renderDeviceMeta();
                updateStatusBar();
                persistProfiles();
            });
            els.buttonGrid.appendChild(btn);
        });
    }

    function renderColorOptions() {
        els.colorSelect.innerHTML = "";
        COLORS.forEach((c) => {
            const opt = document.createElement("option");
            opt.value = c.hex;
            opt.textContent = c.name.toUpperCase() + "  " + c.hex;
            els.colorSelect.appendChild(opt);
        });
        els.swatchRow.innerHTML = "";
        COLORS.forEach((c) => {
            const sw = document.createElement("button");
            sw.type = "button";
            sw.className = "swatch";
            sw.title = c.name + " " + c.hex;
            sw.setAttribute("aria-label", "Color " + c.name);
            sw.dataset.hex = c.hex;
            sw.innerHTML =
                '<span class="swatch-chip" style="background:' + c.hex + '"></span>' +
                '<span class="swatch-name">' + escapeHtml(c.name) + "</span>" +
                '<span class="swatch-hex">' + c.hex + "</span>";
            sw.addEventListener("click", () => applyColor(c.hex));
            els.swatchRow.appendChild(sw);
        });
    }

    function highlightSwatch(hex) {
        els.swatchRow.querySelectorAll(".swatch").forEach((n) => {
            n.classList.toggle("selected", n.dataset.hex === hex);
            n.setAttribute("aria-pressed", n.dataset.hex === hex ? "true" : "false");
        });
    }

    function applyColor(hex) {
        const s = activeSlot();
        if (!s) return;
        s.color = hex;
        els.colorSelect.value = hex;
        highlightSwatch(hex);
        renderGrid();
        renderEditor();
        markDirty(true);
        persistProfiles();
    }

    function renderEditor() {
        const s = activeSlot();
        const p = activeProfile();
        const disabled = !s;
        els.labelInput.disabled = disabled;
        els.commandInput.disabled = disabled;
        els.colorSelect.disabled = disabled;
        els.clearSlotBtn.disabled = disabled;
        els.swatchRow.querySelectorAll(".swatch").forEach((sw) => { sw.disabled = disabled; });
        els.editorForm.classList.toggle("is-disabled", disabled);
        if (!s || !p) {
            els.activeSlotTag.textContent = "—";
            els.slotInfoKey.textContent = "—";
            els.slotInfoState.textContent = "—";
            els.slotInfoState.className = "slot-state-badge mono";
            els.slotColorHex.textContent = "—";
            els.slotColorPreview.style.background = "transparent";
            els.labelInput.value = "";
            els.commandInput.value = "";
            els.labelCount.textContent = "0";
            els.commandCount.textContent = "0";
            els.commandError.hidden = true;
            updateCommandKindUI("");
            highlightSwatch(null);
            return;
        }
        const isEmpty = !s.label && !s.command;
        els.activeSlotTag.textContent = p.name.toUpperCase().slice(0, 12) + " / K" + pad2(s.index + 1);
        els.slotInfoKey.textContent = "K" + pad2(s.index + 1);
        els.slotInfoState.textContent = isEmpty ? "EMPTY" : "CONFIGURED";
        els.slotInfoState.className = "slot-state-badge mono " + (isEmpty ? "is-empty" : "is-configured");
        els.slotColorHex.textContent = colorName(s.color) + "  " + s.color;
        els.slotColorPreview.style.background = s.color;
        els.labelInput.value = s.label;
        els.commandInput.value = s.command;
        els.colorSelect.value = s.color;
        els.labelCount.textContent = String(s.label.length);
        els.commandCount.textContent = String(s.command.length);
        updateCommandKindUI(s.command);
        const v = validateCommand(s.command);
        els.commandError.hidden = v.ok;
        els.commandError.textContent = v.message;
        els.commandInput.classList.toggle("invalid", !v.ok);
        highlightSwatch(s.color);
        updateStatusBar();
    }

    function renderSettingsForm() {
        const s = state.settings;
        els.settingTheme.value = s.theme || "light";
        els.settingLanguage.value = s.language || "en";
        els.settingDeviceName.value = s.deviceName || "";
        els.settingBrightness.value = String(s.brightness ? ? 80);
        els.brightnessVal.textContent = (s.brightness ? ? 80) + "%";
        els.settingSleep.value = String(s.sleepTimeout ? ? "60");
        els.settingWifi.value = s.wifiMode || "off";
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
        updateStatusBar();
    }

    function showPage(pageId) {
        const id = pageId || "dashboard";
        state.currentPage = id;
        els.pages.forEach((page) => { page.hidden = page.dataset.page !== id; });
        els.navBtns.forEach((btn) => {
            const active = btn.dataset.page === id;
            btn.classList.toggle("active", active);
            if (active) btn.setAttribute("aria-current", "page");
            else btn.removeAttribute("aria-current");
        });
        if (id === "settings") renderSettingsForm();
        if (id === "about") renderAbout();
    }

    function addProfile() {
        const name = prompt("New profile name:", "Profile " + (state.profiles.length + 1));
        if (name === null) return;
        const p = makeProfile(name.trim().slice(0, PROFILE_NAME_MAX) || "Untitled");
        state.profiles.push(p);
        state.activeProfileId = p.id;
        state.activeSlotIndex = 0;
        renderAll();
        markDirty(true);
        persistProfiles();
        toast('PROFILE "' + p.name.toUpperCase() + '" CREATED', "success");
    }

    function renameProfile() {
        const p = activeProfile();
        if (!p) return;
        const name = prompt("Rename profile:", p.name);
        if (name === null) return;
        p.name = name.trim().slice(0, PROFILE_NAME_MAX) || p.name;
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
        const copy = cloneProfile(p);
        state.profiles.push(copy);
        state.activeProfileId = copy.id;
        state.activeSlotIndex = 0;
        renderAll();
        markDirty(true);
        persistProfiles();
        toast('DUPLICATED AS "' + copy.name.toUpperCase() + '"', "success");
    }

    function deleteProfile() {
        if (state.profiles.length <= 1) {
            toast("CANNOT DELETE LAST PROFILE", "error");
            return;
        }
        const p = activeProfile();
        if (!p) return;
        if (!confirm('Delete profile "' + p.name + '"?')) return;
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
                slots: p.slots.map((s) => ({
                    index: s.index,
                    label: s.label,
                    command: s.command,
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
            p.id = "p_" + Math.random().toString(36).slice(2, 9);
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

    function clearActiveSlot(skipConfirm) {
        const s = activeSlot();
        if (!s) return;
        if (!skipConfirm && !confirm("Clear slot K" + pad2(s.index + 1) + "?")) return;
        s.label = "";
        s.command = "";
        s.color = DEFAULT_COLOR;
        renderEditor();
        renderGrid();
        renderProfiles();
        markDirty(true);
        persistProfiles();
        toast("SLOT K" + pad2(s.index + 1) + " CLEARED", "info");
    }

    function moveSlotSelection(key) {
        const map = SLOT_NEIGHBORS[key];
        if (!map) return;
        const cur = state.activeSlotIndex;
        if (cur == null) return;
        if (key === "ArrowLeft" && cur % 2 === 0) return;
        if (key === "ArrowRight" && cur % 2 === 1) return;
        const next = cur + map[cur];
        if (next < 0 || next >= SLOTS_PER_PROFILE) return;
        state.activeSlotIndex = next;
        renderGrid();
        renderEditor();
        renderDeviceMeta();
        persistProfiles();
    }

    function buildConfigObject() {
        return {
            device: "ADECK",
            hardware: "Arduino UNO R4 WiFi + 2.4 TFT + 6 keys",
            version: 1,
            app_version: APP_VERSION,
            generated_at: new Date().toISOString(),
            active_profile: (activeProfile() || {}).name || null,
            settings: {
                deviceName: state.settings.deviceName,
                brightness: state.settings.brightness,
                sleepTimeout: Number(state.settings.sleepTimeout),
                defaultProfile: (
                    state.profiles.find((p) => p.id === state.settings.defaultProfileId) ||
                    activeProfile() || {}
                ).name || null,
            },
            profiles: state.profiles.map((p) => ({
                name: p.name,
                buttons: p.slots.map((s) => ({
                    key: s.index + 1,
                    label: s.label,
                    command: s.command,
                    color: s.color,
                })),
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
            if (parsed.profiles && !Array.isArray(parsed.profiles)) throw new Error('"profiles" must be an array');
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
            try { document.execCommand("copy"); } catch (__) { /* ignore */ }
            document.body.removeChild(ta);
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
            if (!confirm("Replace all local profiles with imported JSON (" + imported.length + " profiles)?")) return;
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

    function saveAndShowJson() {
        openJsonModal(buildConfigJson());
        markDirty(false);
        persistProfiles();
        toast("SAVE COMPLETE", "success");
    }

    function collectSettingsFromForm() {
        return {
            theme: els.settingTheme.value || "light",
            language: els.settingLanguage.value || "en",
            deviceName: (els.settingDeviceName.value || "ADECK-UNO").trim().slice(0, 24),
            brightness: Number(els.settingBrightness.value) || 80,
            sleepTimeout: els.settingSleep.value || "60",
            defaultProfileId: els.settingDefaultProfile.value || null,
            wifiMode: els.settingWifi.value || "off",
        };
    }

    function saveSettings() {
        state.settings = collectSettingsFromForm();
        applyTheme(state.settings.theme);
        persistSettings();
        renderDeviceMeta();
        toast("SETTINGS SAVED", "success");
    }

    function resetSettings() {
        if (!confirm("Reset settings to defaults?")) return;
        state.settings = {...DEFAULT_SETTINGS, defaultProfileId: state.activeProfileId };
        applyTheme(state.settings.theme);
        persistSettings();
        renderSettingsForm();
        renderDeviceMeta();
        toast("SETTINGS RESET", "info");
    }

    function wireEvents() {
        els.navBtns.forEach((btn) => btn.addEventListener("click", () => showPage(btn.dataset.page)));
        els.gotoBtns.forEach((btn) => btn.addEventListener("click", () => showPage(btn.dataset.goto)));
        els.addProfileBtn.addEventListener("click", addProfile);
        els.renameProfileBtn.addEventListener("click", renameProfile);
        els.duplicateProfileBtn.addEventListener("click", duplicateProfile);
        els.deleteProfileBtn.addEventListener("click", deleteProfile);
        els.exportProfileBtn.addEventListener("click", exportActiveProfile);
        els.importProfileBtn.addEventListener("click", () => els.importProfileFile.click());
        els.importProfileFile.addEventListener("change", async(e) => {
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
            const isEmpty = !s.label && !s.command;
            els.slotInfoState.textContent = isEmpty ? "EMPTY" : "CONFIGURED";
            renderGrid();
            renderProfiles();
            renderDeviceMeta();
            markDirty(true);
            persistProfiles();
        });
        els.commandInput.addEventListener("input", (e) => {
            const s = activeSlot();
            if (!s) return;
            s.command = e.target.value.slice(0, COMMAND_MAX);
            if (e.target.value !== s.command) e.target.value = s.command;
            els.commandCount.textContent = String(s.command.length);
            updateCommandKindUI(s.command);
            const v = validateCommand(s.command);
            els.commandError.hidden = v.ok;
            els.commandError.textContent = v.message;
            els.commandInput.classList.toggle("invalid", !v.ok);
            renderGrid();
            renderProfiles();
            renderDeviceMeta();
            markDirty(true);
            persistProfiles();
        });
        els.colorSelect.addEventListener("change", (e) => applyColor(e.target.value));
        els.clearSlotBtn.addEventListener("click", () => clearActiveSlot(false));
        els.saveBtn.addEventListener("click", saveAndShowJson);
        els.closeModalBtn.addEventListener("click", closeJsonModal);
        els.formatJsonBtn.addEventListener("click", formatJsonInModal);
        els.validateJsonBtn.addEventListener("click", validateJsonInModal);
        els.copyJsonBtn.addEventListener("click", copyJson);
        els.downloadJsonBtn.addEventListener("click", downloadJson);
        els.importJsonBtn.addEventListener("click", () => els.importJsonFile.click());
        els.importJsonFile.addEventListener("change", async(e) => {
            const file = e.target.files && e.target.files[0];
            e.target.value = "";
            if (file) await importConfigFromFile(file);
        });
        els.jsonOutput.addEventListener("input", updateJsonMeta);
        els.jsonModal.addEventListener("click", (e) => {
            if (e.target === els.jsonModal) closeJsonModal();
        });
        els.settingBrightness.addEventListener("input", (e) => {
            els.brightnessVal.textContent = e.target.value + "%";
        });
        els.settingsSaveBtn.addEventListener("click", saveSettings);
        els.settingsResetBtn.addEventListener("click", resetSettings);
        if (els.themeToggleBtn) els.themeToggleBtn.addEventListener("click", toggleTheme);
        if (els.settingTheme) {
            els.settingTheme.addEventListener("change", (e) => {
                applyTheme(e.target.value);
                persistSettings();
                toast(e.target.value === "dark" ? "NIGHT MODE" : "DAY MODE", "info");
            });
        }
        document.addEventListener("keydown", onGlobalKeydown);
    }

    function onGlobalKeydown(e) {
        if (e.key === "Escape" && !els.jsonModal.hidden) {
            e.preventDefault();
            closeJsonModal();
            return;
        }
        if ((e.ctrlKey || e.metaKey) && (e.key === "s" || e.key === "S")) {
            e.preventDefault();
            saveAndShowJson();
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
        if (e.key === "ArrowUp" || e.key === "ArrowDown" || e.key === "ArrowLeft" || e.key === "ArrowRight") {
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
        const t = formatTime(new Date());
        els.clock.textContent = t;
        els.footerClock.textContent = t;
    }

    function boot() {
        loadSettings();
        if (!loadProfiles()) seed();
        if (state.settings.deviceName) state.device.name = state.settings.deviceName;
        if (!state.settings.defaultProfileId) state.settings.defaultProfileId = state.activeProfileId;
        state.device.connected = false;
        state.device.port = "NOT CONNECTED";
        state.device.firmware = "—";
        applyTheme(state.settings.theme || "light");
        renderColorOptions();
        renderAll();
        renderAbout();
        markDirty(false);
        wireEvents();
        showPage("dashboard");
        setInterval(tickClock, 1000);
        tickClock();
    }

    boot();
})();