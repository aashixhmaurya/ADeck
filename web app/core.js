"use strict";

const APP_VERSION = "2.1.0";
const BUILD_NUMBER = "2026.08.13-local";
const SLOTS_PER_PROFILE = 6;
const LABEL_MAX = 10;
const COMMAND_MAX = 256;
const PROFILE_NAME_MAX = 32;
const STORAGE_KEY = "adeck.cfg.v1";
const LEGACY_STORAGE_KEY = "macropad.cfg.v1";
const SETTINGS_KEY = "adeck.settings.v1";
const DEFAULT_COLOR = "#c5c5c3";
const DEFAULT_BACKGROUND = "#080d0e";
const GRID_COLS = 3;
const DEFAULT_ROTATION = 1;
const ROTATION_ORDER = [1, 0, 2, 3];
const ROTATION_DEGREES = { 1: 0, 0: 90, 2: 180, 3: 270 };
const TASK_WATCH_KEY = "adeck.task.v1";
const SERVICE_HINT_KEY = "adeck.servicehint.v1";

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

const ARROW_DELTA = {
  ArrowUp: -GRID_COLS,
  ArrowDown: GRID_COLS,
  ArrowLeft: -1,
  ArrowRight: 1,
};

const DEFAULT_APPEARANCE_ID = "classic";
const APPEARANCE_IDS = ["classic", "red-and-red", "3", "4"];
const APPEARANCE_LABELS = {
  classic: "CLASSIC",
  "red-and-red": "RED AND RED",
  "3": "CODE CACTUS",
  "4": "OLED",
};
const APPEARANCE_INFO = {
  classic: { name: "CLASSIC", description: "Current ADeck web colours." },
  "red-and-red": { name: "RED AND RED", description: "Dark panels, red selection, red accent." },
  "3": { name: "CODE CACTUS", description: "Cream page, rose selection, soft panels." },
  "4": { name: "OLED", description: "Pure black, dark blue. Dark only." },
};
const CLASSIC_WEB = {
  light: {
    "--bg": "#f2f1ee",
    "--bg-2": "#e4e3df",
    "--bg-3": "#cecdc8",
    "--ink": "#000000",
    "--ink-2": "#000000",
    "--muted": "#111111",
    "--line": "#000000",
    "--accent": "#6b4a12",
    "--sage": "#1f3d22",
    "--danger": "#7a1208",
    "--ok": "#1f3d22",
    "--slot-empty": "#b8b7b2",
    "--screen": "#0e0e0d",
    "--bezel": "#1a1a18",
    "--bezel-edge": "#3a3a37",
    "--panel-focus": "#ffffff",
    "--on-dark": "#f2f1ee",
    "--code-bg": "#0a0a0a",
    "--code-fg": "#ecebe6",
    "--toast-shadow": "#000000",
    "--active-bg": "#e8e7e2",
    "--active-fg": "#000000",
    "--hover-bg": "#ecebe6",
    "--btn-solid-bg": "#111111",
    "--btn-solid-fg": "#f2f1ee",
  },
  dark: {
    "--bg": "#181816",
    "--bg-2": "#222220",
    "--bg-3": "#2c2c28",
    "--ink": "#e4e2dc",
    "--ink-2": "#cac8c0",
    "--muted": "#8e8c84",
    "--line": "#3d3d38",
    "--accent": "#d4a843",
    "--sage": "#9aab7a",
    "--danger": "#c97860",
    "--ok": "#9aab7a",
    "--slot-empty": "#454540",
    "--screen": "#0a0a09",
    "--bezel": "#121210",
    "--bezel-edge": "#333330",
    "--panel-focus": "#262624",
    "--on-dark": "#e4e2dc",
    "--code-bg": "#0e0e0c",
    "--code-fg": "#e4e2dc",
    "--toast-shadow": "#000000",
    "--active-bg": "#2a2a27",
    "--active-fg": "#f0ede6",
    "--hover-bg": "#242422",
    "--btn-solid-bg": "#353532",
    "--btn-solid-fg": "#f0ede6",
  },
};
const RED_AND_RED_PALETTE = {
  "--bg": "#1f1617",
  "--bg-2": "#2a2021",
  "--bg-3": "#3a2a2d",
  "--ink": "#f6f1f7",
  "--ink-2": "#fdf5f2",
  "--muted": "#655659",
  "--line": "#3a2a2d",
  "--accent": "#c8384f",
  "--sage": "#d7ff6a",
  "--danger": "#ec364f",
  "--ok": "#d7ff6a",
  "--slot-empty": "#3a3031",
  "--screen": "#090b0a",
  "--bezel": "#151112",
  "--bezel-edge": "#2f2526",
  "--panel-focus": "#2f2526",
  "--on-dark": "#f6f1f7",
  "--code-bg": "#151112",
  "--code-fg": "#f6f1f7",
  "--toast-shadow": "#000000",
  "--active-bg": "#c8384f",
  "--active-fg": "#ffe8f0",
  "--hover-bg": "#2f2526",
  "--btn-solid-bg": "#c8384f",
  "--btn-solid-fg": "#ffe8f0",
};
const RED_AND_RED_WEB = {
  light: Object.assign({}, RED_AND_RED_PALETTE, {
    "--bg": "#38282a",
    "--bg-2": "#443336",
    "--bg-3": "#524044",
    "--line": "#524044",
    "--slot-empty": "#524446",
    "--panel-focus": "#473c3d",
    "--hover-bg": "#473c3d",
    "--bezel-edge": "#473c3d",
  }),
  dark: RED_AND_RED_PALETTE,
};
const ROSE_PINE_DAWN_WEB = {
  light: {
    "--bg": "#fcf2e9",
    "--bg-2": "#f2e9e0",
    "--bg-3": "#e2d9d2",
    "--ink": "#1f3d22",
    "--ink-2": "#2f5c3a",
    "--muted": "#4a6b52",
    "--line": "#d5e0d4",
    "--accent": "#2f7a4a",
    "--sage": "#2f7a4a",
    "--danger": "#aa586f",
    "--ok": "#2f7a4a",
    "--slot-empty": "#d5e0d4",
    "--screen": "#191724",
    "--bezel": "#26233a",
    "--bezel-edge": "#3b4054",
    "--panel-focus": "#fbf4ec",
    "--on-dark": "#fcf2e9",
    "--code-bg": "#fffaf3",
    "--code-fg": "#1f3d22",
    "--toast-shadow": "#1f3d22",
    "--active-bg": "#2f7a4a",
    "--active-fg": "#fcf2e9",
    "--hover-bg": "#dce8dc",
    "--btn-solid-bg": "#2f7a4a",
    "--btn-solid-fg": "#fcf2e9",
  },
  dark: {
    "--bg": "#191724",
    "--bg-2": "#1f1d2e",
    "--bg-3": "#26233a",
    "--ink": "#b8e0c0",
    "--ink-2": "#8fbf96",
    "--muted": "#6e8a72",
    "--line": "#403d52",
    "--accent": "#7dce82",
    "--sage": "#7dce82",
    "--danger": "#eb6f92",
    "--ok": "#7dce82",
    "--slot-empty": "#403d52",
    "--screen": "#0f0e14",
    "--bezel": "#191724",
    "--bezel-edge": "#403d52",
    "--panel-focus": "#26233a",
    "--on-dark": "#e8f6ea",
    "--code-bg": "#0f0e14",
    "--code-fg": "#b8e0c0",
    "--toast-shadow": "#000000",
    "--active-bg": "#2f7a4a",
    "--active-fg": "#e8f6ea",
    "--hover-bg": "#26233a",
    "--btn-solid-bg": "#2f7a4a",
    "--btn-solid-fg": "#e8f6ea",
  },
};
const OLED_PALETTE = {
  "--bg": "#000000",
  "--bg-2": "#000000",
  "--bg-3": "#000000",
  "--ink": "#e8eef8",
  "--ink-2": "#c5d0e0",
  "--muted": "#6b7a90",
  "--line": "#122033",
  "--accent": "#163a6b",
  "--sage": "#1a4a80",
  "--danger": "#c97860",
  "--ok": "#1a4a80",
  "--slot-empty": "#000000",
  "--screen": "#000000",
  "--bezel": "#000000",
  "--bezel-edge": "#122033",
  "--panel-focus": "#000000",
  "--on-dark": "#e8eef8",
  "--code-bg": "#000000",
  "--code-fg": "#e8eef8",
  "--toast-shadow": "#000000",
  "--active-bg": "#163a6b",
  "--active-fg": "#e8eef8",
  "--hover-bg": "#000000",
  "--btn-solid-bg": "#163a6b",
  "--btn-solid-fg": "#e8eef8",
};
const OLED_WEB = {
  light: OLED_PALETTE,
  dark: OLED_PALETTE,
};

const DEFAULT_SETTINGS = {
  theme: "light",
  appearance: DEFAULT_APPEARANCE_ID,
  deviceName: "ADECK-UNO",
  sleepTimeout: "60",
  sleepMode: "black",
  sleepImage: "",
  defaultProfileId: null,
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
  settings: { ...DEFAULT_SETTINGS },
  storageOk: true,
  device: { ...DEVICE_PLACEHOLDER },
  backend: {
    reachable: true,
    failures: 0,
    status: null,
    system: null,
    busy: false,
  },
};

const SERVICE_TASKS = new Set(["restart", "repair", "reinstall-firmware", "stop"]);
let taskWatch = null;
let installPrompt = null;

function normalizeHex(hex) {
  const raw = String(hex || "").trim().toLowerCase();
  if (/^#[0-9a-f]{6}$/.test(raw)) return raw;
  if (/^[0-9a-f]{6}$/.test(raw)) return "#" + raw;
  return DEFAULT_COLOR;
}

function newProfileId() {
  return "p_" + Math.random().toString(36).slice(2, 9);
}

function makeSlot(i) {
  return { index: i, label: "", command: "", kind: "", color: DEFAULT_COLOR };
}

function normalizeRotation(value) {
  const n = Number(value);
  if (Number.isInteger(n) && n >= 0 && n <= 3) return n;
  return DEFAULT_ROTATION;
}

function rotationDegrees(rotation) {
  return ROTATION_DEGREES[normalizeRotation(rotation)] ?? 0;
}

function nextRotation(rotation) {
  const current = normalizeRotation(rotation);
  const index = ROTATION_ORDER.indexOf(current);
  return ROTATION_ORDER[((index < 0 ? 0 : index) + 1) % ROTATION_ORDER.length];
}

function isPortraitRotation(rotation) {
  const r = normalizeRotation(rotation);
  return r === 0 || r === 2;
}

function isFlippedRotation(rotation) {
  const r = normalizeRotation(rotation);
  return r === 2 || r === 3;
}

function makeProfile(name) {
  return {
    id: newProfileId(),
    name: String(name || "Untitled").slice(0, PROFILE_NAME_MAX),
    theme: DEFAULT_DECK_THEME,
    rotation: DEFAULT_ROTATION,
    background: DEFAULT_BACKGROUND,
    slots: Array.from({ length: SLOTS_PER_PROFILE }, (_, i) => makeSlot(i)),
  };
}

function cloneProfile(source, newName) {
  const p = makeProfile(newName || source.name + " Copy");
  p.theme = normalizeThemeId(source.theme);
  p.rotation = normalizeRotation(source.rotation);
  p.background = normalizeHex(source.background || DEFAULT_BACKGROUND);
  p.slots = source.slots.map((s, i) => ({
    index: i,
    label: String(s.label || "").slice(0, LABEL_MAX),
    command: String(s.command || "").slice(0, COMMAND_MAX),
    kind: s.kind === "app" || s.kind === "command" ? s.kind : "",
    color: normalizeHex(s.color),
  }));
  return p;
}

function profileBackground(profile) {
  if (!profile) return DEFAULT_BACKGROUND;
  return normalizeHex(profile.background || DEFAULT_BACKGROUND);
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


function normalizeProfile(raw) {
  const themeId = normalizeThemeId(raw.theme);
  const theme = deckTheme(themeId);
  const themeBg =
    theme && theme.tft && theme.tft.background
      ? normalizeHex(theme.tft.background)
      : DEFAULT_BACKGROUND;
  return {
    id: raw.id || newProfileId(),
    name: String(raw.name || "Untitled").slice(0, PROFILE_NAME_MAX),
    theme: themeId,
    rotation: normalizeRotation(raw.rotation),
    background: raw.background ? normalizeHex(raw.background) : themeBg,
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
  themeBtn: $("themeBtn"),
  themeBtnName: $("themeBtnName"),
  rotateBtn: $("rotateBtn"),
  rotateBtnDeg: $("rotateBtnDeg"),
  buttonGrid: $("buttonGrid"),
  deviceFrame: $("deviceFrame"),
  deviceConnBadge: $("deviceConnBadge"),
  deviceScreen: $("deviceScreen"),
  screenActiveKey: $("screenActiveKey"),
  screenProfileName: $("screenProfileName"),
  topStateDot: $("topStateDot"),
  activeSlotTag: $("activeSlotTag"),
  slotInfoKey: $("slotInfoKey"),
  slotInfoState: $("slotInfoState"),
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
  customColorBtn: $("customColorBtn"),
  customColorInput: $("customColorInput"),
  bgColorSwatch: $("bgColorSwatch"),
  clearSlotBtn: $("clearSlotBtn"),
  statusLine: $("statusLine"),
  clock: $("clock"),
  footerDirty: $("footerDirty"),
  footerProfile: $("footerProfile"),
  saveBtn: $("saveBtn"),
  themeToggleBtn: $("themeToggleBtn"),
  themeToggleLabel: $("themeToggleLabel"),
  appearanceBtn: $("appearanceBtn"),
  appearanceBtnName: $("appearanceBtnName"),
  appearanceModal: $("appearanceModal"),
  appearanceList: $("appearanceList"),
  appearancePreview: $("appearancePreview"),
  appearanceStatus: $("appearanceStatus"),
  appearanceApplyBtn: $("appearanceApplyBtn"),
  appearanceCancelBtn: $("appearanceCancelBtn"),
  settingAppearance: $("settingAppearance"),
  jsonModal: $("jsonModal"),
  themeModal: $("themeModal"),
  themeList: $("themeList"),
  themeTft: $("themeTft"),
  themeTftGrid: $("themeTftGrid"),
  themeStatus: $("themeStatus"),
  themeApplyBtn: $("themeApplyBtn"),
  themeCancelBtn: $("themeCancelBtn"),
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
  settingDeviceName: $("settingDeviceName"),
  settingSleep: $("settingSleep"),
  settingSleepMode: $("settingSleepMode"),
  settingSleepImage: $("settingSleepImage"),
  sleepImagePickBtn: $("sleepImagePickBtn"),
  sleepImageField: $("sleepImageField"),
  sleepImagePreview: $("sleepImagePreview"),
  settingDefaultProfile: $("settingDefaultProfile"),
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
  dev.slots[0] = { index: 0, label: "CODE", command: "code", color: "#255a8c" };
  dev.slots[1] = { index: 1, label: "TERM", command: "wt", color: "#2c3238" };
  dev.slots[2] = { index: 2, label: "GIT", command: "git status", color: "#1f6b52" };
  dev.slots[3] = { index: 3, label: "EXPLORER", command: "explorer .", color: "#c5c5c3" };
  dev.slots[4] = { index: 4, label: "NOTEPAD", command: "notepad", color: "#b42318" };
  dev.slots[5] = { index: 5, label: "CALC", command: "calc", color: "#0a0a0a" };
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
    state.activeProfileId = state.profiles.find((p) => p.id === parsed.activeProfileId)
      ? parsed.activeProfileId
      : state.profiles[0].id;
    state.activeSlotIndex = Number.isInteger(parsed.activeSlotIndex)
      ? Math.max(0, Math.min(SLOTS_PER_PROFILE - 1, parsed.activeSlotIndex))
      : 0;
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
  const keptAppearance = normalizeAppearance(state.settings.appearance);
  if (config.settings && typeof config.settings === "object") {
    state.settings = { ...state.settings, ...config.settings };
    const defaultName = config.settings.defaultProfile;
    const defaultProfile = profiles.find((profile) => profile.name === defaultName);
    if (defaultProfile) state.settings.defaultProfileId = defaultProfile.id;
  }
  state.settings.appearance = keptAppearance;
  persistProfiles();
  persistSettings();
  return true;
}

function loadSettings() {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) {
      state.settings.appearance = DEFAULT_APPEARANCE_ID;
      return;
    }
    const parsed = JSON.parse(raw);
    const stored = parsed && typeof parsed === "object" ? parsed : {};
    state.settings = { ...DEFAULT_SETTINGS, ...stored };
    state.settings.appearance =
      Object.prototype.hasOwnProperty.call(stored, "appearance")
        ? normalizeAppearance(stored.appearance)
        : DEFAULT_APPEARANCE_ID;
  } catch (_) {
    state.settings.appearance = DEFAULT_APPEARANCE_ID;
  }
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

const DEFAULT_DECK_THEME = "adeck-classic";
const THEMES_CACHE_KEY = "adeck.themes.v3";

let themeRegistry = null;
let appliedThemeVars = [];

function defaultDeckThemeId() {
  return (themeRegistry && themeRegistry.default) || DEFAULT_DECK_THEME;
}

function themeList() {
  return themeRegistry && Array.isArray(themeRegistry.themes) ? themeRegistry.themes : [];
}

function deckTheme(themeId) {
  const key = String(themeId || "").trim().toLowerCase();
  const list = themeList();
  return list.find((t) => t.id === key) || null;
}

function normalizeThemeId(themeId) {
  const key = String(themeId || "").trim().toLowerCase();
  if (!themeRegistry) {
    return /^[a-z0-9][a-z0-9-]{0,31}$/.test(key) ? key : DEFAULT_DECK_THEME;
  }
  return deckTheme(key) ? key : defaultDeckThemeId();
}

function deckThemeName(themeId) {
  const theme = deckTheme(themeId);
  return theme ? theme.name : "Space";
}

function deckThemeShort(themeId) {
  const theme = deckTheme(themeId);
  if (theme && theme.short) return String(theme.short).toUpperCase();
  return deckThemeName(themeId).toUpperCase();
}

async function loadThemes() {
  let payload = null;
  try {
    const res = await fetchWithTimeout("/api/themes", {}, 4000);
    if (res && res.ok) payload = await res.json();
  } catch (err) {
    payload = null;
  }
  if (payload && Array.isArray(payload.themes) && payload.themes.length) {
    themeRegistry = payload;
    try {
      localStorage.setItem(THEMES_CACHE_KEY, JSON.stringify(payload));
    } catch (err) {}
    return true;
  }
  try {
    const cached = JSON.parse(localStorage.getItem(THEMES_CACHE_KEY) || "null");
    if (cached && Array.isArray(cached.themes) && cached.themes.length) {
      themeRegistry = cached;
      return true;
    }
  } catch (err) {}
  return false;
}

function themeVarRoots() {
  return [document.documentElement, document.body].filter(Boolean);
}

function clearDeckThemeVars() {
  const roots = themeVarRoots();
  appliedThemeVars.forEach((key) => {
    roots.forEach((root) => root.style.removeProperty(key));
  });
  appliedThemeVars = [];
}

function normalizeAppearance(id) {
  let key = String(id || "").trim().toLowerCase();
  if (key === "2") key = "red-and-red";
  return APPEARANCE_IDS.indexOf(key) >= 0 ? key : DEFAULT_APPEARANCE_ID;
}

function appearanceLabel(id) {
  return APPEARANCE_LABELS[normalizeAppearance(id)] || APPEARANCE_LABELS[DEFAULT_APPEARANCE_ID];
}

function appearanceInfo(id) {
  return APPEARANCE_INFO[normalizeAppearance(id)] || APPEARANCE_INFO[DEFAULT_APPEARANCE_ID];
}

function appearanceList() {
  return APPEARANCE_IDS.map((id) => ({
    id: id,
    name: appearanceInfo(id).name,
    description: appearanceInfo(id).description,
  }));
}

function appearanceForcesDark(id) {
  return normalizeAppearance(id) === "4";
}

function appearancePalette(id, mode) {
  const key = normalizeAppearance(id);
  const resolved = mode === "dark" ? "dark" : "light";
  if (key === "red-and-red") return RED_AND_RED_WEB[resolved];
  if (key === "3") return ROSE_PINE_DAWN_WEB[resolved];
  if (key === "4") return OLED_WEB[resolved];
  return CLASSIC_WEB[resolved];
}

function activeAppearanceId() {
  if (typeof appearanceModal !== "undefined" && appearanceModal.open) {
    return normalizeAppearance(appearanceModal.selectedId);
  }
  return normalizeAppearance(state.settings.appearance);
}

function updateAppearanceUi() {
  const appearanceId = normalizeAppearance(state.settings.appearance);
  if (els.appearanceBtnName) els.appearanceBtnName.textContent = appearanceLabel(appearanceId);
  if (els.appearanceBtn) {
    els.appearanceBtn.title = "Appearance: " + appearanceLabel(appearanceId);
    els.appearanceBtn.setAttribute(
      "aria-expanded",
      typeof appearanceModal !== "undefined" && appearanceModal.open ? "true" : "false"
    );
  }
  if (els.settingAppearance) els.settingAppearance.value = appearanceId;
}

function applyAppearance(id) {
  state.settings.appearance = normalizeAppearance(id);
  if (appearanceForcesDark(state.settings.appearance)) {
    applyTheme("dark");
  } else {
    applyActiveDeckTheme();
  }
  persistSettings();
  toast("APPEARANCE " + appearanceLabel(state.settings.appearance), "info");
}

function applyDeckTheme(themeId) {
  const roots = themeVarRoots();
  const root = document.documentElement;
  const theme = deckTheme(themeId);
  clearDeckThemeVars();
  if (!theme) {
    root.removeAttribute("data-deck-theme");
  } else {
    root.setAttribute("data-deck-theme", theme.id);
  }
  const appearanceId = activeAppearanceId();
  const mode = state.settings.theme === "dark" ? "dark" : "light";
  const palette = appearancePalette(appearanceId, mode) || {};
  Object.keys(palette).forEach((key) => {
    roots.forEach((node) => node.style.setProperty(key, palette[key]));
    appliedThemeVars.push(key);
  });
  roots.forEach((node) => node.setAttribute("data-web-appearance", appearanceId));
  updateAppearanceUi();
}

function activeDeckThemeId() {
  const profile = activeProfile();
  return normalizeThemeId(profile ? profile.theme : "");
}

function applyActiveDeckTheme() {
  const id = themeModal.open ? themeModal.selectedId : activeDeckThemeId();
  applyDeckTheme(id);
  if (els.themeBtnName) els.themeBtnName.textContent = deckThemeShort(activeDeckThemeId());
  if (els.themeBtn) els.themeBtn.title = "Theme: " + deckThemeName(activeDeckThemeId());
  updateRotationUi();
}

function activeRotation() {
  const profile = activeProfile();
  return normalizeRotation(profile ? profile.rotation : DEFAULT_ROTATION);
}

function applyPreviewOrientation(root, rotation) {
  if (!root) return;
  const value = normalizeRotation(rotation);
  root.dataset.rotation = String(value);
  root.classList.toggle("is-portrait", isPortraitRotation(value));
  root.classList.toggle("is-flipped", isFlippedRotation(value));
}

function updateRotationUi() {
  const rotation = activeRotation();
  const degrees = rotationDegrees(rotation);
  if (els.rotateBtnDeg) els.rotateBtnDeg.textContent = degrees + "°";
  if (els.rotateBtn) {
    els.rotateBtn.title = "Rotate TFT (" + degrees + "°) — click to cycle";
  }
  applyPreviewOrientation(els.deviceFrame, rotation);
  applyPreviewOrientation(els.deviceScreen, rotation);
  applyPreviewOrientation(els.buttonGrid, rotation);
  applyPreviewOrientation(els.themeTft, rotation);
  applyPreviewOrientation(els.themeTftGrid, rotation);
}

function cycleActiveRotation() {
  const p = activeProfile();
  if (!p) return;
  p.rotation = nextRotation(p.rotation);
  markDirty(true);
  persistProfiles();
  updateRotationUi();
  renderGrid();
  renderDeviceMeta();
  if (themeModal.open) renderThemePreview();
  syncActiveProfile();
  toast("ROTATE " + rotationDegrees(p.rotation) + "°", "success");
}

function afterSlotFieldEdit() {
  renderGrid();
  renderProfiles();
  renderDeviceMeta();
  markDirty(true);
  persistProfiles();
}

function applyTheme(theme, animate = true) {
  let mode = theme === "dark" ? "dark" : "light";
  if (appearanceForcesDark(activeAppearanceId())) mode = "dark";
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
  applyActiveDeckTheme();
  if (themeModal.open) {
    renderThemeCards();
    renderThemePreview();
  }
}

function toggleTheme() {
  const next = state.settings.theme === "dark" ? "light" : "dark";
  applyTheme(next);
  persistSettings();
  toast(state.settings.theme === "dark" ? "DARK MODE" : "LIGHT MODE", "info");
}

