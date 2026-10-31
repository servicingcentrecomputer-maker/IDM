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
const PREFERENCE_ERROR = "The preference could not be saved.";

const el = {
  connection: document.getElementById("connection"),
  notice: document.getElementById("notice"),
  intercept: document.getElementById("intercept"),
  askFolder: document.getElementById("ask-folder"),
  active: document.getElementById("stat-active"),
  queued: document.getElementById("stat-queued"),
  total: document.getElementById("stat-total"),
  folder: document.getElementById("folder"),
  transferCard: document.getElementById("transfer-card"),
  transfers: document.getElementById("transfers"),
  idmVersion: document.getElementById("idm-version"),
  hostVersion: document.getElementById("host-version"),
  lastResult: document.getElementById("last-result"),
  hint: document.getElementById("hint"),
  openIdm: document.getElementById("open-idm"),
  openSettings: document.getElementById("open-settings"),
  test: document.getElementById("test-connection"),
};

let pollTimer = null;
let loading = false;
let noticeTimer = null;
let noticeSource = "";
const preferences = { autoIntercept: true, askFolder: true };
let savingPreferences = 0;

document.addEventListener("DOMContentLoaded", () => {
  bindActions();
  void refresh();
  pollTimer = setInterval(() => void refresh({ quiet: true }), 3000);
  window.addEventListener("unload", () => {
    if (pollTimer) clearInterval(pollTimer);
  });
});

function bindActions() {
  el.intercept.addEventListener("change", async () => {
    const enabled = el.intercept.checked;
    if (!(await savePreference({ autoIntercept: enabled }))) {
      el.intercept.checked = !enabled;
      showNotice(PREFERENCE_ERROR, "error", 6000);
      return;
    }
    preferences.autoIntercept = enabled;
    el.hint.textContent = enabled
      ? "Browser downloads will be sent to IDM automatically."
      : "Automatic interception is off. Use the right-click menu to send links to IDM.";
  });

  el.askFolder.addEventListener("change", async () => {
    const enabled = el.askFolder.checked;
    if (!(await savePreference({ askFolder: enabled }))) {
      el.askFolder.checked = !enabled;
      showNotice(PREFERENCE_ERROR, "error", 6000);
      return;
    }
    preferences.askFolder = enabled;
  });

  el.openIdm.addEventListener("click", async () => {
    await withButton(el.openIdm, "Opening…", async () => {
      const response = await send({ type: "idm:openIdm" });
      if (response && response.ok) {
        el.hint.textContent = "IDM was asked to show its window.";
      } else {
        showNotice(failureText(response), "error");
      }
    });
  });

  el.openSettings.addEventListener("click", async () => {
    await withButton(el.openSettings, "Opening…", async () => {
      const response = await send({ type: "idm:openSettings" });
      if (response && response.ok) {
        el.hint.textContent = "Download Settings were opened in IDM.";
      } else {
        showNotice(failureText(response), "error");
      }
    });
  });

  el.test.addEventListener("click", async () => {
    await withButton(el.test, "Testing…", async () => {
      const response = await send({ type: "idm:testConnection" });
      if (response && response.ok) {
        const version =
          (response.response &&
            response.response.status &&
            response.response.status.idm_version) ||
          "";
        showNotice(
          version ? `Connected to IDM ${version}.` : "Connected to IDM.",
          "success",
          4500
        );
      } else {
        showNotice(failureText(response), "error", 6000);
      }
      await refresh({ quiet: true });
    });
  });
}

async function withButton(button, busyLabel, action) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = busyLabel;
  try {
    await action();
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

function hasBrowserApi() {
  return typeof browser !== "undefined" && browser && browser.runtime;
}

async function send(message) {
  let response = null;
  for (let attempt = 0; attempt < SEND_ATTEMPTS; attempt += 1) {
    if (attempt > 0) await delay(200 * attempt);
    if (!extensionAvailable()) {
      return noResponse(
        "The IDM extension was updated in the background. Close this popup and open it again."
      );
    }
    response = await sendOnce(message);
    if (!response || !response.error || response.error.code !== NO_RESPONSE) {
      return response;
    }
  }
  return response;
}

function sendOnce(message) {
  if (hasBrowserApi()) {
    try {
      return browser.runtime
        .sendMessage(message)
        .then((response) => response || noResponse())
        .catch(() => noResponse());
    } catch {
      return Promise.resolve(noResponse());
    }
  }
  return new Promise((resolve) => {
    try {
      chrome.runtime.sendMessage(message, (response) => {
        if (chrome.runtime.lastError) {
          resolve(noResponse());
          return;
        }
        resolve(response || noResponse());
      });
    } catch {
      resolve(noResponse());
    }
  });
}

function extensionAvailable() {
  try {
    const runtime = hasBrowserApi() ? browser.runtime : chrome.runtime;
    return Boolean(runtime && runtime.id);
  } catch {
    return false;
  }
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
        typeof message === "string"
          ? message
          : "The IDM extension did not respond. Try again.",
    },
  };
}

function writeStorage(values) {
  if (hasBrowserApi()) return browser.storage.local.set(values);
  return new Promise((resolve, reject) => {
    chrome.storage.local.set(values, () => {
      const error = chrome.runtime.lastError;
      if (error) reject(new Error(error.message));
      else resolve();
    });
  });
}

// Preferences are written straight to extension storage so a slow or sleeping
// background worker can never block the toggles; the worker picks the change up
// through storage.onChanged.
async function savePreference(values) {
  savingPreferences += 1;
  try {
    await writeStorage(values);
    return true;
  } catch {
    return false;
  } finally {
    savingPreferences -= 1;
  }
}

function readStorage(defaults) {
  if (hasBrowserApi()) {
    return browser.storage.local.get(defaults);
  }
  return new Promise((resolve) => {
    chrome.storage.local.get(defaults, (values) => {
      void chrome.runtime.lastError;
      resolve(values || defaults);
    });
  });
}

async function refresh(options) {
  const quiet = Boolean(options && options.quiet);
  if (loading) return;
  loading = true;
  if (!quiet) {
    el.connection.textContent = "Checking";
    el.connection.className = "status status-checking";
  }
  try {
    if (!savingPreferences) {
      await readPreferences();
      renderPreferences();
    }
    const state = await send({ type: "idm:getState" });
    if (state && state.ok) {
      render(state);
    } else {
      setDisconnected("IDM state could not be read.");
    }
  } finally {
    loading = false;
  }
}

async function readPreferences() {
  try {
    const stored = await readStorage({ autoIntercept: true, askFolder: true });
    preferences.autoIntercept = stored.autoIntercept !== false;
    preferences.askFolder = stored.askFolder === true;
  } catch {
    // Keep the last known values when storage cannot be read.
  }
}

function renderPreferences() {
  el.intercept.checked = preferences.autoIntercept;
  el.askFolder.checked = preferences.askFolder;
}

function render(state) {
  const status = state.status || {};
  const connected = Boolean(state.connected);

  if (connected) {
    el.connection.textContent = "Connected";
    el.connection.className = "status status-connected";
    el.active.textContent = numberOr(status.active_count, "0");
    el.queued.textContent = numberOr(status.queued_count, "0");
    el.total.textContent = numberOr(status.download_count, "0");
    el.folder.textContent = status.default_folder || "Default folder";
    el.folder.title = status.default_folder || "";
    el.idmVersion.textContent = status.idm_version
      ? `IDM ${status.idm_version}`
      : "";
    el.hint.textContent = preferences.autoIntercept
      ? "Browser downloads are added to IDM automatically."
      : "Automatic interception is off. Use the right-click menu to send links to IDM.";

    const recentError =
      state.lastError &&
      typeof state.lastError.at === "number" &&
      Date.now() - state.lastError.at < 60000;
    if (recentError) {
      showNotice(state.lastError.message, "error", 0, "connection");
    } else if (noticeSource === "connection") {
      hideNotice();
    }
    renderTransfers(state.downloads || []);
  } else {
    el.active.textContent = "–";
    el.queued.textContent = "–";
    el.total.textContent = "–";
    el.folder.textContent = "—";
    el.folder.title = "";
    el.idmVersion.textContent = "";
    el.transferCard.classList.add("hidden");
    setDisconnected(
      (state.lastError && state.lastError.message) ||
        (status && status.message) ||
        "IDM is not reachable."
    );
  }

  el.hostVersion.textContent = state.hostVersion || "—";
  void renderLastResult();
}

function setDisconnected(message) {
  el.connection.textContent = "Disconnected";
  el.connection.className = "status status-error";
  showNotice(message, "error", 0, "connection");
  el.hint.textContent =
    "While IDM is unavailable, browser downloads continue normally.";
}

function renderTransfers(downloads) {
  const active = downloads
    .filter((item) => ACTIVE_STATUSES.has(item.status))
    .slice(0, 4);
  el.transfers.replaceChildren();
  if (!active.length) {
    el.transferCard.classList.add("hidden");
    return;
  }
  el.transferCard.classList.remove("hidden");
  for (const item of active) {
    el.transfers.appendChild(transferRow(item));
  }
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
    fill.style.width = `${progress}%`;
  }
  bar.appendChild(fill);

  const meta = document.createElement("div");
  meta.className = "transfer-meta";
  const left = document.createElement("span");
  left.textContent = sizeText(item);
  const right = document.createElement("span");
  if (Number.isFinite(item.speed) && item.speed > 0) {
    right.textContent = `${formatBytes(item.speed)}/s`;
  } else if (item.browser_display) {
    right.textContent = `From ${item.browser_display}`;
  } else if (progress !== null) {
    right.textContent = `${progress.toFixed(0)}%`;
  }
  meta.append(left, right);

  row.append(head, bar, meta);
  return row;
}

function sizeText(item) {
  const total = Number.isFinite(item.total_bytes) ? item.total_bytes : 0;
  const done = Number.isFinite(item.downloaded_bytes) ? item.downloaded_bytes : 0;
  if (total > 0) {
    return `${formatBytes(done)} of ${formatBytes(total)}`;
  }
  return done > 0 ? formatBytes(done) : "Starting…";
}

async function renderLastResult() {
  try {
    const stored = await readStorage({ lastResult: null });
    const result = stored.lastResult;
    if (!result || !result.filename) {
      el.lastResult.textContent = "";
      return;
    }
    el.lastResult.textContent = result.duplicate
      ? `Already in IDM: ${result.filename}`
      : `Added: ${result.filename}`;
  } catch {
    el.lastResult.textContent = "";
  }
}

function failureText(response) {
  if (!response) return "IDM did not respond. Start IDM and try again.";
  const error =
    (response.response && response.response.error) || response.error || null;
  const code = error && error.code;
  if (code === "native_host_unavailable") {
    return "The IDM native host is not registered. Re-run the IDM installer to enable browser integration.";
  }
  if (code === "idm_not_running") {
    return "IDM is not running. Start IDM and try again.";
  }
  if (code === "unauthorized_extension") {
    return "This extension is not authorized in IDM. Re-register the native host from IDM Options.";
  }
  if (code === NO_RESPONSE) {
    return (
      (error && error.message) ||
      "The IDM extension did not respond. Try again."
    );
  }
  if (error && error.message) return error.message;
  return "IDM did not answer the request.";
}

function showNotice(message, kind, autoHideMs, source) {
  if (!message) return;
  if (noticeTimer) {
    clearTimeout(noticeTimer);
    noticeTimer = null;
  }
  noticeSource = source || "action";
  el.notice.textContent = message;
  el.notice.className = `notice ${kind || ""}`.trim();
  el.notice.dataset.pinned = autoHideMs ? "0" : "1";
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
  el.notice.dataset.pinned = "0";
}

function numberOr(value, fallback) {
  return Number.isFinite(value) ? String(value) : fallback;
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
  return `${value.toFixed(digits)} ${units[index]}`;
}
