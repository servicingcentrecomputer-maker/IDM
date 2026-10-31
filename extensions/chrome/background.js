"use strict";

const HOST_NAME = "com.idm.native";
const BROWSER = "chrome";
const MENU_ID = "idm-download-link";
const MENU_TITLE = "Download with IDM";
const MENU_TO_ID = "idm-download-link-to";
const MENU_TO_TITLE = "Download with IDM to\u2026";
const DEFAULT_AUTO_INTERCEPT = true;
const DEFAULT_ASK_FOLDER = true;
const SUPPRESS_TTL_MS = 15000;

let settings = {
  autoIntercept: DEFAULT_AUTO_INTERCEPT,
  askFolder: DEFAULT_ASK_FOLDER,
};
let lastError = null;
const suppressed = new Map();
const handling = new Set();

const ready = loadSettings().catch(() => undefined);

function loadSettings() {
  return chrome.storage.local
    .get({
      autoIntercept: DEFAULT_AUTO_INTERCEPT,
      askFolder: DEFAULT_ASK_FOLDER,
    })
    .then((stored) => {
      settings.autoIntercept = stored.autoIntercept !== false;
      settings.askFolder = stored.askFolder === true;
    })
    .catch(() => undefined);
}

function createMenus() {
  chrome.contextMenus.removeAll(() => {
    void chrome.runtime.lastError;
    chrome.contextMenus.create(
      { id: MENU_ID, title: MENU_TITLE, contexts: ["link"] },
      () => void chrome.runtime.lastError
    );
    chrome.contextMenus.create(
      { id: MENU_TO_ID, title: MENU_TO_TITLE, contexts: ["link"] },
      () => void chrome.runtime.lastError
    );
  });
}

function prepare() {
  ready.then(() => {
    createMenus();
  });
}

prepare();
chrome.runtime.onInstalled.addListener(prepare);
chrome.runtime.onStartup.addListener(prepare);

// The popup writes preferences straight to storage so a sleeping worker can
// never block the toggles; keep the in-memory copy in step with those writes.
chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "local" || !changes) return;
  if (changes.autoIntercept) {
    settings.autoIntercept = changes.autoIntercept.newValue !== false;
  }
  if (changes.askFolder) {
    settings.askFolder = changes.askFolder.newValue === true;
  }
});

// ------------------------------------------------------------------ native channel

function sendNative(message) {
  const payload = Object.assign(
    {
      request_id: createRequestId(),
      browser: BROWSER,
      extension_id: chrome.runtime.id,
      client_version: chrome.runtime.getManifest().version,
    },
    message
  );
  return new Promise((resolve) => {
    try {
      chrome.runtime.sendNativeMessage(HOST_NAME, payload, (response) => {
        const error = chrome.runtime.lastError;
        if (error) {
          resolve({
            ok: false,
            error: {
              code: "native_host_unavailable",
              message:
                error.message ||
                "The IDM native messaging host is not available.",
              retryable: true,
            },
          });
          return;
        }
        if (!response || typeof response !== "object") {
          resolve({
            ok: false,
            error: {
              code: "invalid_response",
              message: "The IDM native host returned an invalid response.",
              retryable: true,
            },
          });
          return;
        }
        resolve(response);
      });
    } catch (error) {
      resolve({
        ok: false,
        error: {
          code: "native_host_unavailable",
          message: String(error && error.message ? error.message : error),
          retryable: true,
        },
      });
    }
  });
}

function createRequestId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return BROWSER + "-" + crypto.randomUUID();
  }
  const random = Math.random().toString(36).slice(2);
  return BROWSER + "-" + Date.now().toString(36) + "-" + random;
}

function describeFailure(response) {
  if (response && response.error && response.error.message) {
    return response.error.message;
  }
  if (response && response.status && response.status.message) {
    return response.status.message;
  }
  return "IDM did not answer the request.";
}

function isCancelled(response) {
  return Boolean(
    response && response.error && response.error.code === "cancelled"
  );
}

function rememberError(response) {
  lastError = {
    code:
      (response && response.error && response.error.code) ||
      (response && response.status && response.status.idm_running === false
        ? "idm_not_running"
        : "idm_rejected"),
    message: describeFailure(response),
    at: Date.now(),
  };
  chrome.storage.local.set({ lastError }).catch(() => undefined);
}

function forgetError() {
  lastError = null;
  chrome.storage.local.remove("lastError").catch(() => undefined);
}

// ------------------------------------------------------------------ downloads

chrome.downloads.onCreated.addListener((item) => {
  void maybeIntercept(item);
});

chrome.downloads.onChanged.addListener((delta) => {
  if (delta && delta.state && delta.state.current === "complete") {
    clearSuppressionSoon();
  }
});

function isHttpUrl(value) {
  return typeof value === "string" && /^https?:\/\//i.test(value);
}

function isSuppressed(url) {
  const until = suppressed.get(url);
  if (!until) return false;
  if (Date.now() > until) {
    suppressed.delete(url);
    return false;
  }
  return true;
}

function suppress(url) {
  if (!url) return;
  suppressed.set(url, Date.now() + SUPPRESS_TTL_MS);
}

function clearSuppressionSoon() {
  const now = Date.now();
  for (const [url, until] of suppressed) {
    if (now > until) suppressed.delete(url);
  }
}

function safeFilename(path) {
  if (typeof path !== "string" || !path) return "";
  const name = path.split(/[\\/]/).pop() || "";
  if (!name || name === "." || name === ".." || name.length > 200) return "";
  if (/[\\/:*?"<>|\u0000-\u001f]/.test(name)) return "";
  if (/[. ]$/.test(name)) return "";
  return name;
}

function httpOrEmpty(value) {
  return isHttpUrl(value) ? value : "";
}

function positiveInteger(value) {
  return Number.isSafeInteger(value) && value > 0 ? value : null;
}

async function findDownload(id) {
  try {
    const results = await chrome.downloads.search({ id });
    return Array.isArray(results) && results.length ? results[0] : null;
  } catch {
    return null;
  }
}

async function pauseDownload(id) {
  try {
    await chrome.downloads.pause(id);
    return true;
  } catch {
    return false;
  }
}

async function resumeDownload(id) {
  try {
    await chrome.downloads.resume(id);
  } catch {
    // The download may have completed or been cancelled already.
  }
}

async function cancelBrowserDownload(id) {
  try {
    await chrome.downloads.cancel(id);
    await chrome.downloads.erase({ id });
  } catch {
    // IDM already owns the transfer; a lingering cancelled entry is harmless.
  }
}

async function maybeIntercept(item) {
  if (!item || typeof item.id !== "number") return;
  await ready;
  if (!settings.autoIntercept) return;
  if (item.state && item.state !== "in_progress") return;
  if (item.byExtensionId) return;
  if (!isHttpUrl(item.url)) return;
  if (isSuppressed(item.url)) return;
  if (handling.has(item.id)) return;

  handling.add(item.id);
  try {
    await pauseDownload(item.id);
    let current = await findDownload(item.id);
    if (!current || current.state !== "in_progress") {
      return;
    }
    if (!current.paused) {
      await pauseDownload(item.id);
      current = await findDownload(item.id);
      if (!current || current.state !== "in_progress") return;
    }

    const response = await sendNative({
      type: "request_download",
      url: current.url || item.url,
      filename: safeFilename(current.filename),
      referrer: httpOrEmpty(current.referrer),
      mime: typeof current.mime === "string" ? current.mime : "",
      total_bytes: positiveInteger(current.totalBytes),
      ask_folder: settings.askFolder,
    });

    if (response.ok && response.type === "download_accepted") {
      suppress(current.url || item.url);
      await cancelBrowserDownload(item.id);
      forgetError();
      setBadge("\u2713", "#1f9d55", 2500);
      chrome.storage.local
        .set({
          lastResult: {
            at: Date.now(),
            filename:
              (response.download && response.download.filename) ||
              safeFilename(current.filename),
            duplicate: response.duplicate === true,
          },
        })
        .catch(() => undefined);
      return;
    }

    if (isCancelled(response)) {
      await resumeDownload(item.id);
      return;
    }

    await resumeDownload(item.id);
    rememberError(response);
    setBadge("!", "#c0392b", 4000);
  } catch {
    await resumeDownload(item.id);
  } finally {
    handling.delete(item.id);
  }
}

// ------------------------------------------------------------------ context menu

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (!info) return;
  if (info.menuItemId === MENU_ID) {
    void downloadLink(info, tab, false);
  } else if (info.menuItemId === MENU_TO_ID) {
    void downloadLink(info, tab, true);
  }
});

async function downloadLink(info, tab, forceAsk) {
  await ready;
  const url = info.linkUrl || info.srcUrl || "";
  if (!isHttpUrl(url)) {
    rememberError({
      error: {
        code: "unsupported_url",
        message: "IDM can only download HTTP and HTTPS addresses.",
      },
    });
    setBadge("!", "#c0392b", 4000);
    return;
  }
  const referrer = httpOrEmpty(info.pageUrl || (tab && tab.url) || "");
  const response = await sendNative({
    type: "request_download",
    url,
    filename: filenameFromUrl(url),
    referrer,
    ask_folder: forceAsk === true || settings.askFolder,
  });
  if (response.ok && response.type === "download_accepted") {
    suppress(url);
    forgetError();
    setBadge("\u2713", "#1f9d55", 2500);
    chrome.storage.local
      .set({
        lastResult: {
          at: Date.now(),
          filename:
            (response.download && response.download.filename) ||
            filenameFromUrl(url),
          duplicate: response.duplicate === true,
        },
      })
      .catch(() => undefined);
    return;
  }
  if (isCancelled(response)) return;
  rememberError(response);
  setBadge("!", "#c0392b", 4000);
}

function filenameFromUrl(value) {
  try {
    const name = new URL(value).pathname.split("/").filter(Boolean).pop();
    return safeFilename(name ? decodeURIComponent(name) : "");
  } catch {
    return "";
  }
}

function setBadge(text, color, clearAfterMs) {
  try {
    chrome.action.setBadgeBackgroundColor({ color });
    chrome.action.setBadgeText({ text });
    if (clearAfterMs) {
      setTimeout(() => {
        chrome.action.setBadgeText({ text: "" }).catch(() => undefined);
      }, clearAfterMs);
    }
  } catch {
    // Badge support is cosmetic.
  }
}

// ------------------------------------------------------------------ popup messages

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || typeof message !== "object") return undefined;
  if (message.type === "idm:getState") {
    buildState().then(sendResponse, () =>
      sendResponse({ ok: false, error: "IDM state could not be read." })
    );
    return true;
  }
  if (message.type === "idm:setIntercept") {
    const enabled = message.enabled === true;
    awaitReadySave(enabled).then(sendResponse, () =>
      sendResponse({ ok: false, error: "The preference could not be saved." })
    );
    return true;
  }
  if (message.type === "idm:setAskFolder") {
    const enabled = message.enabled === true;
    awaitReadySaveAskFolder(enabled).then(sendResponse, () =>
      sendResponse({ ok: false, error: "The preference could not be saved." })
    );
    return true;
  }
  if (message.type === "idm:openIdm" || message.type === "idm:openSettings") {
    const type = message.type === "idm:openIdm" ? "open_idm" : "open_settings";
    sendNative({ type }).then((response) => {
      if (!response.ok) rememberError(response);
      sendResponse({ ok: response.ok, response });
    });
    return true;
  }
  if (message.type === "idm:testConnection") {
    sendNative({ type: "status" }).then((response) => {
      const connected = Boolean(response.ok && response.connected);
      if (connected) forgetError();
      else rememberError(response);
      sendResponse({ ok: connected, response });
    });
    return true;
  }
  if (message.type === "idm:clearError") {
    forgetError();
    sendResponse({ ok: true });
    return undefined;
  }
  return undefined;
});

async function awaitReadySave(enabled) {
  await ready;
  settings.autoIntercept = enabled;
  await chrome.storage.local.set({ autoIntercept: enabled });
  return { ok: true, autoIntercept: enabled };
}

async function awaitReadySaveAskFolder(enabled) {
  await ready;
  settings.askFolder = enabled;
  await chrome.storage.local.set({ askFolder: enabled });
  return { ok: true, askFolder: enabled };
}

let stateBuild = null;

function buildState() {
  if (!stateBuild) {
    stateBuild = collectState().finally(() => {
      stateBuild = null;
    });
  }
  return stateBuild;
}

async function collectState() {
  await ready;
  const statusResponse = await sendNative({ type: "status" });
  const connected = Boolean(statusResponse.ok && statusResponse.connected);
  if (!connected && !lastError) {
    rememberError(statusResponse);
  }
  let downloads = Array.isArray(statusResponse.downloads)
    ? statusResponse.downloads
    : null;
  if (downloads === null) {
    // Older desktop builds do not embed the transfer list in status.
    const listResponse = await sendNative({ type: "list_downloads", limit: 5 });
    downloads = listResponse.ok ? listResponse.downloads || [] : [];
  }
  return {
    ok: true,
    connected,
    autoIntercept: settings.autoIntercept,
    askFolder: settings.askFolder,
    status: (statusResponse.ok && statusResponse.status) || {},
    downloads,
    hostVersion: statusResponse.native_host_version || "",
    lastError,
  };
}
