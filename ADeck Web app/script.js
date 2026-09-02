/* adeck - open index.html, no build */
(() => {
    "use strict";

    const APP_VERSION = "1.2.0";
    const BUILD_NUMBER = "2026.08.13-local";
    const SLOTS_PER_PROFILE = 6;
    const LABEL_MAX = 10;
    const COMMAND_MAX = 256;
    const PROFILE_NAME_MAX = 32;
    const STORAGE_KEY = "adeck.cfg.v1";
    const LEGACY_STORAGE_KEY = "macropad.cfg.v1"; // legacy storage key
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

    const COMMON_COMMANDS = [
        { name: "git status", command: "git status", label: "GIT", kind: "command" },
        { name: "git add .", command: "git add .", label: "ADD", kind: "command" },
        { name: "git commit", command: "git commit", label: "COMMIT", kind: "command" },
        { name: "git push", command: "git push", label: "PUSH", kind: "command" },
        { name: "git pull", command: "git pull", label: "PULL", kind: "command" },
        { name: "npm test", command: "npm test", label: "TEST", kind: "command" },
        { name: "npm run dev", command: "npm run dev", label: "DEV", kind: "command" },
    ];

    const PICKER_LABELS = {
        "visual studio code": "VS CODE",
        "google chrome": "CHROME",
        "file explorer": "EXPLORER",
        "windows explorer": "EXPLORER",
        calculator: "CALC",
        paint: "PAINT",
        notepad: "NOTEPAD",
        "youtube music": "YT MUSIC",
        settings: "SETTINGS",
    };

    function normalizeHex(hex) {
        const raw = String(hex || "").trim().toLowerCase();
        if (/^#[0-9a-f]{6}$/.test(raw)) return raw;
        if (/^[0-9a-f]{6}$/.test(raw)) return "#" + raw;
        return DEFAULT_COLOR;
    }

    function isPresetColor(hex) {
        return COLORS.some((c) => c.hex === hex);
    }

    // 2x3 grid moves
    const ARROW_DELTA = {
        ArrowUp: -2,
        ArrowDown: 2,
        ArrowLeft: -1,
        ArrowRight: 1,
    };

    const DEFAULT_SETTINGS = {
        theme: "light",
        language: "en",
        deviceName: "ADECK-UNO",
        brightness: 80,
        sleepTimeout: "60",
        defaultProfileId: null,
        wifiMode: "off",
        appRelaunchMode: "new",
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
        backend: {
            reachable: true,
            failures: 0,
            status: null,
            system: null,
            busy: false,
        },
    };

    // Tasks that take the local service down for a moment.
    const SERVICE_TASKS = new Set(["restart", "repair", "reinstall-firmware", "stop"]);
    const TASK_WATCH_KEY = "adeck.task.v1";
    const SERVICE_HINT_KEY = "adeck.servicehint.v1";
    let taskWatch = null;
    let installPrompt = null;

    function newProfileId() {
        return "p_" + Math.random().toString(36).slice(2, 9);
    }

    function makeSlot(i) {
        return { index: i, label: "", command: "", kind: "", color: DEFAULT_COLOR };
    }

    function makeProfile(name) {
        return {
            id: newProfileId(),
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
            kind: s.kind === "app" || s.kind === "command" ? s.kind : "",
            color: normalizeHex(s.color),
        }));
        return p;
    }

    function activeProfile() {
        return state.profiles.find((p) => p.id === state.activeProfileId) || null;
    }

    function profileNameExists(name, exceptId) {
        const folded = String(name || "").trim().toLowerCase();
        return state.profiles.some(
            (profile) =>
            profile.id !== exceptId && profile.name.trim().toLowerCase() === folded
        );
    }

    function uniqueProfileName(name) {
        const base = String(name || "Untitled").slice(0, PROFILE_NAME_MAX);
        if (!profileNameExists(base)) return base;
        let suffix = 2;
        let candidate;
        do {
            const suffixText = " " + suffix++;
            candidate = base.slice(0, PROFILE_NAME_MAX - suffixText.length) + suffixText;
        } while (profileNameExists(candidate));
        return candidate;
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

    // also accepts old buttons[] exports
    function normalizeProfile(raw) {
        return {
            id: raw.id || newProfileId(),
            name: String(raw.name || "Untitled").slice(0, PROFILE_NAME_MAX),
            slots: Array.from({ length: SLOTS_PER_PROFILE }, (_, i) => {
                const s = (raw.slots && raw.slots[i]) || (raw.buttons && raw.buttons[i]) || {};
                return {
                    index: i,
                    label: String(s.label || "").slice(0, LABEL_MAX),
                    command: String(s.command || "").slice(0, COMMAND_MAX),
                    kind: s.kind === "app" || s.kind === "command" ? s.kind : "",
                    color: normalizeHex(s.color),
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
        deviceConnBadge: $("deviceConnBadge"),
        screenActiveKey: $("screenActiveKey"),
        screenProfileName: $("screenProfileName"),
        topStateDot: $("topStateDot"),
        activeSlotTag: $("activeSlotTag"),
        slotInfoKey: $("slotInfoKey"),
        slotInfoState: $("slotInfoState"),
        slotColorPreview: $("slotColorPreview"),
        slotColorHex: $("slotColorHex"),
        editorForm: $("editorForm"),
        settingsForm: $("settingsForm"),
        labelInput: $("labelInput"),
        labelCount: $("labelCount"),
        commandInput: $("commandInput"),
        commandCount: $("commandCount"),
        commandError: $("commandError"),
        commandKindBadge: $("commandKindBadge"),
        appPickerBtn: $("appPickerBtn"),
        appPickerModal: $("appPickerModal"),
        appPickerCloseBtn: $("appPickerCloseBtn"),
        appPickerSearch: $("appPickerSearch"),
        appPickerStatus: $("appPickerStatus"),
        appPickerCommands: $("appPickerCommands"),
        appPickerApps: $("appPickerApps"),
        swatchRow: $("swatchRow"),
        customColorBtn: $("customColorBtn"),
        customColorInput: $("customColorInput"),
        clearSlotBtn: $("clearSlotBtn"),
        statusLine: $("statusLine"),
        clock: $("clock"),
        footerDirty: $("footerDirty"),
        footerProfile: $("footerProfile"),
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
        settingAppRelaunch: $("settingAppRelaunch"),
        settingsSaveBtn: $("settingsSaveBtn"),
        settingsResetBtn: $("settingsResetBtn"),
        aboutVersion: $("aboutVersion"),
        aboutBuild: $("aboutBuild"),
        toastHost: $("toastHost"),
        navSystemDot: $("navSystemDot"),
        systemBanner: $("systemBanner"),
        systemBannerTitle: $("systemBannerTitle"),
        systemBannerText: $("systemBannerText"),
        systemBannerAction: $("systemBannerAction"),
        sysBackend: $("sysBackend"),
        sysHardware: $("sysHardware"),
        sysPort: $("sysPort"),
        sysFirmware: $("sysFirmware"),
        sysSync: $("sysSync"),
        sysConfig: $("sysConfig"),
        sysSetup: $("sysSetup"),
        sysRefreshBtn: $("sysRefreshBtn"),
        sysPortSelect: $("sysPortSelect"),
        sysReconnectBtn: $("sysReconnectBtn"),
        sysResyncBtn: $("sysResyncBtn"),
        sysRestartBtn: $("sysRestartBtn"),
        sysStopBtn: $("sysStopBtn"),
        sysViewLogBtn: $("sysViewLogBtn"),
        sysLogsBtn: $("sysLogsBtn"),
        sysInstalled: $("sysInstalled"),
        sysDesktop: $("sysDesktop"),
        sysAutostart: $("sysAutostart"),
        sysInstallBtn: $("sysInstallBtn"),
        sysShortcutBtn: $("sysShortcutBtn"),
        sysAutostartBtn: $("sysAutostartBtn"),
        sysInstallHint: $("sysInstallHint"),
        sysCheckBtn: $("sysCheckBtn"),
        sysErrorsBtn: $("sysErrorsBtn"),
        sysRepairBtn: $("sysRepairBtn"),
        sysFirmwareBtn: $("sysFirmwareBtn"),
        sysTaskLabel: $("sysTaskLabel"),
        sysOutput: $("sysOutput"),
        sysClearOutputBtn: $("sysClearOutputBtn"),
        offlineOverlay: $("offlineOverlay"),
        offlineKicker: $("offlineKicker"),
        offlineTitle: $("offlineTitle"),
        offlineMessage: $("offlineMessage"),
        offlineHint: $("offlineHint"),
        offlineStartBtn: $("offlineStartBtn"),
        offlineRetryBtn: $("offlineRetryBtn"),
        appDialog: $("appDialog"),
        dialogKicker: $("dialogKicker"),
        dialogTitle: $("dialogTitle"),
        dialogMessage: $("dialogMessage"),
        dialogInputWrap: $("dialogInputWrap"),
        dialogInputLabel: $("dialogInputLabel"),
        dialogInput: $("dialogInput"),
        dialogCancel: $("dialogCancel"),
        dialogConfirm: $("dialogConfirm"),
    };

    let dialogState = null;

    function seed() {
        const dev = makeProfile("Dev Mode");
        dev.slots[0] = { index: 0, label: "BUILD", command: "make build", color: "#1f6b52" };
        dev.slots[1] = { index: 1, label: "TEST", command: "npm test", color: "#255a8c" };
        dev.slots[2] = { index: 2, label: "GIT", command: "git status", color: "#2c3238" };
        dev.slots[3] = { index: 3, label: "LOGS", command: "tail -f app.log", color: "#c5c5c3" };
        dev.slots[4] = { index: 4, label: "DEPLOY", command: "./scripts/deploy", color: "#b42318" };
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

    function hydrateConfig(config) {
        if (!config || !Array.isArray(config.profiles) || config.profiles.length === 0) {
            return false;
        }
        const profiles = config.profiles.map(normalizeProfile);
        const activeName = String(config.active_profile || "");
        const active =
            profiles.find((profile) => profile.name === activeName) ||
            profiles.find((profile) => profile.id === config.activeProfileId) ||
            profiles[0];
        state.profiles = profiles;
        state.activeProfileId = active.id;
        state.activeSlotIndex = 0;
        if (config.settings && typeof config.settings === "object") {
            state.settings = {...state.settings, ...config.settings };
            const defaultName = config.settings.defaultProfile;
            const defaultProfile = profiles.find((profile) => profile.name === defaultName);
            if (defaultProfile) state.settings.defaultProfileId = defaultProfile.id;
        }
        persistProfiles();
        persistSettings();
        return true;
    }

    function loadSettings() {
        try {
            const raw = localStorage.getItem(SETTINGS_KEY);
            if (!raw) return;
            state.settings = {...DEFAULT_SETTINGS, ...JSON.parse(raw) };
        } catch (_) {}
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
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function pickTextColor(hex) {
        const h = String(hex || "").replace("#", "");
        if (h.length < 6) return "#000000";
        const r = parseInt(h.slice(0, 2), 16);
        const g = parseInt(h.slice(2, 4), 16);
        const b = parseInt(h.slice(4, 6), 16);
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
        a.remove();
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
        ) {
            return "path";
        }
        return "command";
    }

    function colorName(hex) {
        const found = COLORS.find((c) => c.hex === hex);
        return found ? found.name.toUpperCase() : "CUSTOM";
    }

    function pickerLabel(name, fallback) {
        const raw = String(name || "").trim();
        const mapped = PICKER_LABELS[raw.toLowerCase()];
        if (mapped) return mapped.slice(0, LABEL_MAX);
        const ascii = raw.replace(/[^\x20-\x7E]/g, "").trim();
        if (ascii) return ascii.slice(0, LABEL_MAX).toUpperCase();
        return String(fallback || "").slice(0, LABEL_MAX);
    }

    function updateCommandKindUI(cmd, kind) {
        if (!els.commandKindBadge) return;
        if (kind === "app") {
            els.commandKindBadge.dataset.kind = "path";
            els.commandKindBadge.textContent = "APP";
            return;
        }
        if (kind === "command") {
            els.commandKindBadge.dataset.kind = "command";
            els.commandKindBadge.textContent = "CMD";
            return;
        }
        const detected = detectCommandKind(cmd);
        els.commandKindBadge.dataset.kind = detected;
        els.commandKindBadge.textContent =
            detected === "url" ? "URL" : detected === "path" ? "PATH" : detected === "command" ? "CMD" : "—";
    }

    function markDirty(flag) {
        state.dirty = flag !== false;
        updateStatusBar();
    }

    function refreshSlotUI() {
        renderGrid();
        renderEditor();
        renderDeviceMeta();
        updateStatusBar();
    }

    function afterSlotFieldEdit() {
        renderGrid();
        renderProfiles();
        renderDeviceMeta();
        markDirty(true);
        persistProfiles();
    }

    function applyTheme(theme, animate = true) {
        const mode = theme === "dark" ? "dark" : "light";
        state.settings.theme = mode;
        if (animate) {
            document.body.classList.add("theme-switching");
            window.clearTimeout(applyTheme._t);
            applyTheme._t = window.setTimeout(() => {
                document.body.classList.remove("theme-switching");
            }, 480);
        }
        document.documentElement.setAttribute("data-theme", mode);
        document.body.setAttribute("data-theme", mode);
        if (els.themeToggleLabel) els.themeToggleLabel.textContent = mode === "dark" ? "DARK" : "LIGHT";
        if (els.themeToggleBtn) {
            els.themeToggleBtn.setAttribute("aria-pressed", mode === "dark" ? "true" : "false");
        }
        if (els.settingTheme) els.settingTheme.value = mode;
    }

    function toggleTheme() {
        const next = state.settings.theme === "dark" ? "light" : "dark";
        applyTheme(next);
        persistSettings();
        toast(next === "dark" ? "DARK MODE" : "LIGHT MODE", "info");
    }

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
        return showDialog({...options, mode: "confirm" }).then((ok) => !!ok);
    }

    function askPrompt(options) {
        return showDialog({...options, mode: "prompt" }).then((value) => {
            if (value === null || value === false) return null;
            return String(value);
        });
    }

    function isDialogOpen() {
        return !!dialogState;
    }

    const localBridge =
        /^https?:$/.test(window.location.protocol) && ["127.0.0.1", "localhost"].includes(window.location.hostname) ?
        window.location.origin :
        "http://127.0.0.1:8765";

    async function fetchWithTimeout(url, options, timeoutMs) {
        const controller = new AbortController();
        const timer = window.setTimeout(() => controller.abort(), timeoutMs);
        try {
            return await fetch(url, {...(options || {}), signal: controller.signal });
        } finally {
            window.clearTimeout(timer);
        }
    }

    async function postConfigToBridge(config) {
        try {
            const res = await fetchWithTimeout(
                localBridge + "/api/config", {
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
            return {...data, reachable: true };
        } catch (error) {
            return { ok: false, reachable: false, error: error.message };
        }
    }

    async function fetchConfigFromBridge() {
        try {
            const response = await fetchWithTimeout(
                localBridge + "/api/config", { cache: "no-store" },
                2500
            );
            const data = await response.json().catch(() => ({}));
            if (!response.ok || !data.ok) {
                return { ok: false, reachable: true, error: data.error || "Could not load config" };
            }
            return {...data, reachable: true };
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

    async function saveAndShowJson() {
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
        profileSyncChain = profileSyncChain.then(async() => {
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
                localBridge + "/api/status", { cache: "no-store" },
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
            empty.innerHTML = filter ?
                "<strong>NO MATCHES</strong> Try another profile name." :
                "<strong>NO PROFILES</strong> Create your first configuration profile.";
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

    function renderColorOptions() {
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
            const on = n.dataset.hex === hex;
            n.classList.toggle("selected", on);
            n.setAttribute("aria-pressed", on ? "true" : "false");
        });
        const custom = !!hex && !isPresetColor(hex);
        els.customColorBtn.classList.toggle("is-custom", custom);
        if (hex) {
            els.customColorBtn.style.setProperty("--picked-color", hex);
            els.customColorInput.value = hex;
        } else {
            els.customColorBtn.style.removeProperty("--picked-color");
        }
    }

    function applyColor(hex) {
        const s = activeSlot();
        if (!s) return;
        s.color = normalizeHex(hex);
        highlightSwatch(s.color);
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
        if (els.appPickerBtn) els.appPickerBtn.disabled = disabled;
        els.clearSlotBtn.disabled = disabled;
        els.customColorBtn.disabled = disabled;
        els.swatchRow.querySelectorAll(".swatch").forEach((sw) => {
            sw.disabled = disabled;
        });
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
            updateCommandKindUI("", "");
            highlightSwatch(null);
            return;
        }

        const isEmpty = !s.label && !s.command;
        els.activeSlotTag.textContent = p.name.toUpperCase().slice(0, 12) + " / " + pad2(s.index + 1);
        els.slotInfoKey.textContent = pad2(s.index + 1);
        els.slotInfoState.textContent = isEmpty ? "EMPTY" : "CONFIGURED";
        els.slotInfoState.className =
            "slot-state-badge mono " + (isEmpty ? "is-empty" : "is-configured");
        els.slotColorHex.textContent = colorName(s.color) + "  " + s.color;
        els.slotColorPreview.style.background = s.color;
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
        if (els.settingAppRelaunch) {
            els.settingAppRelaunch.value =
                s.appRelaunchMode === "minimize" || s.appRelaunchMode === "close" ?
                s.appRelaunchMode :
                "new";
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
        if (key === "ArrowLeft" && cur % 2 === 0) return;
        if (key === "ArrowRight" && cur % 2 === 1) return;
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
                language: state.settings.language,
                deviceName: state.settings.deviceName,
                brightness: state.settings.brightness,
                sleepTimeout: Number(state.settings.sleepTimeout),
                defaultProfile: (
                    state.profiles.find((p) => p.id === state.settings.defaultProfileId) ||
                    activeProfile() || {}
                ).name || null,
                wifiMode: state.settings.wifiMode,
                appRelaunchMode: state.settings.appRelaunchMode === "minimize" ||
                    state.settings.appRelaunchMode === "close" ?
                    state.settings.appRelaunchMode :
                    "new",
            },
            profiles: state.profiles.map((p) => ({
                id: p.id,
                name: p.name,
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
            language: els.settingLanguage.value || "en",
            deviceName: (els.settingDeviceName.value || "ADECK-UNO").trim().slice(0, 24),
            brightness: Number(els.settingBrightness.value) || 80,
            sleepTimeout: els.settingSleep.value || "60",
            defaultProfileId: els.settingDefaultProfile.value || null,
            wifiMode: els.settingWifi.value || "off",
            appRelaunchMode: ["minimize", "close"].includes(
                    els.settingAppRelaunch && els.settingAppRelaunch.value
                ) ?
                els.settingAppRelaunch.value :
                "new",
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
        state.settings = {...DEFAULT_SETTINGS, defaultProfileId: state.activeProfileId };
        applyTheme(state.settings.theme);
        persistSettings();
        renderSettingsForm();
        renderDeviceMeta();
        toast("SETTINGS RESET", "info");
    }

    /* ---------------------------------------------------------------
       Installed-app plumbing and local service control (System page)
       --------------------------------------------------------------- */

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
            els.offlineHint.textContent = hint.protocol ?
                "Use START SERVICE, or open ADeck from its desktop icon." :
                "Open ADeck from its desktop icon, or run Start ADeck.bat in the project folder.";
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
            localBridge + path, {
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
            localBridge + path, { cache: "no-store" },
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
        auto.textContent = ports.length ?
            "AUTO-DETECT (" + ports.length + " PORT" + (ports.length === 1 ? "" : "S") + ")" :
            "AUTO-DETECT";
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
        // /api/status is polled every 2s, so it wins over the slower system snapshot.
        const device = !state.backend.reachable ?
            null :
            status || (system && system.device) || null;

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
                ports.length ?
                "NOT CONNECTED · " + ports.length + " PORT(S) SEEN" + (arduino ? ", " + arduino + " ARDUINO" : "") :
                "NO SERIAL PORTS FOUND",
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
            els.sysAutostartBtn.textContent = integration.autostart ?
                "TURN OFF START WITH WINDOWS" :
                "START WITH WINDOWS";
        }
        if (els.sysShortcutBtn) {
            els.sysShortcutBtn.textContent = integration.desktop_shortcut ?
                "RECREATE DESKTOP ICON" :
                "CREATE DESKTOP ICON";
        }
        if (els.sysInstallBtn) els.sysInstallBtn.hidden = standalone || !installPrompt;
        if (els.sysInstallHint) {
            els.sysInstallHint.textContent = standalone ?
                "Running in its own window. The desktop icon starts the service and reopens this window." :
                installPrompt ?
                "INSTALL APP adds ADeck to Windows and opens it in its own window." :
                "No install prompt available yet — use your browser menu (Install ADeck), or the desktop icon created by setup.";
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
            // The service itself may be restarting as part of this task; keep waiting.
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
            /* task history was pruned or the service is down */
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
            message: "The board stops responding to key presses and this window loses its connection until ADeck is started again.",
            confirmLabel: "STOP",
            danger: true,
        });
        if (!ok) return;
        try {
            await apiPost("/api/control", { action: "stop" });
            toast("STOPPING ADECK SERVICE", "info");
            // The task's own output lives in the service we just stopped, so only
            // the connection state is tracked from here.
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
                        message: "The service stops and starts again. This window reconnects automatically after a few seconds.",
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
                        message: "Rebuilds the Python environment and Arduino CLI if needed, reflashes firmware only when the board does not answer, then restarts the service. This can take several minutes.",
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
                        message: "Stops the service and reflashes the UNO R4 WiFi. Keep the board plugged in with a data USB cable until it finishes.",
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
        installedAppsPromise = (async() => {
            try {
                const response = await fetchWithTimeout(
                    localBridge + "/api/apps", { cache: "no-store" },
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

    function applyPickerItem(item) {
        const s = activeSlot();
        if (!s || !item || !item.command) return;
        s.command = String(item.command).slice(0, COMMAND_MAX);
        s.kind = item.kind === "app" ? "app" : "command";
        const nextLabel = item.label || pickerLabel(item.name);
        if (nextLabel) s.label = nextLabel.slice(0, LABEL_MAX);
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
        if (els.settingTheme) {
            els.settingTheme.addEventListener("change", (e) => {
                applyTheme(e.target.value);
                persistSettings();
                toast(e.target.value === "dark" ? "DARK MODE" : "LIGHT MODE", "info");
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
            if (isAppPickerOpen()) {
                e.preventDefault();
                closeAppPicker();
                return;
            }
        }
        if (isDialogOpen()) return;
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
        renderColorOptions();
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
            // Live while the System page is open, occasional refresh elsewhere.
            if (state.currentPage === "system" || systemTick % 3 === 0) refreshSystem();
        }, 5000);
        tickClock();
        await pollBridgeStatus();
        await refreshSystem();
        await resumeTaskWatch();
        registerServiceWorker();
    }

    boot();
})();