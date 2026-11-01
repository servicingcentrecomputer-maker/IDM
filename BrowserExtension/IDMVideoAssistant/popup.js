"use strict";

const ACTIVE_STATUSES = new Set([
  "Queued",
  "Connecting",
  "Downloading",
  "Retrying",
  "Pausing",
  "Paused",
  "Stopping",
]);

const NO_RESPONSE = "no_response";
const SEND_ATTEMPTS = 3;

const el = {
  version: document.getElementById("version"),
  connection: document.getElementById("connection"),
  test: document.getElementById("test-connection"),
  notice: document.getElementById("notice"),
  detectToggle: document.getElementById("detect-toggle"),
  detectHint: document.getElementById("detect-hint"),
  fileTypes: document.getElementById("file-types"),
  saveTypes: document.getElementById("save-types"),
  mediaHeading: document.getElementById("media-heading"),
  pageDomain: document.getElementById("page-domain"),
  refreshMedia: document.getElementById("refresh-media"),
  restrictedBox: document.getElementById("restricted-box"),
  restrictedTitle: document.getElementById("restricted-title"),
  restrictedText: document.getElementById("restricted-text"),
  officialBox: document.getElementById("official-box"),
  officialHeading: document.getElementById("official-heading"),
  officialList: document.getElementById("official-list"),
  officialNote: document.getElementById("official-note"),
  openOfficial: document.getElementById("open-official"),
  detectOff: document.getElementById("detect-off"),
  mediaList: document.getElementById("media-list"),
  mediaEmpty: document.getElementById("media-empty"),
  transferList: document.getElementById("transfer-list"),
  transferEmpty: document.getElementById("transfer-empty"),
  hostVersion: document.getElementById("host-version"),
  lastResult: document.getElementById("last-result"),
  autoIntercept: document.getElementById("auto-intercept"),
  askFolder: document.getElementById("ask-folder"),
  notifyAdd: document.getElementById("notify-add"),
  openIdm: document.getElementById("open-idm"),
  openSettings: document.getElementById("open-settings"),
  copyId: document.getElementById("copy-id"),
  manageExtension: document.getElementById("manage-extension"),
  browserName: document.getElementById("browser-name"),
};

let tab = null;
let stateData = null;
let settings = {
  autoIntercept: true,
  askFolder: false,
  detectionEnabled: true,
  notifyOnAdd: true,
  fileTypes: IDMDetector.DEFAULT_FILE_TYPES.join(","),
};
let loading = false;
let sending = false;
let typesDirty = false;
let pollTimer = null;
let noticeTimer = null;
let noticeSource = "";
let lastOfficialUrl = "";

document.addEventListener("DOMContentLoaded", () => {
  el.version.textContent = "v" + chrome.runtime.getManifest().version;
  el.browserName.textContent =
    IDMNative.BROWSER === "edge" ? "Microsoft Edge" : "Google Chrome";
  bindActions();
  renderSettings();
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    void chrome.runtime.lastError;
    tab = Array.isArray(tabs) && tabs.length ? tabs[0] : null;
    void refresh();
    pollTimer = setInterval(() => void refresh({ quiet: true }), 3000);
  });
  window.addEventListener("unload", () => {
    if (pollTimer) clearInterval(pollTimer);
  });
});

function bindActions() {
  el.test.addEventListener("click", () => void testConnection());
  el.refreshMedia.addEventListener("click", () => void rescan(true));
  el.openOfficial.addEventListener("click", () => void openOfficialPage());
  el.saveTypes.addEventListener("click", () => void saveFileTypes());
  el.fileTypes.addEventListener("input", () => {
    typesDirty = true;
  });
  el.fileTypes.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      void saveFileTypes();
    }
  });

  el.detectToggle.addEventListener("change", () => {
    void toggleSetting("detectionEnabled", el.detectToggle.checked);
  });
  el.autoIntercept.addEventListener("change", () => {
    void toggleSetting("autoIntercept", el.autoIntercept.checked);
  });
  el.askFolder.addEventListener("change", () => {
    void toggleSetting("askFolder", el.askFolder.checked);
  });
  el.notifyAdd.addEventListener("change", () => {
    void toggleSetting("notifyOnAdd", el.notifyAdd.checked);
  });

  el.openIdm.addEventListener("click", () => void openNativeTarget("idm:openIdm", "IDM"));
  el.openSettings.addEventListener("click", () =>
    void openNativeTarget("idm:openSettings", "Download settings")
  );
  el.copyId.addEventListener("click", () => void copyExtensionId());
  el.manageExtension.addEventListener("click", () => void openExtensionDetails());
}

// ------------------------------------------------------------------ messaging

function sendOnce(message) {
  return new Promise((resolve) => {
    try {
      chrome.runtime.sendMessage(message, (response) => {
        if (chrome.runtime.lastError) {
          resolve(noResponse(chrome.runtime.lastError.message));
          return;
        }
        resolve(response || noResponse());
      });
    } catch (error) {
      resolve(noResponse(String(error && error.message ? error.message : error)));
    }
  });
}

async function send(message) {
  let response = null;
  for (let attempt = 0; attempt < SEND_ATTEMPTS; attempt += 1) {
    if (attempt > 0) await delay(150 * attempt);
    response = await sendOnce(message);
    if (!response || !response.error || response.error.code !== NO_RESPONSE) {
      return response;
    }
  }
  return response;
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function noResponse(message) {
  return {
    ok: false,
    error: {
      code: NO_RESPONSE,
      message:
        typeof message === "string" && message
          ? message
          : "The IDM assistant did not respond. Close this popup and try again.",
    },
  };
}

// ------------------------------------------------------------------ refresh

async function refresh(options) {
  const quiet = Boolean(options && options.quiet);
  if (loading) return;
  loading = true;
  if (!quiet) setConnection("checking", "Checking");
  try {
    const tabId = tab && Number.isInteger(tab.id) ? tab.id : null;
    const state = await send({ type: "idm:getState", tabId: tabId });
    if (!state || !state.ok) {
      setDisconnected(
        (state && state.error) || "IDM state could not be read."
      );
      renderMedia(emptyMedia());
      return;
    }
    stateData = state;
    applySettings(state.settings);
    renderSettings();
    renderConnection(state);
    renderMedia(state.media || emptyMedia());
    renderTransfers(state.downloads || []);
    el.hostVersion.textContent = state.hostVersion
      ? "Host " + state.hostVersion
      : "";
  } catch (error) {
    setDisconnected(String(error && error.message ? error.message : error));
    renderMedia(emptyMedia());
  } finally {
    loading = false;
  }
  await renderLastResult();
}

function applySettings(values) {
  if (!values || typeof values !== "object") return;
  if ("autoIntercept" in values) settings.autoIntercept = values.autoIntercept !== false;
  if ("askFolder" in values) settings.askFolder = values.askFolder === true;
  if ("detectionEnabled" in values) {
    settings.detectionEnabled = values.detectionEnabled !== false;
  }
  if ("notifyOnAdd" in values) settings.notifyOnAdd = values.notifyOnAdd !== false;
  if ("fileTypes" in values) {
    settings.fileTypes = IDMDetector.fileTypesText(values.fileTypes);
  }
}

function renderSettings() {
  el.detectToggle.checked = settings.detectionEnabled !== false;
  el.autoIntercept.checked = settings.autoIntercept !== false;
  el.askFolder.checked = settings.askFolder === true;
  el.notifyAdd.checked = settings.notifyOnAdd !== false;
  if (!typesDirty && document.activeElement !== el.fileTypes) {
    el.fileTypes.value = settings.fileTypes || IDMDetector.DEFAULT_FILE_TYPES.join(",");
  }
  el.detectHint.textContent = settings.detectionEnabled
    ? "Detection only inspects the page you are on. It does not read browsing history."
    : "Detection is off. Browser downloads can still be sent to IDM.";
}

function renderConnection(state) {
  const connected = Boolean(state && state.connected);
  if (!connected) {
    setDisconnected(
      friendlyError(
        state && state.lastError
          ? { error: state.lastError }
          : (state && state.status) || { error: {} }
      )
    );
    return;
  }
  setConnection("connected", "Connected");
  const version = state.status && state.status.idm_version;
  el.connection.title = version ? "IDM " + version : "IDM is running";
  if (noticeSource === "connection") hideNotice();
}

function setConnection(kind, text) {
  el.connection.textContent = text;
  el.connection.className = "status status-" + kind;
}

function setDisconnected(message) {
  setConnection("error", "Not connected");
  el.connection.title = "";
  showNotice(
    message || "IDM is not reachable. Start IDM and try again.",
    "error",
    0,
    "connection"
  );
}

// ------------------------------------------------------------------ media

function emptyMedia() {
  return {
    page: { url: "", title: "", domain: "" },
    items: [],
    restricted: null,
  };
}

function currentPageUrl(media) {
  return (
    (media && media.page && media.page.url) ||
    (tab && typeof tab.url === "string" ? tab.url : "") ||
    ""
  );
}

function isScannablePage(url) {
  return /^https?:\/\//i.test(String(url || ""));
}

function renderMedia(media) {
  const enabled = settings.detectionEnabled !== false;
  const page = (media && media.page) || {};
  const pageUrl = currentPageUrl(media);
  const domain = page.domain || IDMDetector.domainOf(pageUrl);
  el.pageDomain.textContent = domain || "This page";
  el.pageDomain.title = pageUrl || "";

  if (!enabled) {
    el.mediaHeading.textContent = "Media on this page";
    show(el.detectOff);
    hide(el.restrictedBox);
    clearOfficial();
    hide(el.mediaList);
    hide(el.mediaEmpty);
    el.mediaList.replaceChildren();
    return;
  }
  hide(el.detectOff);

  if (media && media.restricted) {
    const platform = media.restricted.platform || "This platform";
    lastOfficialUrl = media.restricted.page_url || pageUrl;
    el.mediaHeading.textContent = "Media on this page";
    el.restrictedTitle.textContent = platform + " page";
    el.restrictedText.textContent =
      media.restricted.message || IDMDetector.restrictionMessage(platform);
    el.openOfficial.disabled = !IDMDetector.isHttpUrl(lastOfficialUrl);
    renderOfficial(media.restricted);
    show(el.restrictedBox);
    hide(el.mediaList);
    hide(el.mediaEmpty);
    el.mediaList.replaceChildren();
    return;
  }
  hide(el.restrictedBox);
  clearOfficial();

  const items = Array.isArray(media && media.items) ? media.items : [];
  el.mediaHeading.textContent = items.length
    ? "Media on this page (" + items.length + ")"
    : "Media on this page";

  if (!items.length) {
    hide(el.mediaList);
    el.mediaList.replaceChildren();
    el.mediaEmpty.textContent = isScannablePage(pageUrl) || pageUrl
      ? "No direct media links were found on this page. IDM only downloads media URLs you are authorised to transfer."
      : "IDM can only scan http and https pages. Open a normal web page to detect direct media links.";
    show(el.mediaEmpty);
    return;
  }
  hide(el.mediaEmpty);
  renderMediaList(items, page);
  show(el.mediaList);
}

function renderMediaList(items, page) {
  el.mediaList.replaceChildren();
  for (const item of items) {
    el.mediaList.appendChild(mediaRow(item, page));
  }
}

function clearOfficial() {
  el.officialList.replaceChildren();
  el.officialHeading.textContent = "";
  el.officialNote.textContent = "";
  hide(el.officialBox);
}

function renderOfficial(restricted) {
  clearOfficial();
  const official = restricted && restricted.official;
  const links = official && Array.isArray(official.links) ? official.links : [];
  if (!links.length) return;
  el.officialHeading.textContent = official.heading || "Official download options";
  el.officialNote.textContent = official.note || "";
  for (const option of links) {
    if (!option || !IDMDetector.isHttpUrl(option.url)) continue;
    const row = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary";
    button.textContent = option.label || option.url;
    button.title = option.description || option.url;
    button.addEventListener("click", () => void openOfficialLink(option.url));
    const description = document.createElement("span");
    description.className = "official-description";
    description.textContent = option.description || "";
    row.append(button, description);
    el.officialList.appendChild(row);
  }
  if (el.officialList.childElementCount) show(el.officialBox);
}

async function openOfficialLink(url) {
  if (!IDMDetector.isHttpUrl(url)) {
    showNotice("That official option has no valid HTTP address.", "error", 6000);
    return;
  }
  const response = await send({ type: "idm:openPage", url: url });
  if (!response || !response.ok) {
    showNotice(friendlyError(response), "error", 7000);
  }
}

function mediaRow(item, page) {
  const row = document.createElement("li");
  row.className = "media-item";

  const head = document.createElement("div");
  head.className = "item-head";
  const title = document.createElement("span");
  title.className = "item-title";
  title.textContent = item.title || item.filename || "Media link";
  title.title = title.textContent;
  const kind = document.createElement("span");
  kind.className = "item-kind";
  kind.textContent = kindLabel(item);
  head.append(title, kind);

  const meta = document.createElement("div");
  meta.className = "item-meta";
  const format = String(item.format || item.extension || "").toUpperCase();
  if (format) meta.appendChild(chip(format));
  if (Number.isFinite(item.size_bytes) && item.size_bytes > 0) {
    meta.appendChild(chip(formatBytes(item.size_bytes)));
  }
  if (item.quality_label) meta.appendChild(chip(item.quality_label));
  if (Number.isFinite(item.duration_seconds) && item.duration_seconds > 0) {
    meta.appendChild(chip(formatDuration(item.duration_seconds)));
  }
  meta.appendChild(chip(item.size_bytes ? "Size known" : "Size unavailable"));

  const url = document.createElement("div");
  url.className = "item-url";
  url.textContent = item.url;
  url.title = item.url;

  const actions = document.createElement("div");
  actions.className = "item-actions";
  const send = document.createElement("button");
  send.type = "button";
  send.className = "secondary";
  send.textContent = "Send to IDM";
  send.addEventListener("click", () => void sendItem(item, send, page));
  actions.appendChild(send);

  row.append(head, meta, url, actions);
  return row;
}

function chip(text) {
  const span = document.createElement("span");
  span.className = "chip";
  span.textContent = text;
  return span;
}

function kindLabel(item) {
  if (item.media_kind === "audio") return "Audio";
  if (item.media_kind === "video") return "Video";
  return "File";
}

async function sendItem(item, button, page) {
  if (sending || !item) return;
  sending = true;
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "Sending…";
  try {
    const response = await send({
      type: "idm:sendMedia",
      tabId: tab && Number.isInteger(tab.id) ? tab.id : null,
      item: item,
      requestId: IDMNative.createRequestId(),
    });
    if (response && response.ok) {
      button.disabled = true;
      button.textContent = "Added";
      button.classList.add("added");
      showNotice(
        response.duplicate
          ? "\u201c" + response.filename + "\u201d is already downloading in IDM."
          : "Added \u201c" + response.filename + "\u201d to IDM.",
        "success",
        6000
      );
      await renderLastResult();
      void refresh({ quiet: true });
      return;
    }
    button.disabled = false;
    button.textContent = original;
    if (response && response.cancelled) return;
    showNotice(friendlyError(response), "error", 9000);
  } finally {
    sending = false;
  }
}

async function rescan(announce) {
  el.refreshMedia.disabled = true;
  try {
    const response = await send({
      type: "idm:getMedia",
      tabId: tab && Number.isInteger(tab.id) ? tab.id : null,
      force: true,
    });
    if (response && response.ok) {
      renderMedia(response.media || emptyMedia());
      if (announce) showNotice("The page was scanned again.", "success", 3500);
    } else {
      showNotice(
        (response && response.error) || "The page could not be scanned.",
        "error",
        7000
      );
    }
  } finally {
    el.refreshMedia.disabled = false;
  }
}

async function openOfficialPage() {
  if (!IDMDetector.isHttpUrl(lastOfficialUrl)) {
    showNotice("There is no HTTP page to open.", "error", 6000);
    return;
  }
  const response = await send({ type: "idm:openPage", url: lastOfficialUrl });
  if (!response || !response.ok) {
    showNotice(friendlyError(response), "error", 7000);
  }
}

// ------------------------------------------------------------------ settings

async function saveFileTypes() {
  const raw = el.fileTypes.value;
  const tokens = raw
    .split(/[\s,;]+/)
    .map((value) => value.trim().replace(/^\.+/, "").toLowerCase())
    .filter(Boolean);
  const valid = tokens.filter((value) => /^[a-z0-9]{1,10}$/.test(value));
  if (!valid.length) {
    showNotice(
      "Enter at least one file extension, for example mp4, webm, mp3.",
      "error",
      7000
    );
    return;
  }
  const fileTypes = IDMDetector.normalizeExtensionList(valid).join(",");
  el.saveTypes.disabled = true;
  try {
    const response = await send({
      type: "idm:updateSettings",
      values: { fileTypes: fileTypes },
    });
    if (!response || !response.ok) {
      showNotice(
        (response && response.error) || "The file types could not be saved.",
        "error",
        7000
      );
      return;
    }
    applySettings(response.settings);
    typesDirty = false;
    el.fileTypes.value = settings.fileTypes;
    showNotice("Supported file types saved.", "success", 4000);
    await rescan(false);
  } finally {
    el.saveTypes.disabled = false;
  }
}

async function toggleSetting(key, value) {
  const previous = settings[key];
  settings[key] = value;
  renderSettings();
  const response = await send({
    type: "idm:updateSettings",
    values: { [key]: value },
  });
  if (!response || !response.ok) {
    settings[key] = previous;
    renderSettings();
    showNotice(
      (response && response.error) || "The preference could not be saved.",
      "error",
      7000
    );
    return;
  }
  applySettings(response.settings);
  renderSettings();
  if (key === "detectionEnabled") {
    if (settings.detectionEnabled) {
      await rescan(false);
    } else {
      renderMedia(emptyMedia());
    }
  }
}

// ------------------------------------------------------------------ native actions

async function testConnection() {
  const label = el.test.textContent;
  el.test.disabled = true;
  el.test.textContent = "Testing…";
  try {
    const response = await send({ type: "idm:testConnection" });
    if (response && response.ok) {
      const version =
        response.response &&
        response.response.status &&
        response.response.status.idm_version;
      showNotice(
        version ? "Connected to IDM " + version + "." : "Connected to IDM.",
        "success",
        4500
      );
      await refresh({ quiet: true });
    } else {
      showNotice(friendlyError(response), "error", 8000);
    }
  } finally {
    el.test.disabled = false;
    el.test.textContent = label;
  }
}

async function openNativeTarget(type, label) {
  const response = await send({ type: type });
  if (response && response.ok) {
    showNotice(label + " requested in IDM.", "success", 4000);
  } else {
    showNotice(friendlyError(response), "error", 7000);
  }
}

async function copyExtensionId() {
  const id = chrome.runtime.id;
  try {
    await navigator.clipboard.writeText(id);
    showNotice("Extension ID copied.", "success", 3500);
    return;
  } catch {
    // Fall back to a temporary text box for restricted clipboard contexts.
  }
  try {
    const area = document.createElement("textarea");
    area.value = id;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
    showNotice("Extension ID copied.", "success", 3500);
  } catch {
    showNotice("Extension ID: " + id, "warning", 0);
  }
}

async function openExtensionDetails() {
  const scheme = IDMNative.BROWSER === "edge" ? "edge" : "chrome";
  const url = scheme + "://extensions/?id=" + chrome.runtime.id;
  try {
    await chrome.tabs.create({ url: url, active: true });
  } catch {
    showNotice(
      "Open " + scheme + "://extensions in the address bar to review this extension's permissions.",
      "warning",
      0
    );
  }
}

// ------------------------------------------------------------------ transfers

function renderTransfers(downloads) {
  const active = downloads
    .filter((item) => ACTIVE_STATUSES.has(item.status))
    .slice(0, 4);
  el.transferList.replaceChildren();
  if (!active.length) {
    hide(el.transferList);
    el.transferEmpty.textContent = "No active transfers. Start one from a media link above.";
    show(el.transferEmpty);
    return;
  }
  hide(el.transferEmpty);
  for (const item of active) {
    el.transferList.appendChild(transferRow(item));
  }
  show(el.transferList);
}

function transferRow(item) {
  const row = document.createElement("li");
  row.className = "transfer";

  const head = document.createElement("div");
  head.className = "transfer-head";
  const name = document.createElement("span");
  name.className = "transfer-name";
  name.textContent = item.filename || "Download";
  name.title = item.filename || "";
  const state = document.createElement("span");
  state.className = "transfer-state";
  state.textContent = item.status || "";
  head.append(name, state);

  const bar = document.createElement("div");
  bar.className = "transfer-bar";
  const fill = document.createElement("span");
  const progress =
    typeof item.progress === "number" && Number.isFinite(item.progress)
      ? Math.max(0, Math.min(100, item.progress))
      : null;
  if (progress === null) {
    bar.classList.add("indeterminate");
  } else {
    fill.style.width = progress + "%";
  }
  bar.appendChild(fill);

  const meta = document.createElement("div");
  meta.className = "transfer-meta";
  const left = document.createElement("span");
  left.textContent = sizeText(item);
  const right = document.createElement("span");
  if (Number.isFinite(item.speed) && item.speed > 0) {
    right.textContent = formatBytes(item.speed) + "/s";
  } else if (progress !== null) {
    right.textContent = progress.toFixed(0) + "%";
  } else {
    right.textContent = "Starting…";
  }
  meta.append(left, right);

  row.append(head, bar, meta);
  return row;
}

function sizeText(item) {
  const total = Number.isFinite(item.total_bytes) ? item.total_bytes : 0;
  const done = Number.isFinite(item.downloaded_bytes) ? item.downloaded_bytes : 0;
  if (total > 0) return formatBytes(done) + " of " + formatBytes(total);
  return done > 0 ? formatBytes(done) : "Starting…";
}

async function renderLastResult() {
  const response = await send({ type: "idm:getLastResult" });
  const result = response && response.ok ? response.result : null;
  if (!result || !result.filename) {
    el.lastResult.textContent = "";
    return;
  }
  el.lastResult.textContent = result.duplicate
    ? "Already in IDM: " + result.filename
    : "Added: " + result.filename;
}

// ------------------------------------------------------------------ helpers

function friendlyError(response) {
  if (!response) return "IDM did not respond. Start IDM and try again.";
  const error =
    (response.response && response.response.error) ||
    response.error ||
    (response.status && response.status.idm_running === false
      ? { code: "idm_not_running" }
      : null);
  const code = error && error.code;
  if (code === "native_host_unavailable") {
    return "The IDM native host is not registered. Open IDM → Browser Integration and install the Chrome or Edge integration.";
  }
  if (code === "idm_not_running") {
    return "IDM is not running. Start IDM and try again.";
  }
  if (code === "unauthorized_extension") {
    return "This extension is not authorised in IDM. Reinstall the native host from IDM → Browser Integration.";
  }
  if (code === "restricted_platform" || code === "restricted_stream") {
    return (error && error.message) || "IDM does not download protected platform streams.";
  }
  if (code === "detection_disabled") {
    return "Media detection is turned off. Enable it above and rescan the page.";
  }
  if (code === NO_RESPONSE) {
    return "The IDM assistant did not respond. Close this popup and try again.";
  }
  if (error && error.message) return error.message;
  return "IDM did not answer the request.";
}

function showNotice(message, kind, autoHideMs, source) {
  if (!message) return;
  const origin = source || "action";
  if (
    origin === "connection" &&
    noticeSource &&
    noticeSource !== "connection" &&
    !el.notice.classList.contains("hidden")
  ) {
    return;
  }
  if (noticeTimer) {
    clearTimeout(noticeTimer);
    noticeTimer = null;
  }
  noticeSource = origin;
  el.notice.textContent = String(message);
  el.notice.className = "notice " + (kind || "");
  if (autoHideMs) {
    noticeTimer = setTimeout(hideNotice, autoHideMs);
  }
}

function hideNotice() {
  if (noticeTimer) {
    clearTimeout(noticeTimer);
    noticeTimer = null;
  }
  noticeSource = "";
  el.notice.className = "notice hidden";
  el.notice.textContent = "";
}

function show(element) {
  element.classList.remove("hidden");
}

function hide(element) {
  element.classList.add("hidden");
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  const digits = index === 0 ? 0 : value < 10 ? 1 : 0;
  return value.toFixed(digits) + " " + units[index];
}

function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return "";
  const total = Math.round(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = total % 60;
  if (hours) {
    return hours + ":" + String(minutes).padStart(2, "0") + ":" + String(rest).padStart(2, "0");
  }
  return minutes + ":" + String(rest).padStart(2, "0");
}
