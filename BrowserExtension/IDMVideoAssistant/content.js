/* Page-side detection and in-page notifications.
 *
 * The content script only inspects the current document after the user
 * installs the extension. It never reads browsing history, never fetches media
 * URLs, and does nothing on restricted platform pages beyond reporting the
 * platform restriction to the popup.
 */
(function () {
  "use strict";

  if (typeof chrome === "undefined" || !chrome.runtime || !chrome.runtime.id) {
    return;
  }

  const detector = globalThis.IDMDetector;
  if (!detector) return;

  const DEFAULT_SETTINGS = {
    detectionEnabled: true,
    fileTypes: detector.DEFAULT_FILE_TYPES.join(","),
  };

  let settings = Object.assign({}, DEFAULT_SETTINGS);
  let lastSignature = "";
  let scanTimer = null;
  let toastTimer = null;
  let toastHost = null;

  function loadSettings(callback) {
    try {
      chrome.storage.local.get(DEFAULT_SETTINGS, (stored) => {
        void chrome.runtime.lastError;
        settings.detectionEnabled = stored.detectionEnabled !== false;
        settings.fileTypes = detector.fileTypesText(
          stored.fileTypes || DEFAULT_SETTINGS.fileTypes
        );
        if (callback) callback();
      });
    } catch {
      if (callback) callback();
    }
  }

  function currentReport() {
    return detector.collectMedia(document, {
      pageUrl: location.href,
      pageTitle: document.title || location.hostname,
      fileTypes: settings.fileTypes,
    });
  }

  function sendReport(report) {
    try {
      chrome.runtime.sendMessage(
        {
          type: "idm:mediaFound",
          enabled: settings.detectionEnabled,
          page: report.page,
          items: report.items,
          restricted: report.restricted,
        },
        () => void chrome.runtime.lastError
      );
    } catch {
      // The worker may be restarting; the next scan reports again.
    }
  }

  function scan(force) {
    if (!settings.detectionEnabled) {
      lastSignature = "";
      sendReport({
        page: {
          url: location.href,
          title: document.title || "",
          domain: detector.domainOf(location.href),
        },
        items: [],
        restricted: null,
      });
      return null;
    }
    const report = currentReport();
    const signature = JSON.stringify({
      url: report.page.url,
      restricted: report.restricted ? report.restricted.platform : "",
      items: report.items.map((item) => [
        item.url,
        item.quality_label,
        item.duration_seconds,
        item.size_bytes,
      ]),
    });
    if (!force && signature === lastSignature) return report;
    lastSignature = signature;
    sendReport(report);
    return report;
  }

  function scheduleScan(delay) {
    if (!settings.detectionEnabled) return;
    if (scanTimer) clearTimeout(scanTimer);
    scanTimer = setTimeout(() => {
      scanTimer = null;
      scan(false);
    }, typeof delay === "number" ? delay : 900);
  }

  function startObserver() {
    if (typeof MutationObserver !== "function" || !document.documentElement) {
      return;
    }
    const observer = new MutationObserver((records) => {
      if (!settings.detectionEnabled) return;
      let relevant = false;
      for (const record of records) {
        if (record.type === "childList" && record.addedNodes.length) {
          relevant = true;
          break;
        }
        if (record.type === "attributes") {
          relevant = true;
          break;
        }
      }
      if (relevant) scheduleScan(1200);
    });
    observer.observe(document.documentElement, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["href", "src", "type", "download"],
    });
  }

  function showToast(text) {
    if (!text) return;
    if (toastHost && toastHost.parentNode) {
      toastHost.parentNode.removeChild(toastHost);
    }
    const host = document.createElement("div");
    host.style.position = "fixed";
    host.style.right = "18px";
    host.style.bottom = "18px";
    host.style.zIndex = "2147483647";
    host.style.pointerEvents = "auto";
    const shadow = host.attachShadow({ mode: "open" });
    const box = document.createElement("div");
    box.style.cssText =
      "display:flex;align-items:center;gap:10px;max-width:360px;" +
      "padding:10px 12px;border-radius:10px;border:1px solid #2f4b6e;" +
      "background:#0f1d2e;color:#e7eef7;font:13px/1.4 'Segoe UI',Arial,sans-serif;" +
      "box-shadow:0 10px 30px rgba(0,0,0,.45);";
    const icon = document.createElement("span");
    icon.textContent = "IDM";
    icon.style.cssText =
      "background:#2f81f7;color:#fff;font-weight:700;font-size:11px;" +
      "padding:3px 6px;border-radius:5px;letter-spacing:.4px;";
    const label = document.createElement("span");
    label.textContent = String(text).slice(0, 220);
    label.style.flex = "1";
    const close = document.createElement("button");
    close.type = "button";
    close.textContent = "\u00d7";
    close.setAttribute("aria-label", "Dismiss");
    close.style.cssText =
      "background:transparent;border:0;color:#9db4cc;font-size:16px;" +
      "cursor:pointer;padding:0 2px;line-height:1;";
    close.addEventListener("click", () => {
      if (toastHost && toastHost.parentNode) {
        toastHost.parentNode.removeChild(toastHost);
      }
      toastHost = null;
    });
    box.append(icon, label, close);
    shadow.appendChild(box);
    (document.body || document.documentElement).appendChild(host);
    toastHost = host;
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      if (toastHost && toastHost.parentNode) {
        toastHost.parentNode.removeChild(toastHost);
      }
      toastHost = null;
    }, 6000);
    void chrome.runtime.sendMessage({ type: "idm:toastShown" }, () => {
      void chrome.runtime.lastError;
    });
  }

  try {
    chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
      if (!message || typeof message !== "object") return undefined;
      if (message.type === "idm:scan") {
        const report = scan(true);
        sendResponse(
          report || {
            page: { url: location.href, title: document.title || "", domain: "" },
            items: [],
            restricted: null,
          }
        );
        return undefined;
      }
      if (message.type === "idm:collectLinks") {
        const captured = detector.collectLinks(document, {
          pageUrl: location.href,
          pageTitle: document.title || location.hostname,
        });
        sendResponse(captured);
        return undefined;
      }
      if (message.type === "idm:showToast") {
        showToast(message.text);
        sendResponse({ ok: true });
        return undefined;
      }
      if (message.type === "idm:settingsChanged") {
        loadSettings(() => {
          if (settings.detectionEnabled) scan(true);
        });
        sendResponse({ ok: true });
        return undefined;
      }
      return undefined;
    });
  } catch {
    // A restricted page can tear down the extension context mid-load.
  }

  try {
    chrome.storage.onChanged.addListener((changes, area) => {
      if (area !== "local" || !changes) return;
      if (changes.detectionEnabled) {
        settings.detectionEnabled = changes.detectionEnabled.newValue !== false;
      }
      if (changes.fileTypes) {
        settings.fileTypes = detector.fileTypesText(changes.fileTypes.newValue);
      }
      lastSignature = "";
      if (settings.detectionEnabled) scan(true);
      else scan(false);
    });
  } catch {
    // Storage is unavailable in a detached frame.
  }

  for (const eventName of ["loadedmetadata", "durationchange", "emptied"]) {
    document.addEventListener(
      eventName,
      (event) => {
        const tag = event && event.target && event.target.tagName;
        if (tag === "VIDEO" || tag === "AUDIO") scheduleScan(400);
      },
      true
    );
  }

  window.addEventListener("pageshow", () => scheduleScan(300));
  window.addEventListener("hashchange", () => scheduleScan(300));

  loadSettings(() => {
    scan(false);
    startObserver();
  });
})();
