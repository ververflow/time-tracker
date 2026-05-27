// Reports the active tab's URL to the local time tracker.
// Nothing leaves your machine — it only POSTs to 127.0.0.1:7879.
const ENDPOINT = "http://127.0.0.1:7879/tab";

async function reportActive() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    if (!tab) return;
    let url = tab.url || "";
    // don't report browser-internal pages as real sites
    if (/^(chrome|edge|brave|about|chrome-extension|edge-extension):/i.test(url)) {
      url = "";
    }
    await fetch(ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "text/plain" }, // simple request, no CORS preflight
      body: JSON.stringify({ url: url, title: tab.title || "" }),
    });
  } catch (e) {
    // tracker not running — ignore silently
  }
}

// Event-driven updates
chrome.tabs.onActivated.addListener(reportActive);
chrome.tabs.onUpdated.addListener((id, info) => {
  if (info.url || info.status === "complete") reportActive();
});
chrome.windows.onFocusChanged.addListener((winId) => {
  if (winId !== chrome.windows.WINDOW_ID_NONE) reportActive();
});
chrome.runtime.onStartup.addListener(reportActive);

// Heartbeat so a long read on one tab stays "fresh" for the tracker
chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("heartbeat", { periodInMinutes: 0.5 });
  reportActive();
});
chrome.alarms.onAlarm.addListener((a) => {
  if (a.name === "heartbeat") reportActive();
});
