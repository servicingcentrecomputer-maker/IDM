/* Shared media-link detection used by the content script and the popup.
 *
 * Only observable page metadata is read: anchors, <video>/<audio> sources,
 * MIME types, intrinsic video height and duration. Nothing is probed, fetched
 * or decrypted, and restricted platform pages are never scanned for streams.
 */
(function (global) {
  "use strict";

  const DEFAULT_FILE_TYPES = [
    "mp4",
    "webm",
    "m4v",
    "mov",
    "mkv",
    "mp3",
    "m4a",
    "ogg",
    "wav",
    "flac",
  ];

  const VIDEO_EXTENSIONS = new Set([
    "mp4",
    "webm",
    "m4v",
    "mov",
    "mkv",
    "avi",
    "wmv",
    "flv",
    "mpg",
    "mpeg",
    "3gp",
    "ts",
    "m2ts",
  ]);

  const AUDIO_EXTENSIONS = new Set([
    "mp3",
    "m4a",
    "aac",
    "ogg",
    "oga",
    "wav",
    "flac",
    "opus",
    "wma",
  ]);

  const RESTRICTED_PLATFORMS = {
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "music.youtube.com": "YouTube Music",
    "vimeo.com": "Vimeo",
    "dailymotion.com": "Dailymotion",
    "twitch.tv": "Twitch",
    "netflix.com": "Netflix",
    "hulu.com": "Hulu",
    "primevideo.com": "Prime Video",
    "amazon.com": "Prime Video",
    "disneyplus.com": "Disney+",
    "max.com": "Max",
    "hbomax.com": "Max",
    "peacocktv.com": "Peacock",
    "paramountplus.com": "Paramount+",
    "tiktok.com": "TikTok",
    "instagram.com": "Instagram",
    "facebook.com": "Facebook",
    "x.com": "X",
    "twitter.com": "X",
    "soundcloud.com": "SoundCloud",
    "spotify.com": "Spotify",
  };

  // Direct download traffic that belongs to restricted platforms is left to
  // the browser; IDM must not take over protected or signed stream requests.
  const RESTRICTED_MEDIA_HOSTS = [
    "googlevideo.com",
    "youtube.com",
    "youtu.be",
    "fbcdn.net",
    "cdninstagram.com",
    "tiktokcdn.com",
    "ttvnw.net",
    "video.twimg.com",
  ];

  const MIME_EXTENSIONS = {
    "video/mp4": "mp4",
    "video/webm": "webm",
    "video/quicktime": "mov",
    "video/x-matroska": "mkv",
    "video/x-msvideo": "avi",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/flac": "flac",
  };

  const MAX_LINKS = 4000;
  const MAX_ITEMS = 40;

  function isHttpUrl(value) {
    if (typeof value !== "string") return false;
    try {
      const url = new URL(value);
      return url.protocol === "http:" || url.protocol === "https:";
    } catch {
      return false;
    }
  }

  function hostOf(value) {
    if (typeof value !== "string") return "";
    try {
      return (new URL(value).hostname || "").toLowerCase();
    } catch {
      return "";
    }
  }

  function domainOf(value) {
    const host = hostOf(value);
    return host.startsWith("www.") ? host.slice(4) : host;
  }

  function extensionOf(value) {
    if (typeof value !== "string" || !value) return "";
    let pathname = value;
    let search = "";
    try {
      const url = new URL(value);
      pathname = url.pathname || "";
      search = url.search || "";
    } catch {
      const clean = value.split(/[?#]/, 1)[0];
      pathname = clean;
    }
    const base = pathname.split("/").filter(Boolean).pop() || "";
    const direct = /\.([A-Za-z0-9]{1,10})$/.exec(base);
    if (direct) return direct[1].toLowerCase();
    if (search) {
      try {
        const params = new URLSearchParams(search);
        for (const key of ["filename", "file", "download", "name"]) {
          const candidate = params.get(key);
          if (!candidate) continue;
          const nested = /\.([A-Za-z0-9]{1,10})$/.exec(candidate);
          if (nested) return nested[1].toLowerCase();
        }
      } catch {
        return "";
      }
    }
    return "";
  }

  function filenameFromUrl(value) {
    if (typeof value !== "string" || !value) return "";
    try {
      const url = new URL(value);
      const name = (url.pathname.split("/").filter(Boolean).pop() || "").trim();
      return decodeURIComponent(name).slice(0, 200);
    } catch {
      return "";
    }
  }

  function normalizeExtensionList(value) {
    const source = Array.isArray(value) ? value.join(",") : String(value || "");
    const seen = new Set();
    for (const raw of source.split(/[\s,;]+/)) {
      const item = raw.trim().toLowerCase().replace(/^\.+/, "");
      if (!/^[a-z0-9]{1,10}$/.test(item)) continue;
      seen.add(item);
      if (seen.size >= 50) break;
    }
    if (!seen.size) {
      for (const item of DEFAULT_FILE_TYPES) seen.add(item);
    }
    return Array.from(seen);
  }

  function fileTypesText(value) {
    return normalizeExtensionList(value).join(",");
  }

  function restrictedPlatformFor(value) {
    if (!isHttpUrl(value)) return null;
    if (extensionOf(value)) {
      // A direct media file link is a normal download, not a page whose
      // protected stream would need to be extracted.
      const direct = extensionOf(value);
      if (VIDEO_EXTENSIONS.has(direct) || AUDIO_EXTENSIONS.has(direct)) {
        return null;
      }
    }
    const host = hostOf(value);
    if (!host) return null;
    let match = null;
    for (const [domain, platform] of Object.entries(RESTRICTED_PLATFORMS)) {
      if (host !== domain && !host.endsWith("." + domain)) continue;
      if (!match || domain.length > match.domain.length) {
        match = { domain: domain, platform: platform };
      }
    }
    return match ? match.platform : null;
  }

  function isRestrictedMediaHost(value) {
    const host = hostOf(value);
    if (!host) return false;
    return RESTRICTED_MEDIA_HOSTS.some(
      (domain) => host === domain || host.endsWith("." + domain)
    );
  }

  function isYouTubeHost(value) {
    const host = hostOf(value);
    if (!host) return false;
    return (
      host === "youtu.be" ||
      host === "youtube.com" ||
      host.endsWith(".youtube.com")
    );
  }

  function officialOptionsFor(pageUrl, platform) {
    if (!isYouTubeHost(pageUrl)) return null;
    const music = hostOf(pageUrl) === "music.youtube.com";
    const label = music ? "YouTube Music" : platform || "YouTube";
    return {
      heading: "Official " + label + " download options",
      note:
        "IDM does not extract YouTube streams or bypass download restrictions. " +
        "These buttons open Google's own pages; downloading is handled by " +
        label +
        ".",
      links: [
        {
          id: "youtube-premium",
          label: music ? "YouTube Music Premium" : "YouTube Premium",
          description:
            "Download videos and music for offline use inside the official app.",
          url: music
            ? "https://music.youtube.com/premium"
            : "https://www.youtube.com/premium",
        },
        {
          id: "youtube-studio",
          label: "Download your own uploads in YouTube Studio",
          description:
            "Creators can download MP4 copies of videos they uploaded.",
          url: "https://studio.youtube.com",
        },
        {
          id: "youtube-help",
          label: "YouTube Help: download videos you uploaded",
          description: "Google's official instructions for your own uploads.",
          url: "https://support.google.com/youtube/answer/56100",
        },
      ],
    };
  }

  function restrictionMessage(platform) {
    const name = platform || "this platform";
    return (
      name +
      " pages are not downloadable by IDM. IDM does not bypass DRM, access " +
      "controls or platform download rules. Use the options " +
      name +
      " provides, or add a direct media URL you are authorised to download in " +
      "IDM's Add URL dialog."
    );
  }

  function mediaKindFor(extension, mime) {
    const ext = String(extension || "").toLowerCase();
    if (VIDEO_EXTENSIONS.has(ext)) return "video";
    if (AUDIO_EXTENSIONS.has(ext)) return "audio";
    const type = String(mime || "").split(";")[0].trim().toLowerCase();
    if (type.startsWith("video/")) return "video";
    if (type.startsWith("audio/")) return "audio";
    return "";
  }

  function formatFor(extension, mime) {
    const ext = String(extension || "").toLowerCase();
    if (ext) return ext;
    const type = String(mime || "").split(";")[0].trim().toLowerCase();
    return MIME_EXTENSIONS[type] || "";
  }

  function qualityFromVideo(element) {
    if (!element || typeof element !== "object") return "";
    const height = Number(element.videoHeight);
    if (Number.isFinite(height) && height >= 144) return Math.round(height) + "p";
    return "";
  }

  function durationFromElement(element) {
    if (!element || typeof element !== "object") return null;
    const duration = Number(element.duration);
    if (!Number.isFinite(duration) || duration <= 0) return null;
    if (duration > 60 * 60 * 24) return null;
    return Math.round(duration);
  }

  function safeTitle(value, fallback) {
    const text = String(value || "")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 180);
    return text || fallback || "";
  }

  function makeItem(raw) {
    const extension = String(raw.extension || "").toLowerCase();
    const mime = String(raw.mime || "").toLowerCase();
    const kind = raw.media_kind || mediaKindFor(extension, mime);
    const filename = String(raw.filename || "").slice(0, 200);
    const size =
      Number.isSafeInteger(raw.size_bytes) && raw.size_bytes > 0
        ? raw.size_bytes
        : null;
    const duration =
      Number.isSafeInteger(raw.duration_seconds) && raw.duration_seconds > 0
        ? raw.duration_seconds
        : null;
    return {
      url: raw.url,
      filename: filename,
      title: safeTitle(raw.title, filename || domainOf(raw.url) || "Media"),
      extension: extension || formatFor("", mime),
      format: formatFor(extension, mime),
      media_kind: kind,
      mime: mime,
      size_bytes: size,
      quality_label: safeTitle(raw.quality_label, ""),
      duration_seconds: duration,
      detected_by: raw.detected_by || "link",
    };
  }

  function mergeItem(existing, candidate) {
    if (!existing) return candidate;
    const merged = Object.assign({}, existing);
    for (const key of [
      "filename",
      "title",
      "extension",
      "format",
      "media_kind",
      "mime",
      "size_bytes",
      "quality_label",
      "duration_seconds",
    ]) {
      const value = candidate[key];
      if (
        value !== null &&
        value !== undefined &&
        value !== "" &&
        (merged[key] === null || merged[key] === undefined || merged[key] === "")
      ) {
        merged[key] = value;
      }
    }
    if (candidate.detected_by === "media" && merged.detected_by !== "media") {
      merged.detected_by = "media";
      if (candidate.title) merged.title = candidate.title;
    }
    return merged;
  }

  function collectMedia(documentLike, options) {
    const opts = options || {};
    const pageUrl = String(opts.pageUrl || "");
    const pageTitle = safeTitle(opts.pageTitle, "");
    const extensions = new Set(
      normalizeExtensionList(opts.fileTypes || DEFAULT_FILE_TYPES)
    );
    const page = {
      url: pageUrl,
      title: pageTitle,
      domain: domainOf(pageUrl),
    };

    if (!isHttpUrl(pageUrl)) {
      return { page, items: [], restricted: null };
    }

    const platform = restrictedPlatformFor(pageUrl);
    if (platform) {
      return {
        page,
        items: [],
        restricted: {
          platform: platform,
          page_url: pageUrl,
          message: restrictionMessage(platform),
          official: officialOptionsFor(pageUrl, platform),
        },
      };
    }

    if (!documentLike || typeof documentLike.querySelectorAll !== "function") {
      return { page, items: [], restricted: null };
    }

    const found = new Map();

    const links = documentLike.querySelectorAll("a[href]");
    const linkCount = Math.min(links.length || 0, MAX_LINKS);
    for (let index = 0; index < linkCount; index += 1) {
      const link = links[index];
      if (!link || typeof link.getAttribute !== "function") continue;
      const href = link.getAttribute("href");
      if (!href || href.startsWith("#")) continue;
      let url;
      try {
        url = new URL(href, pageUrl).href;
      } catch {
        continue;
      }
      if (!isHttpUrl(url) || found.has(url)) continue;
      if (isRestrictedMediaHost(url)) continue;
      const extension = extensionOf(url);
      if (!extensions.has(extension)) continue;
      const downloadName =
        typeof link.getAttribute === "function"
          ? link.getAttribute("download")
          : "";
      const filename =
        (downloadName && String(downloadName).trim()) || filenameFromUrl(url);
      const label = safeTitle(link.textContent, filename);
      found.set(
        url,
        makeItem({
          url: url,
          filename: filename,
          title: label,
          extension: extension,
          media_kind: mediaKindFor(extension, ""),
          mime: String(link.type || ""),
          detected_by: "link",
        })
      );
      if (found.size >= MAX_ITEMS) break;
    }

    const mediaNodes = documentLike.querySelectorAll("video, audio");
    const mediaCount = Math.min(mediaNodes.length || 0, 50);
    for (let index = 0; index < mediaCount; index += 1) {
      const element = mediaNodes[index];
      if (!element) continue;
      const tag = String(element.tagName || "").toLowerCase();
      const candidates = [];
      if (element.currentSrc) candidates.push({ url: element.currentSrc, mime: "" });
      if (element.src) candidates.push({ url: element.src, mime: "" });
      const sources =
        typeof element.querySelectorAll === "function"
          ? element.querySelectorAll("source[src]")
          : [];
      for (let sourceIndex = 0; sourceIndex < (sources.length || 0); sourceIndex += 1) {
        const source = sources[sourceIndex];
        if (!source) continue;
        candidates.push({
          url: source.getAttribute ? source.getAttribute("src") : source.src,
          mime: source.type || "",
        });
      }
      for (const candidate of candidates) {
        let url;
        try {
          url = new URL(candidate.url, pageUrl).href;
        } catch {
          continue;
        }
        if (!isHttpUrl(url)) continue;
        if (isRestrictedMediaHost(url)) continue;
        const extension = extensionOf(url) || formatFor("", candidate.mime);
        if (!extensions.has(extension)) continue;
        const filename = filenameFromUrl(url);
        const item = makeItem({
          url: url,
          filename: filename,
          title: safeTitle(element.title, filename),
          extension: extension,
          media_kind: tag === "audio" ? "audio" : mediaKindFor(extension, candidate.mime),
          mime: candidate.mime,
          quality_label: tag === "video" ? qualityFromVideo(element) : "",
          duration_seconds: durationFromElement(element),
          detected_by: "media",
        });
        found.set(url, mergeItem(found.get(url), item));
        if (found.size >= MAX_ITEMS) break;
      }
      if (found.size >= MAX_ITEMS) break;
    }

    return {
      page: page,
      items: Array.from(found.values()).slice(0, MAX_ITEMS),
      restricted: null,
    };
  }

  function countLabel(count) {
    if (!Number.isFinite(count) || count <= 0) return "";
    return count > 9 ? "9+" : String(count);
  }

  const api = {
    DEFAULT_FILE_TYPES,
    VIDEO_EXTENSIONS,
    AUDIO_EXTENSIONS,
    RESTRICTED_PLATFORMS,
    collectMedia,
    countLabel,
    domainOf,
    durationFromElement,
    extensionOf,
    fileTypesText,
    filenameFromUrl,
    formatFor,
    hostOf,
    isHttpUrl,
    isRestrictedMediaHost,
    isYouTubeHost,
    mediaKindFor,
    normalizeExtensionList,
    officialOptionsFor,
    qualityFromVideo,
    restrictedPlatformFor,
    restrictionMessage,
  };

  global.IDMDetector = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
