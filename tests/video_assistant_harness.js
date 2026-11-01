"use strict";
/* Exercises the IDM Video Assistant detector and native request builder.
 * Run from pytest; requires Node.js only (no browser, no network). */
const assert = require("assert");
const path = require("path");

global.chrome = {
  runtime: {
    id: "ljckgbgnolmopacdgmmgaijleadcmpgn",
    getManifest: () => ({ version: "3.5.0" }),
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

console.log("video assistant harness passed");
