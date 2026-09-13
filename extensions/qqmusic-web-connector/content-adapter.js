const SELECTORS = Object.freeze({
  searchInput: [
    'input[type="search"]',
    'input[placeholder*="搜索"]',
    '[role="searchbox"]',
  ],
  playbackControl: [
    'button[aria-label*="播放"]',
    'button[aria-label*="暂停"]',
    '[role="button"][title*="播放"]',
    '[role="button"][title*="暂停"]',
  ],
  queueSurface: [
    '[aria-label*="播放列表"]',
    '[aria-label*="队列"]',
    '[class*="playlist"]',
    '[class*="queue"]',
  ],
  media: ["audio"],
});

function visible(element) {
  const style = getComputedStyle(element);
  const rect = element.getBoundingClientRect();
  return style.visibility !== "hidden" && style.display !== "none" && rect.width > 0 && rect.height > 0;
}

function uniqueVisibleElements(selectors) {
  const elements = new Set();
  for (const selector of selectors) {
    for (const element of document.querySelectorAll(selector)) {
      if (visible(element)) elements.add(element);
    }
  }
  return [...elements];
}

function pageKind() {
  const path = location.pathname.toLowerCase();
  if (path.includes("/player")) return "player";
  if (path.includes("/search")) return "search";
  if (path.includes("/song")) return "song";
  return "other";
}

function probe() {
  if (location.hostname !== "y.qq.com") {
    return { ok: false, message: "当前标签页不是 QQ 音乐网页版" };
  }
  const searchInputs = uniqueVisibleElements(SELECTORS.searchInput);
  const playbackControls = uniqueVisibleElements(SELECTORS.playbackControl);
  const queueSurfaces = uniqueVisibleElements(SELECTORS.queueSurface);
  const mediaElements = uniqueVisibleElements(SELECTORS.media);
  const capabilities = [];

  // A capability is advertised only when its target is unique enough to avoid blind actions.
  if (searchInputs.length === 1) capabilities.push("catalog.search");
  if (playbackControls.length === 1) capabilities.push("playback.control");
  if (queueSurfaces.length === 1 && playbackControls.length === 1) capabilities.push("queue.play");
  if (mediaElements.length === 1) capabilities.push("playback.state");

  return {
    ok: true,
    status: capabilities.includes("catalog.search") ? "ready" : "degraded",
    pageKind: pageKind(),
    capabilities,
    diagnostics: {
      searchInputCount: searchInputs.length,
      playbackControlCount: playbackControls.length,
      queueSurfaceCount: queueSurfaces.length,
      mediaElementCount: mediaElements.length,
    },
  };
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "moodmusic.probe") return false;
  sendResponse(probe());
  return false;
});
