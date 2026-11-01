/* Native messaging client for the IDM desktop application.
 *
 * The extension never launches a process itself. Chrome or Edge starts the
 * registered com.idm.native host, which validates every field again before
 * forwarding a download request to the local IDM window.
 */
(function (global) {
  "use strict";

  const HOST_NAME = "com.idm.native";
  const PROTOCOL_VERSION = 2;
  const MAX_FILENAME = 200;

  function browserName() {
    try {
      const agent = String(global.navigator && global.navigator.userAgent);
      if (/\bEdg\//.test(agent)) return "edge";
    } catch {
      // Fall through to Chrome, which shares the same extension format.
    }
    return "chrome";
  }

  const BROWSER = browserName();

  function isHttpUrl(value) {
    if (typeof value !== "string" || value.length > 8192) return false;
    try {
      const url = new URL(value);
      return url.protocol === "http:" || url.protocol === "https:";
    } catch {
      return false;
    }
  }

  function safeFilename(value) {
    const text = String(value || "").trim();
    if (!text || text === "." || text === ".." || text.length > MAX_FILENAME) {
      return "";
    }
    if (/[\\/:*?"<>|\u0000-\u001f]/.test(text)) return "";
    if (/[. ]$/.test(text)) return "";
    return text;
  }

  function positiveInteger(value) {
    return Number.isSafeInteger(value) && value > 0 ? value : null;
  }

  function shortText(value, limit) {
    const text = String(value || "")
      .replace(/[\u0000-\u001f\u007f]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    return text.slice(0, limit);
  }

  function clientVersion() {
    try {
      return chrome.runtime.getManifest().version;
    } catch {
      return "3.0.0";
    }
  }

  function createRequestId() {
    try {
      if (
        typeof crypto !== "undefined" &&
        typeof crypto.randomUUID === "function"
      ) {
        return BROWSER + "-" + crypto.randomUUID();
      }
    } catch {
      // Use the time-based fallback below.
    }
    const random = Math.random().toString(36).slice(2, 12);
    return BROWSER + "-" + Date.now().toString(36) + "-" + random;
  }

  function mediaKindFor(item) {
    const metadata = item || {};
    const kind = String(metadata.media_kind || "").toLowerCase();
    if (kind === "video" || kind === "audio") return kind;
    const detector = global.IDMDetector;
    if (detector && typeof detector.mediaKindFor === "function") {
      const extension =
        metadata.extension ||
        (typeof detector.extensionOf === "function"
          ? detector.extensionOf(metadata.url)
          : "");
      return detector.mediaKindFor(extension, metadata.mime) || "";
    }
    return "";
  }

  function buildDownloadRequest(item, options) {
    const opts = options || {};
    const url = String((item && item.url) || "");
    if (!isHttpUrl(url)) {
      throw new Error("IDM can only download HTTP and HTTPS addresses.");
    }
    const metadata = item || {};
    const payload = {
      type: "request_download",
      request_id: opts.requestId || createRequestId(),
      browser: BROWSER,
      extension_id: chrome.runtime.id,
      client_version: clientVersion(),
      url: url,
      filename: safeFilename(metadata.filename),
      referrer: isHttpUrl(opts.referrer) ? opts.referrer : "",
      page_url: isHttpUrl(opts.pageUrl) ? opts.pageUrl : "",
      mime: shortText(metadata.mime, 120).toLowerCase(),
      total_bytes: positiveInteger(metadata.size_bytes),
      ask_folder: opts.askFolder === true,
      page_title: shortText(opts.pageTitle, 180),
      media_kind: mediaKindFor(metadata),
      quality_label: shortText(metadata.quality_label, 40),
      duration_seconds: positiveInteger(metadata.duration_seconds),
      detected_by:
        metadata.detected_by === "media" || metadata.detected_by === "link"
          ? metadata.detected_by
          : "",
    };
    return payload;
  }

  function sendNative(message) {
    const payload = Object.assign(
      {
        request_id: createRequestId(),
        browser: BROWSER,
        extension_id: chrome.runtime.id,
        client_version: clientVersion(),
      },
      message || {}
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

  const api = {
    BROWSER,
    HOST_NAME,
    PROTOCOL_VERSION,
    buildDownloadRequest,
    clientVersion,
    createRequestId,
    describeFailure,
    isCancelled,
    isHttpUrl,
    mediaKindFor,
    safeFilename,
    sendNative,
    shortText,
  };

  global.IDMNative = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
