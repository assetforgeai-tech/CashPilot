const DEFAULT_SERVER = "http://42.96.13.215:8080";

let lastImport = null;

function setStatus(html) {
  document.getElementById("status").innerHTML = html;
}

function chromeCall(fn, ...args) {
  return new Promise((resolve, reject) => {
    fn(...args, result => {
      const err = chrome.runtime.lastError;
      if (err) reject(new Error(err.message));
      else resolve(result);
    });
  });
}

async function activeTab() {
  const tabs = await chromeCall(chrome.tabs.query, { active: true, currentWindow: true });
  if (!tabs.length || !tabs[0].id) throw new Error("No active tab");
  return tabs[0];
}

async function scan() {
  document.getElementById("save").disabled = true;
  lastImport = null;
  try {
    const tab = await activeTab();
    const [result] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ["extractor.js"],
    });
    const payload = result?.result;
    if (!payload || !Object.keys(payload.data || {}).length) {
      setStatus(`<div class="warn">No importable config found for this tab.</div><div class="muted">${payload?.reason || ""}</div>`);
      return;
    }
    lastImport = payload;
    const keys = Object.keys(payload.data).sort();
    setStatus(`
      <div class="ok">Found ${keys.length} setting(s) for <b>${escapeHtml(payload.slug)}</b>.</div>
      <ul class="keys">${keys.map(k => `<li><code>${escapeHtml(k)}</code></li>`).join("")}</ul>
      <div class="muted">Values are hidden. Press Save to write these keys into CashPilot Settings.</div>
    `);
    document.getElementById("save").disabled = false;
  } catch (err) {
    setStatus(`<div class="warn">Scan failed: ${escapeHtml(err.message)}</div>`);
  }
}

async function save() {
  if (!lastImport) return;
  const server = normalizeServer(document.getElementById("server-url").value || DEFAULT_SERVER);
  await chrome.storage.local.set({ server });
  try {
    const tabs = await chromeCall(chrome.tabs.query, { url: [`${server}/*`] });
    if (!tabs.length) {
      throw new Error(`Open ${server}/settings and sign in first`);
    }
    const tab = tabs.find(t => (t.url || "").includes("/settings")) || tabs[0];
    const saved = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: async payload => {
        const resp = await fetch("/api/config", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ data: payload?.data || {} }),
        });
        if (!resp.ok) {
          const detail = await resp.text().catch(() => "");
          return { status: "error", error: `${resp.status} ${detail}`.trim() };
        }
        return { status: "saved" };
      },
      args: [{ data: lastImport.data }],
    });
    if (saved[0]?.result?.status === "saved") {
      setStatus(`<div class="ok">Saved ${Object.keys(lastImport.data).length} setting(s) to CashPilot.</div>`);
      document.getElementById("save").disabled = true;
      return;
    }
    throw new Error(saved[0]?.result?.error || "Save failed");
  } catch (err) {
    setStatus(`<div class="warn">Save failed: ${escapeHtml(err.message)}</div>`);
  }
}

function normalizeServer(value) {
  return String(value || DEFAULT_SERVER).trim().replace(/\/+$/, "");
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

document.getElementById("scan").addEventListener("click", scan);
document.getElementById("save").addEventListener("click", save);

chrome.storage.local.get({ server: DEFAULT_SERVER }, stored => {
  document.getElementById("server-url").value = stored.server || DEFAULT_SERVER;
});
