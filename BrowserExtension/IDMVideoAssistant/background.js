/* IDM Video Assistant service worker.
 *
 * Responsibilities:
 *  - keep a per-tab cache of the direct media links reported by content.js
 *  - intercept ordinary browser downloads and hand them to IDM
 *  - send validated download requests to the registered native messaging host
 *  - never touch protected platform streams or arbitrary shell operations
 */
importScripts("media-detector.js", "native-messaging.js");

const Detector = self.IDMDetector;
const Native = self.IDMNative;

const MENU_DOWNLOAD = "idm-download-link";
const MENU_DOWNLOAD_TO = "idm-download-link-to";
const MENU_MEDIA = "idm-download-media";
const SUPPRESS_TTL_MS = 15000;
const CACHE_TTL_MS = 60000;

const DEFAULT_SETTINGS = {
  autoIntercept: true,
  askFolder: false,
  detectionEnabled: true,
  notifyOnAdd: true,
  fileTypes: Detector.DEFAULT_FILE_TYPES.join(","),
};

let settings = Object.assign({}, DEFAULT_SETTINGS);
let lastError = null;
let stateBuild = null;
const suppressed = new Map();
const handling = new Set();
const tabCache = new Map();

const ready = loadSettings();

function callSafely(action) {
  try {
    const result = action();
    if (result && typeof result.catch === "function") result.catch(() => undefined);
    return result;
  } catch {
    return undefined;
  }
}

function applySettings(stored) {
  const values = stored || {};
  settings.autoIntercept = values.autoIntercept !== false;
  settings.askFolder = values.askFolder === true;
  settings.detectionEnabled = values.detectionEnabled !== false;
  settings.notifyOnAdd = values.notifyOnAdd !== false;
  settings.fileTypes = Detector.fileTypesText(
    values.fileTypes || DEFAULT_SETTINGS.fileTypes
  );
}

function loadSettings() {
  return new Promise((resolve) => {
    try {
      chrome.storage.local.get(DEFAULT_SETTINGS, (stored) => {
        void chrome.runtime.lastError;
        applySettings(stored);
        resolve();
      });
    } catch {
      applySettings(DEFAULT_SETTINGS);
      resolve();
    }
  });
}

function syncFromStorage(changes) {
  if (!changes) return;
  const patch = {};
  let touched = false;
  for (const key of [
    "autoIntercept",
    "askFolder",
    "detectionEnabled",
    "notifyOnAdd",
    "fileTypes",
  ]) {
    if (changes[key]) {
      patch[key] = changes[key].newValue;
      touched = true;
    }
  }
  if (!touched) return;
  applySettings(
    Object.assign({}, settings, {
      fileTypes: changes.fileTypes ? changes.fileTypes.newValue : settings.fileTypes,
    })
  );
  if (changes.detectionEnabled && changes.detectionEnabled.newValue === false) {
    tabCache.clear();
  }
}

callSafely(() => chrome.storage.onChanged.addListener(syncFromStorage));

// ------------------------------------------------------------------ context menus

function createMenus() {
  callSafely(() =>
    chrome.contextMenus.removeAll(() => {
      void chrome.runtime.lastError;
      chrome.contextMenus.create(
        { id: MENU_DOWNLOAD, title: "Download with IDM", contexts: ["link"] },
        () => void chrome.runtime.lastError
      );
      chrome.contextMenus.create(
        {
          id: MENU_DOWNLOAD_TO,
          title: "Download with IDM to\u2026",
          contexts: ["link"],
        },
        () => void chrome.runtime.lastError
      );
      chrome.contextMenus.create(
        {
          id: MENU_MEDIA,
          title: "Send this media to IDM",
          contexts: ["video", "audio"],
        },
        () => void chrome.runtime.lastError
      );
    })
  );
}

ready.then(createMenus).catch(() => undefined);
callSafely(() => chrome.runtime.onInstalled.addListener(createMenus));
callSafely(() => chrome.runtime.onStartup.addListener(createMenus));

callSafely(() =>
  chrome.contextMenus.onClicked.addListener((info, tab) => {
    if (!info) return;
    if (info.menuItemId === MENU_DOWNLOAD) {
      void downloadLink(info, tab, false);
    } else if (info.menuItemId === MENU_DOWNLOAD_TO) {
      void downloadLink(info, tab, true);
    } else if (info.menuItemId === MENU_MEDIA) {
      void downloadLink(info, tab, false);
    }
  })
);

function httpOrEmpty(value) {
  return Native.isHttpUrl(value) ? value : "";
}

function filenameFromUrl(value) {
  return Native.safeFilename(Detector.filenameFromUrl(value));
}

async function downloadLink(info, tab, forceAsk) {
  await ready;
  const url = httpOrEmpty(info.linkUrl || info.srcUrl || "");
  if (!url) {
    rememberError({
      error: {
        code: "unsupported_url",
        message: "IDM can only download HTTP and HTTPS addresses.",
      },
    });
    setBadge("!", "#c0392b", 4000);
    return;
  }
  if (Detector.isRestrictedMediaHost(url)) {
    rememberError({
      error: {
        code: "restricted_stream",
        message:
          "This media address belongs to a restricted platform. IDM does not " +
          "extract protected streams; use the platform's official download options.",
      },
    });
    setBadge("!", "#c0392b", 4000);
    return;
  }
  const pageUrl = httpOrEmpty(info.pageUrl || (tab && tab.url) || "");
  const pageTitle = String((tab && tab.title) || "");
  const extension = Detector.extensionOf(url);
  const payload = Native.buildDownloadRequest(
    {
      url: url,
      filename: filenameFromUrl(url),
      mime: "",
      media_kind: Detector.mediaKindFor(extension, ""),
      quality_label: "",
      duration_seconds: null,
    },
    {
      pageUrl: pageUrl,
      pageTitle: pageTitle,
      askFolder: forceAsk === true || settings.askFolder,
    }
  );
  const response = await Native.sendNative(payload);
  if (response.ok && response.type === "download_accepted") {
    suppress(url);
    forgetError();
    const filename =
      (response.download && response.download.filename) ||
      filenameFromUrl(url) ||
      "download";
    await recordResult(filename, response.duplicate === true);
    setBadge("\u2713", "#1f9d55", 2500);
    if (settings.notifyOnAdd && tab && tab.id != null) {
      toastTab(
        tab.id,
        response.duplicate
          ? "\u201c" + filename + "\u201d is already downloading in IDM."
          : "Added \u201c" + filename + "\u201d to IDM."
      );
    }
    return;
  }
  if (Native.isCancelled(response)) return;
  rememberError(response);
  setBadge("!", "#c0392b", 4000);
}

// ------------------------------------------------------------------ browser downloads

callSafely(() =>
  chrome.downloads.onCreated.addListener((item) => {
    void maybeIntercept(item);
  })
);

callSafely(() =>
  chrome.downloads.onChanged.addListener((delta) => {
    if (delta && delta.state && delta.state.current === "complete") {
      clearSuppressionSoon();
    }
  })
);

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
    // The transfer may already be finished or cancelled.
  }
}

async function cancelBrowserDownload(id) {
  try {
    await chrome.downloads.cancel(id);
    await chrome.downloads.erase({ id });
  } catch {
    // A cancelled entry left in the browser list is harmless.
  }
}

async function maybeIntercept(item) {
  if (!item || typeof item.id !== "number") return;
  await ready;
  if (!settings.autoIntercept) return;
  if (item.state && item.state !== "in_progress") return;
  if (item.byExtensionId) return;
  if (!Native.isHttpUrl(item.url)) return;
  if (isSuppressed(item.url)) return;
  if (handling.has(item.id)) return;

  handling.add(item.id);
  try {
    const referrer = httpOrEmpty(item.referrer);
    if (Detector.isRestrictedMediaHost(item.url)) {
      return;
    }
    if (referrer && Detector.restrictedPlatformFor(referrer)) {
      // Leave the transfer to the browser: taking over a request started by a
      // restricted platform would mean circumventing that platform's rules.
      return;
    }

    await pauseDownload(item.id);
    let current = await findDownload(item.id);
    if (!current || current.state !== "in_progress") return;
    if (!current.paused) {
      await pauseDownload(item.id);
      current = await findDownload(item.id);
      if (!current || current.state !== "in_progress") return;
    }

    const url = current.url || item.url;
    const extension = Detector.extensionOf(url);
    const payload = Native.buildDownloadRequest(
      {
        url: url,
        filename: Native.safeFilename(current.filename) || filenameFromUrl(url),
        mime: typeof current.mime === "string" ? current.mime : "",
        media_kind: Detector.mediaKindFor(extension, current.mime),
        quality_label: "",
        duration_seconds: null,
      },
      {
        pageUrl: referrer,
        pageTitle: "",
        askFolder: settings.askFolder,
      }
    );
    const response = await Native.sendNative(payload);

    if (response.ok && response.type === "download_accepted") {
      suppress(url);
      await cancelBrowserDownload(item.id);
      forgetError();
      const filename =
        (response.download && response.download.filename) ||
        Native.safeFilename(current.filename) ||
        filenameFromUrl(url) ||
        "download";
      await recordResult(filename, response.duplicate === true);
      setBadge("\u2713", "#1f9d55", 2500);
      return;
    }

    if (Native.isCancelled(response)) {
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

// ------------------------------------------------------------------ tab media cache

function emptyMedia() {
  return {
    page: { url: "", title: "", domain: "" },
    items: [],
    restricted: null,
    updated_at: 0,
  };
}

function storeReport(tabId, frameId, message) {
  if (!Number.isInteger(tabId)) return;
  if (!message || message.enabled === false) {
    tabCache.delete(tabId);
    return;
  }
  const id = Number.isInteger(frameId) ? frameId : 0;
  const entry =
    tabCache.get(tabId) || {
      frames: new Map(),
      page: { url: "", title: "", domain: "" },
      items: [],
      restricted: null,
      updatedAt: 0,
    };
  entry.frames.set(id, {
    frameId: id,
    report: {
      page: message.page && typeof message.page === "object" ? message.page : {},
      items: Array.isArray(message.items) ? message.items : [],
      restricted:
        message.restricted && typeof message.restricted === "object"
          ? message.restricted
          : null,
    },
    at: Date.now(),
  });
  pruneFrames(entry);
  recomputeEntry(entry);
  tabCache.set(tabId, entry);
}

function pruneFrames(entry) {
  const cutoff = Date.now() - 10 * 60 * 1000;
  for (const [frameId, frame] of entry.frames) {
    if (frame.at < cutoff) entry.frames.delete(frameId);
  }
}

function recomputeEntry(entry) {
  const frames = Array.from(entry.frames.values()).sort(
    (left, right) => left.frameId - right.frameId
  );
  const top = entry.frames.get(0) || frames[0] || null;
  entry.page =
    (top && top.report && top.report.page) ||
    entry.page ||
    emptyMedia().page;
  entry.restricted =
    top && top.report && top.report.restricted ? top.report.restricted : null;

  const items = [];
  const seen = new Set();
  for (const frame of frames) {
    if (!frame.report || !Array.isArray(frame.report.items)) continue;
    for (const item of frame.report.items) {
      if (!item || typeof item.url !== "string" || seen.has(item.url)) continue;
      seen.add(item.url);
      items.push(item);
      if (items.length >= 60) break;
    }
    if (items.length >= 60) break;
  }
  entry.items = entry.restricted ? [] : items;
  entry.updatedAt = Date.now();
}

function publicMedia(entry) {
  if (!entry) return emptyMedia();
  return {
    page: entry.page || emptyMedia().page,
    items: Array.isArray(entry.items) ? entry.items : [],
    restricted: entry.restricted || null,
    updated_at: entry.updatedAt || 0,
  };
}

function scanTab(tabId) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      resolve(value);
    };
    const timer = setTimeout(() => finish(null), 2000);
    try {
      chrome.tabs.sendMessage(
        tabId,
        { type: "idm:scan" },
        { frameId: 0 },
        (response) => {
          clearTimeout(timer);
          void chrome.runtime.lastError;
          finish(response && typeof response === "object" ? response : null);
        }
      );
    } catch {
      clearTimeout(timer);
      finish(null);
    }
  });
}

async function getTabMedia(tabId, force) {
  if (!Number.isInteger(tabId) || tabId < 0) return emptyMedia();
  const cached = tabCache.get(tabId);
  if (!force && cached && Date.now() - cached.updatedAt < CACHE_TTL_MS) {
    return publicMedia(cached);
  }
  const response = await scanTab(tabId);
  if (response) {
    storeReport(tabId, 0, {
      page: response.page,
      items: response.items,
      restricted: response.restricted,
      enabled: settings.detectionEnabled,
    });
  }
  return publicMedia(tabCache.get(tabId));
}

callSafely(() =>
  chrome.tabs.onRemoved.addListener((tabId) => {
    tabCache.delete(tabId);
  })
);

callSafely(() =>
  chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
    if (changeInfo && changeInfo.status === "loading") {
      tabCache.delete(tabId);
    }
  })
);

// ------------------------------------------------------------------ native actions

function rememberError(response) {
  lastError = {
    code:
      (response && response.error && response.error.code) ||
      (response && response.status && response.status.idm_running === false
        ? "idm_not_running"
        : "idm_rejected"),
    message: Native.describeFailure(response),
    at: Date.now(),
  };
  callSafely(() => chrome.storage.local.set({ lastError }));
}

function forgetError() {
  lastError = null;
  callSafely(() => chrome.storage.local.remove("lastError"));
}

async function recordResult(filename, duplicate) {
  const result = {
    at: Date.now(),
    filename: String(filename || "download").slice(0, 200),
    duplicate: duplicate === true,
  };
  try {
    await chrome.storage.local.set({ lastResult: result });
  } catch {
    // The badge still confirms the transfer.
  }
}

function setBadge(text, color, clearAfterMs) {
  callSafely(() => chrome.action.setBadgeBackgroundColor({ color }));
  callSafely(() => chrome.action.setBadgeText({ text }));
  if (clearAfterMs) {
    setTimeout(() => {
      callSafely(() => chrome.action.setBadgeText({ text: "" }));
    }, clearAfterMs);
  }
}

function toastTab(tabId, text) {
  if (!Number.isInteger(tabId) || !text) return;
  try {
    chrome.tabs.sendMessage(
      tabId,
      { type: "idm:showToast", text: String(text).slice(0, 220) },
      () => void chrome.runtime.lastError
    );
  } catch {
    // Some tabs (PDF viewer, chrome://) cannot host the toast.
  }
}

async function collectState(tabId) {
  await ready;
  const statusResponse = await Native.sendNative({ type: "status" });
  const connected = Boolean(statusResponse.ok && statusResponse.connected);
  if (!connected && !lastError) rememberError(statusResponse);

  let downloads = Array.isArray(statusResponse.downloads)
    ? statusResponse.downloads
    : null;
  if (downloads === null) {
    const listResponse = await Native.sendNative({
      type: "list_downloads",
      limit: 5,
    });
    downloads = listResponse.ok && Array.isArray(listResponse.downloads)
      ? listResponse.downloads
      : [];
  }
  const media = Number.isInteger(tabId)
    ? await getTabMedia(tabId, false)
    : emptyMedia();

  return {
    ok: true,
    connected: connected,
    settings: Object.assign({}, settings),
    status: (statusResponse.ok && statusResponse.status) || {},
    downloads: downloads,
    hostVersion: statusResponse.native_host_version || "",
    protocol: statusResponse.native_protocol || statusResponse.protocol || null,
    browser: Native.BROWSER,
    extensionId: chrome.runtime.id,
    lastError: lastError,
    media: media,
  };
}

function buildState(tabId) {
  if (!stateBuild) {
    stateBuild = collectState(tabId).finally(() => {
      stateBuild = null;
    });
  }
  return stateBuild;
}

async function sendMedia(tabId, item, requestId, askFolder) {
  await ready;
  if (!settings.detectionEnabled) {
    return failure("detection_disabled", "Media detection is turned off.");
  }
  const media = await getTabMedia(tabId, false);
  if (media.restricted) {
    return failure(
      "restricted_platform",
      media.restricted.message || Detector.restrictionMessage(media.restricted.platform)
    );
  }
  const target = media.items.find(
    (candidate) => item && candidate.url === item.url
  );
  if (!target) {
    return failure(
      "media_not_found",
      "That media link is no longer available on the page. Refresh and try again."
    );
  }
  if (!Native.isHttpUrl(target.url) || Detector.isRestrictedMediaHost(target.url)) {
    return failure(
      "restricted_stream",
      "IDM does not download protected platform streams."
    );
  }

  let payload;
  try {
    payload = Native.buildDownloadRequest(target, {
      requestId: requestId,
      pageUrl: media.page.url,
      pageTitle: media.page.title,
      askFolder: askFolder === true || settings.askFolder,
    });
  } catch (error) {
    return failure("invalid_url", String(error && error.message ? error.message : error));
  }

  const response = await Native.sendNative(payload);
  if (response.ok && response.type === "download_accepted") {
    forgetError();
    const filename =
      (response.download && response.download.filename) ||
      target.filename ||
      filenameFromUrl(target.url) ||
      "download";
    await recordResult(filename, response.duplicate === true);
    setBadge("\u2713", "#1f9d55", 2500);
    if (settings.notifyOnAdd) {
      toastTab(
        tabId,
        response.duplicate
          ? "\u201c" + filename + "\u201d is already downloading in IDM."
          : "Added \u201c" + filename + "\u201d to IDM."
      );
    }
    return {
      ok: true,
      duplicate: response.duplicate === true,
      filename: filename,
      response: response,
    };
  }
  if (Native.isCancelled(response)) {
    return { ok: false, cancelled: true, error: { code: "cancelled", message: "Cancelled." } };
  }
  rememberError(response);
  setBadge("!", "#c0392b", 4000);
  return {
    ok: false,
    error:
      (response && response.error) || {
        code: "idm_rejected",
        message: Native.describeFailure(response),
      },
    response: response,
  };
}

function failure(code, message) {
  return { ok: false, error: { code: code, message: message } };
}

function collectPageLinks(tabId) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      resolve(value);
    };
    const timer = setTimeout(() => finish(null), 3000);
    try {
      chrome.tabs.sendMessage(
        tabId,
        { type: "idm:collectLinks" },
        { frameId: 0 },
        (response) => {
          clearTimeout(timer);
          void chrome.runtime.lastError;
          finish(response && typeof response === "object" ? response : null);
        }
      );
    } catch {
      clearTimeout(timer);
      finish(null);
    }
  });
}

/**
 * Offer every plain link on the page for a batch download.
 *
 * The page itself is never fetched again: the links are the ones already
 * visible in the document, and IDM still asks the user to confirm the list.
 */
async function capturePageLinks(tabId) {
  await ready;
  if (!Number.isInteger(tabId) || tabId < 0) {
    return failure("no_tab", "No page is available to capture.");
  }
  const report = await collectPageLinks(tabId);
  if (!report) {
    return failure(
      "page_unreachable",
      "This page cannot be read. Reload it and try again."
    );
  }
  if (report.restricted) {
    return failure(
      "restricted_platform",
      report.restricted.message ||
        Detector.restrictionMessage(report.restricted.platform)
    );
  }
  if (!Array.isArray(report.links) || !report.links.length) {
    return failure("no_links", "This page does not offer any downloadable links.");
  }

  let payload;
  try {
    payload = Native.buildCaptureRequest(report, {});
  } catch (error) {
    return failure(
      "invalid_links",
      String(error && error.message ? error.message : error)
    );
  }

  const response = await Native.sendNative(payload);
  if (response.ok && response.type === "page_captured") {
    forgetError();
    setBadge("\u2713", "#1f9d55", 2500);
    return {
      ok: true,
      requested: response.requested || payload.links.length,
      added: response.added || 0,
      skipped: response.skipped || 0,
      rejected: response.rejected || 0,
    };
  }
  if (Native.isCancelled(response)) {
    return { ok: false, cancelled: true, error: { code: "cancelled", message: "Cancelled." } };
  }
  rememberError(response);
  setBadge("!", "#c0392b", 4000);
  return {
    ok: false,
    error:
      (response && response.error) || {
        code: "idm_rejected",
        message: Native.describeFailure(response),
      },
  };
}

async function openPage(url) {
  if (!Native.isHttpUrl(url)) {
    return failure("invalid_url", "IDM can only open HTTP and HTTPS pages.");
  }
  try {
    await chrome.tabs.create({ url: url, active: true });
    return { ok: true };
  } catch (error) {
    return failure(
      "open_failed",
      String(error && error.message ? error.message : "The page could not be opened.")
    );
  }
}

async function updateSettings(values) {
  await ready;
  const clean = {};
  if (values && typeof values === "object") {
    if ("autoIntercept" in values) {
      clean.autoIntercept = values.autoIntercept === true;
    }
    if ("askFolder" in values) {
      clean.askFolder = values.askFolder === true;
    }
    if ("detectionEnabled" in values) {
      clean.detectionEnabled = values.detectionEnabled === true;
    }
    if ("notifyOnAdd" in values) {
      clean.notifyOnAdd = values.notifyOnAdd === true;
    }
    if ("fileTypes" in values) {
      clean.fileTypes = Detector.fileTypesText(values.fileTypes);
    }
  }
  if (Object.keys(clean).length) {
    try {
      await chrome.storage.local.set(clean);
    } catch {
      return failure("storage_failed", "The preference could not be saved.");
    }
    applySettings(Object.assign({}, settings, clean));
    if (clean.detectionEnabled === false) tabCache.clear();
  }
  return { ok: true, settings: Object.assign({}, settings) };
}

// ------------------------------------------------------------------ message router

callSafely(() =>
  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (!message || typeof message !== "object") return undefined;
    const type = message.type;
    const senderTab = sender && sender.tab;

    if (type === "idm:mediaFound") {
      if (senderTab && Number.isInteger(senderTab.id)) {
        storeReport(
          senderTab.id,
          sender && Number.isInteger(sender.frameId) ? sender.frameId : 0,
          message
        );
      }
      sendResponse({ ok: true });
      return undefined;
    }

    if (type === "idm:getState") {
      const tabId = Number.isInteger(message.tabId) ? message.tabId : null;
      buildState(tabId).then(
        sendResponse,
        () => sendResponse({ ok: false, error: "IDM state could not be read." })
      );
      return true;
    }

    if (type === "idm:getMedia") {
      const tabId = Number.isInteger(message.tabId) ? message.tabId : null;
      getTabMedia(tabId, message.force === true).then(
        (media) => sendResponse({ ok: true, media: media }),
        () => sendResponse({ ok: false, error: "The page could not be scanned." })
      );
      return true;
    }

    if (type === "idm:sendMedia") {
      const tabId = Number.isInteger(message.tabId) ? message.tabId : null;
      sendMedia(tabId, message.item, message.requestId, message.askFolder).then(
        sendResponse,
        (error) =>
          sendResponse(
            failure(
              "internal_error",
              String(error && error.message ? error.message : "IDM could not be reached.")
            )
          )
      );
      return true;
    }

    if (type === "idm:capturePage") {
      const tabId = Number.isInteger(message.tabId) ? message.tabId : null;
      capturePageLinks(tabId).then(
        sendResponse,
        () =>
          sendResponse(
            failure("internal_error", "The page links could not be captured.")
          )
      );
      return true;
    }

    if (type === "idm:updateSettings") {
      updateSettings(message.values).then(
        sendResponse,
        () => sendResponse(failure("storage_failed", "The preference could not be saved."))
      );
      return true;
    }

    if (type === "idm:openIdm" || type === "idm:openSettings") {
      const nativeType = type === "idm:openIdm" ? "open_idm" : "open_settings";
      Native.sendNative({ type: nativeType }).then((response) => {
        if (!response.ok) rememberError(response);
        sendResponse({ ok: response.ok, response: response });
      });
      return true;
    }

    if (type === "idm:testConnection") {
      Native.sendNative({ type: "status" }).then((response) => {
        const connected = Boolean(response.ok && response.connected);
        if (connected) forgetError();
        else rememberError(response);
        sendResponse({ ok: connected, response: response });
      });
      return true;
    }

    if (type === "idm:openPage") {
      openPage(message.url).then(sendResponse, () =>
        sendResponse(failure("open_failed", "The page could not be opened."))
      );
      return true;
    }

    if (type === "idm:clearError") {
      forgetError();
      sendResponse({ ok: true });
      return undefined;
    }

    if (type === "idm:getLastResult") {
      callSafely(() =>
        chrome.storage.local.get({ lastResult: null }, (stored) => {
          void chrome.runtime.lastError;
          sendResponse({ ok: true, result: stored.lastResult || null });
        })
      );
      return true;
    }

    if (type === "idm:toastShown") {
      sendResponse({ ok: true });
      return undefined;
    }

    return undefined;
  })
);
