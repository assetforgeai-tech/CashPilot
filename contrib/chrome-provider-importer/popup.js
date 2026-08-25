const DEFAULT_SERVER = "https://cashpilot.4gmt.com";

let lastImport = null;

function setStatus(html) {
  document.getElementById("status").innerHTML = html;
}

function setEarnAppStatus(html) {
  document.getElementById("earnapp-status").innerHTML = html;
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
  try {
    const server = normalizeServer(document.getElementById("server-url").value || DEFAULT_SERVER);
    await chrome.storage.local.set({ server });
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
  let url;
  try {
    url = new URL(String(value || DEFAULT_SERVER).trim());
  } catch (_error) {
    throw new Error("CashPilot URL is invalid");
  }
  const hostname = url.hostname.toLowerCase();
  if (
    url.protocol !== "https:" ||
    !(hostname === "4gmt.com" || hostname.endsWith(".4gmt.com")) ||
    url.username ||
    url.password
  ) {
    throw new Error("CashPilot must use an HTTPS 4gmt.com hostname");
  }
  return url.origin;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

document.getElementById("scan").addEventListener("click", scan);
document.getElementById("save").addEventListener("click", save);

function formatExpiry(seconds) {
  if (!seconds) return "expiry unknown";
  return `expires ${new Date(seconds * 1000).toLocaleString()}`;
}

function applyEarnAppBinding(binding) {
  if (!binding) return;
  document.getElementById("server-url").value = binding.server || DEFAULT_SERVER;
  document.getElementById("earnapp-account-name").value = binding.accountName || "";
  document.getElementById("earnapp-email").value = binding.email || "";
  document.getElementById("earnapp-auth-method").value = binding.authMethod || "google";
  for (const id of ["server-url", "earnapp-account-name", "earnapp-email", "earnapp-auth-method"]) {
    document.getElementById(id).disabled = true;
  }
  document.getElementById("import-earnapp").textContent = "Sync bound account now";
  const synced = binding.lastSyncedAt ? new Date(binding.lastSyncedAt).toLocaleString() : "not yet";
  const warning = binding.lastError ? `<div class="warn">${escapeHtml(binding.lastError)}</div>` : "";
  setEarnAppStatus(`
    <div class="ok">Bound to <b>${escapeHtml(binding.accountName)}</b> via ${escapeHtml(binding.authMethod)}.</div>
    <div class="muted">Last sync: ${escapeHtml(synced)}; token ${escapeHtml(formatExpiry(binding.tokenExpiresAt))}.</div>
    ${warning}
  `);
}

async function importEarnApp() {
  const button = document.getElementById("import-earnapp");
  button.disabled = true;
  setEarnAppStatus('<div class="muted">Reading allowlisted EarnApp cookies and syncing...</div>');
  try {
    const response = await chromeCall(chrome.runtime.sendMessage, {
      type: "IMPORT_EARNAPP_ACCOUNT",
      server: normalizeServer(document.getElementById("server-url").value || DEFAULT_SERVER),
      accountName: document.getElementById("earnapp-account-name").value.trim(),
      email: document.getElementById("earnapp-email").value.trim(),
      authMethod: document.getElementById("earnapp-auth-method").value,
    });
    if (!response?.ok) throw new Error(response?.error || "EarnApp import failed");
    applyEarnAppBinding(response.binding);
  } catch (error) {
    setEarnAppStatus(`<div class="warn">Import failed: ${escapeHtml(error.message)}</div>`);
  } finally {
    button.disabled = false;
  }
}

document.getElementById("import-earnapp").addEventListener("click", importEarnApp);

chrome.runtime.onMessage.addListener(message => {
  if (message?.type !== "EARNAPP_SYNC_STATUS") return;
  if (message.binding) applyEarnAppBinding(message.binding);
  if (message.status === "error") {
    setEarnAppStatus(`<div class="warn">Automatic sync failed: ${escapeHtml(message.error || "Unknown error")}</div>`);
  }
});

chrome.storage.local.get({ server: DEFAULT_SERVER }, stored => {
  document.getElementById("server-url").value = stored.server || DEFAULT_SERVER;
});

chrome.runtime.sendMessage({ type: "GET_EARNAPP_BINDING" }, response => {
  if (response?.ok && response.binding) applyEarnAppBinding(response.binding);
});
