"use strict";
/* Exercises the IDM Video Assistant detector and native request builder.
 * Run from pytest; requires Node.js only (no browser, no network). */
const assert = require("assert");
const path = require("path");

global.chrome = {
  runtime: {
    id: "ljckgbgnolmopacdgmmgaijleadcmpgn",
    getManifest: () => ({ version: "3.6.0" }),
  },
};
const BASE = path.resolve(__dirname, "..", "BrowserExtension", "IDMVideoAssistant");
const D = require(path.join(BASE, "media-detector.js"));
const N = require(path.join(BASE, "native-messaging.js"));

function fakeDoc(links, media) {
  return {
    querySelectorAll(selector) {
      if (selector === "a[href]") return links;
      if (selector === "video, audio") return media || [];
      return [];
    },
  };
}

const link = (href, text, download) => ({
  getAttribute: (name) =>
    name === "href" ? href : name === "download" ? download || "" : "",
  textContent: text,
  type: "",
});

const video = {
  tagName: "VIDEO",
  currentSrc: "https://cdn.example.com/clip.MP4",
  src: "https://cdn.example.com/clip.MP4",
  videoHeight: 720,
  duration: 31.4,
  title: "Sample clip",
  querySelectorAll: () => [],
};

// Restricted pages are never scanned for streams. YouTube instead reports
// links to Google's own download options.
const restricted = D.collectMedia(
  fakeDoc([link("https://cdn.example.com/a.mp4", "x")]),
  { pageUrl: "https://www.youtube.com/watch?v=abc", pageTitle: "Video" }
);
assert.equal(restricted.items.length, 0);
assert.ok(restricted.restricted && restricted.restricted.platform === "YouTube");
assert.ok(/DRM|access controls/.test(restricted.restricted.message));
const official = restricted.restricted.official;
assert.ok(official && Array.isArray(official.links));
const officialUrls = official.links.map((option) => option.url);
assert.ok(officialUrls.includes("https://www.youtube.com/premium"));
assert.ok(officialUrls.includes("https://studio.youtube.com"));
assert.ok(officialUrls.includes("https://support.google.com/youtube/answer/56100"));
assert.ok(officialUrls.every((url) => D.isHttpUrl(url)));
assert.ok(officialUrls.every((url) => !/googlevideo|videoplayback|\/watch/i.test(url)));
assert.ok(!/googlevideo|videoplayback/i.test(JSON.stringify(restricted)));
assert.ok(/does not extract/i.test(official.note));

const shortLink = D.collectMedia(fakeDoc([]), {
  pageUrl: "https://youtu.be/abc",
  pageTitle: "Video",
});
assert.equal(shortLink.restricted.platform, "YouTube");
assert.ok(shortLink.restricted.official.links.length > 0);

const music = D.collectMedia(fakeDoc([]), {
  pageUrl: "https://music.youtube.com/watch?v=abc",
  pageTitle: "Song",
});
assert.equal(music.restricted.platform, "YouTube Music");
assert.ok(
  music.restricted.official.links.some(
    (option) => option.url === "https://music.youtube.com/premium"
  )
);

const netflix = D.collectMedia(fakeDoc([]), {
  pageUrl: "https://www.netflix.com/watch/1",
  pageTitle: "Film",
});
assert.equal(netflix.restricted.official, null);
assert.equal(D.officialOptionsFor("file:///etc/passwd", "YouTube"), null);
assert.equal(D.officialOptionsFor("https://vimeo.com/1", "Vimeo"), null);

// A direct media file on a restricted host is an ordinary, authorised link.
assert.equal(D.restrictedPlatformFor("https://youtube.com/file.mp4"), null);
assert.equal(D.restrictedPlatformFor("https://youtube.com/watch?v=1"), "YouTube");
assert.equal(D.isRestrictedMediaHost("https://r1.googlevideo.com/videoplayback"), true);

// Detection reports only metadata the page actually exposes.
const page = D.collectMedia(
  fakeDoc(
    [link("https://cdn.example.com/a.mp4", "Movie", "movie.mp4")],
    [video]
  ),
  { pageUrl: "https://example.com/library", pageTitle: "Library" }
);
assert.equal(page.items.length, 2);
const linked = page.items.find((item) => item.url.endsWith("a.mp4"));
assert.equal(linked.media_kind, "video");
assert.equal(linked.title, "Movie");
assert.equal(linked.filename, "movie.mp4");
const media = page.items.find((item) => /clip/i.test(item.url));
assert.equal(media.media_kind, "video");
assert.equal(media.quality_label, "720p");
assert.equal(media.duration_seconds, 31);
assert.equal(media.detected_by, "media");

// Restricted stream hosts are filtered even when an ordinary page embeds them.
const embeddedStream = D.collectMedia(
  fakeDoc(
    [link("https://r1.googlevideo.com/clip.mp4", "stream")],
    [
      {
        tagName: "VIDEO",
        currentSrc: "https://r1.googlevideo.com/clip.mp4",
        src: "https://r1.googlevideo.com/clip.mp4",
        videoHeight: 1080,
        duration: 10,
        title: "Embedded",
        querySelectorAll: () => [],
      },
    ]
  ),
  { pageUrl: "https://example.com/embed", pageTitle: "Embed" }
);
assert.equal(embeddedStream.items.length, 0);

// Unobservable or implausible values are omitted, never invented.
assert.equal(D.qualityFromVideo({ videoHeight: 2 }), "");
assert.equal(D.durationFromElement({ duration: NaN }), null);
assert.equal(D.qualityFromVideo({}), "");
assert.equal(D.durationFromElement({ duration: 60 * 60 * 24 * 2 }), null);

// A configured archive type is detected but is not called video.
const archive = D.collectMedia(
  fakeDoc([link("https://example.com/setup.zip", "Setup")]),
  { pageUrl: "https://example.com", pageTitle: "Home", fileTypes: "zip" }
);
assert.equal(archive.items.length, 1);
assert.equal(archive.items[0].media_kind, "");

// Request construction matches protocol v2 and rejects unsafe URLs.
const request = N.buildDownloadRequest(archive.items[0], {
  pageUrl: "https://example.com",
  pageTitle: "Home",
});
assert.equal(request.type, "request_download");
assert.equal(request.browser, "chrome");
assert.equal(request.extension_id, "ljckgbgnolmopacdgmmgaijleadcmpgn");
assert.equal(request.media_kind, "");
assert.equal(request.detected_by, "link");

const videoRequest = N.buildDownloadRequest(media, {
  pageUrl: "https://example.com/library",
  pageTitle: "Library",
});
assert.equal(videoRequest.media_kind, "video");
assert.equal(videoRequest.quality_label, "720p");
assert.equal(videoRequest.duration_seconds, 31);
assert.equal(videoRequest.detected_by, "media");
assert.equal(videoRequest.page_url, "https://example.com/library");

assert.equal(
  N.buildDownloadRequest(
    { url: "https://cdn.example.com/track.flac", media_kind: "audio" },
    {}
  ).media_kind,
  "audio"
);
assert.throws(() => N.buildDownloadRequest({ url: "file:///etc/passwd" }, {}));
assert.throws(() => N.buildDownloadRequest({ url: "javascript:alert(1)" }, {}));
assert.equal(N.safeFilename("../../evil.exe"), "");
assert.equal(N.safeFilename("clip.mp4"), "clip.mp4");

// ----------------------------------------------------------- page link capture
// collectLinks gathers every ordinary link a page publishes, not only the
// configured media types, and skips anything IDM cannot download.
const manyLinks = [];
for (let index = 0; index < 140; index += 1) {
  manyLinks.push(link("https://example.com/f" + index + ".zip", "f" + index));
}
const bulk = D.collectLinks(
  fakeDoc(manyLinks),
  { pageUrl: "https://example.com/index.html", pageTitle: "Index" }
);
assert.equal(bulk.total, 140);
assert.equal(bulk.links.length, D.MAX_CAPTURE_LINKS, "the batch stays inside the cap");
assert.equal(bulk.restricted, null);

const mixed = D.collectLinks(
  fakeDoc([
    link("files/a.zip", "A"),
    link("https://example.com/files/a.zip", "A again"),
    link("https://example.com/files/b.pdf", "B", "renamed.pdf"),
    link("#section", "Fragment"),
    link("mailto:someone@example.com", "Mail"),
    link("javascript:alert(1)", "Script"),
    link("https://r1.googlevideo.com/videoplayback", "Protected stream"),
  ]),
  { pageUrl: "https://example.com/index.html", pageTitle: "Index" }
);
assert.deepEqual(mixed.links.map((entry) => entry.url), [
  "https://example.com/files/a.zip",
  "https://example.com/files/b.pdf",
]);
assert.equal(mixed.links[0].filename, "a.zip");
assert.equal(mixed.links[1].filename, "renamed.pdf");
assert.equal(mixed.links[0].title, "A");

const blockedPage = D.collectLinks(
  fakeDoc([link("https://example.com/a.zip", "A")]),
  { pageUrl: "https://www.youtube.com/watch?v=abc", pageTitle: "Video" }
);
assert.equal(blockedPage.links.length, 0);
assert.equal(blockedPage.restricted.platform, "YouTube");

assert.equal(
  D.collectLinks(null, { pageUrl: "https://example.com" }).links.length,
  0
);
assert.equal(
  D.collectLinks(fakeDoc([link("https://example.com/a.zip", "A")]), {
    pageUrl: "file:///C:/page.html",
  }).links.length,
  0
);

const capture = N.buildCaptureRequest(mixed, { pageUrl: "https://example.com" });
assert.equal(capture.type, "capture_page_links");
assert.equal(capture.browser, "chrome");
assert.equal(capture.extension_id, "ljckgbgnolmopacdgmmgaijleadcmpgn");
assert.equal(capture.page_url, "https://example.com/index.html");
assert.equal(capture.page_title, "Index");
assert.deepEqual(capture.links, [
  { url: "https://example.com/files/a.zip", filename: "a.zip" },
  { url: "https://example.com/files/b.pdf", filename: "renamed.pdf" },
]);
assert.throws(() => N.buildCaptureRequest({ page: {}, links: [] }, {}));
assert.throws(() =>
  N.buildCaptureRequest(
    { page: {}, links: [{ url: "javascript:alert(1)" }] },
    {}
  )
);
assert.deepEqual(
  N.buildCaptureRequest(
    { page: {}, links: [{ url: "https://example.com/a.zip", filename: "../../evil.exe" }] },
    {}
  ).links,
  [{ url: "https://example.com/a.zip", filename: "" }]
);
assert.equal(
  N.buildCaptureRequest(
    {
      page: {},
      links: manyLinks.map((entry) => ({
        url: entry.getAttribute("href"),
        filename: "",
      })),
    },
    {}
  ).links.length,
  N.MAX_CAPTURE_LINKS
);

// ------------------------------------------------------------- browser identity
// The native host compares this claim with the process that launched it, so
// Brave and Opera must identify themselves correctly.
function reloadNative(userAgent, braveApi) {
  // Node exposes navigator as a getter-only property, so it has to be
  // redefined rather than assigned.
  Object.defineProperty(global, "navigator", {
    value: userAgent === null ? undefined : { userAgent: userAgent, brave: braveApi },
    configurable: true,
    writable: true,
  });
  delete require.cache[path.join(BASE, "native-messaging.js")];
  return require(path.join(BASE, "native-messaging.js"));
}

const braveApi = { isBrave: () => Promise.resolve(true) };
const braveChromeUA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36";
assert.equal(reloadNative(braveChromeUA, braveApi).BROWSER, "brave");
assert.equal(
  reloadNative(braveChromeUA + " OPR/110.0.0.0", undefined).BROWSER,
  "opera"
);
assert.equal(
  reloadNative(braveChromeUA + " Edg/126.0.0.0", undefined).BROWSER,
  "edge"
);
assert.equal(reloadNative(braveChromeUA, undefined).BROWSER, "chrome");
// A missing navigator (an unexpected context) must not fabricate a browser.
reloadNative(null);
assert.equal(require(path.join(BASE, "native-messaging.js")).BROWSER, "chrome");

console.log("video assistant harness passed");
