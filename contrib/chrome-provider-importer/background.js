const DEFAULT_SERVER = "https://cashpilot.4gmt.com";
const EARNAPP_BINDING_KEY = "earnappAccountBinding";
const EARNAPP_SYNC_ALARM = "earnapp-token-sync";
const EARNAPP_COOKIE_DEBOUNCE_ALARM = "earnapp-cookie-debounce";
const EARNAPP_COOKIE_ALLOWLIST = Object.freeze([
  "auth",
  "auth-method",
  "oauth-refresh-token",
  "oauth-token",
  "xsrf-token",
  "brd_sess_id",
  "cg_uuid",
]);

function normalizeCashPilotServer(value) {
  let url;
  try {
    url = new URL(String(value || DEFAULT_SERVER).trim());
  } catch (_error) {
    throw new Error("CashPilot URL is invalid");
  }
  const hostname = url.hostname.toLowerCase();
  const allowedHost = hostname === "4gmt.com" || hostname.endsWith(".4gmt.com");
  if (url.protocol !== "https:" || !allowedHost || url.username || url.password) {
    throw new Error("CashPilot must use an HTTPS 4gmt.com hostname");
  }
  return url.origin;
}

function decodeJwtPayload(value) {
  const parts = String(value || "").split(".");
  if (parts.length !== 3) return null;
  try {
    const encoded = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = encoded.padEnd(encoded.length + ((4 - (encoded.length % 4)) % 4), "=");
    return JSON.parse(atob(padded));
  } catch (_error) {
    return null;
  }
}

function decodeJwtExpiry(value) {
  const payload = decodeJwtPayload(value);
  const expiry = Number(payload?.exp || 0);
  return Number.isFinite(expiry) && expiry > 0 ? expiry : null;
}

function accountFingerprint(cookies, fallback) {
  const payload = decodeJwtPayload(cookies?.["oauth-refresh-token"]?.value);
  for (const key of ["sub", "user_id", "uid", "email"]) {
    const value = String(payload?.[key] || "").trim().toLowerCase();
    if (value) return `${key}:${value}`;
  }
  return `label:${String(fallback || "").trim().toLowerCase()}`;
}

function assertSameAccount(binding, cookies) {
  const current = accountFingerprint(cookies, binding.accountName || binding.email);
  if (binding.accountFingerprint && current !== binding.accountFingerprint) {
    throw new Error("This Chrome profile is already bound to a different EarnApp account");
  }
}

function cookieScore(cookie) {
  const domain = String(cookie.domain || "").replace(/^\./, "").toLowerCase();
  return (domain === "earnapp.com" ? 4 : 0) + (cookie.path === "/" ? 2 : 0) + (cookie.secure ? 1 : 0);
}

async function collectEarnAppCookies() {
  const found = await chrome.cookies.getAll({ domain: "earnapp.com" });
  const selected = new Map();
  for (const cookie of found) {
    if (!EARNAPP_COOKIE_ALLOWLIST.includes(cookie.name) || !cookie.value) continue;
    const previous = selected.get(cookie.name);
    if (!previous || cookieScore(cookie) > cookieScore(previous)) selected.set(cookie.name, cookie);
  }
  const cookies = {};
  for (const name of EARNAPP_COOKIE_ALLOWLIST) {
    const cookie = selected.get(name);
    if (!cookie) continue;
    cookies[name] = {
      value: cookie.value,
      expirationDate: Number.isFinite(cookie.expirationDate) ? cookie.expirationDate : null,
    };
  }
  if (!cookies["oauth-refresh-token"] || !cookies["xsrf-token"]) {
    throw new Error("Open earnapp.com and sign in before importing this profile");
  }
  return cookies;
}

async function getBinding() {
  const stored = await chrome.storage.local.get({ [EARNAPP_BINDING_KEY]: null });
  return stored[EARNAPP_BINDING_KEY];
}

function expiryMetadata(cookies) {
  const tokenExpiresAt = decodeJwtExpiry(cookies["oauth-refresh-token"]?.value);
  const cookieExpirations = Object.values(cookies)
    .map(cookie => Number(cookie.expirationDate || 0))
    .filter(value => Number.isFinite(value) && value > 0);
  return {
    tokenExpiresAt,
    cookieExpiresAt: cookieExpirations.length ? Math.min(...cookieExpirations) : null,
  };
}

function publicBinding(binding) {
  if (!binding) return null;
  return {
    profileKey: binding.profileKey,
    accountName: binding.accountName,
    email: binding.email,
    authMethod: binding.authMethod,
    server: binding.server,
    lastSyncedAt: binding.lastSyncedAt || null,
    tokenExpiresAt: binding.tokenExpiresAt || null,
    cookieExpiresAt: binding.cookieExpiresAt || null,
    lastError: binding.lastError || null,
  };
}

async function postToCashPilot(server, payload) {
  const origin = normalizeCashPilotServer(server);
  const tabs = await chrome.tabs.query({ url: [`${origin}/*`] });
  if (!tabs.length) throw new Error(`Open ${origin}/settings and sign in as owner first`);
  const target = tabs.find(tab => String(tab.url || "").includes("/settings")) || tabs[0];
  const [result] = await chrome.scripting.executeScript({
    target: { tabId: target.id },
    func: async importPayload => {
      const response = await fetch("/api/admin/earnapp/accounts/import", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(importPayload),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        return { ok: false, status: response.status, detail: body.detail || "Import failed" };
      }
      const body = await response.json();
      return { ok: true, accountId: body.account_id };
    },
    args: [payload],
  });
  if (!result?.result?.ok) {
    const status = result?.result?.status ? ` (${result.result.status})` : "";
    throw new Error(`${result?.result?.detail || "CashPilot import failed"}${status}`);
  }
  return result.result.accountId;
}

async function notifyStatus(status, detail = {}) {
  await chrome.runtime.sendMessage({ type: "EARNAPP_SYNC_STATUS", status, ...detail }).catch(() => undefined);
}

async function persistSyncResult(binding, cookies, accountId) {
  const expiry = expiryMetadata(cookies);
  const updated = {
    ...binding,
    accountId,
    lastSyncedAt: new Date().toISOString(),
    tokenExpiresAt: expiry.tokenExpiresAt,
    cookieExpiresAt: expiry.cookieExpiresAt,
    lastError: null,
  };
  await chrome.storage.local.set({ [EARNAPP_BINDING_KEY]: updated });
  chrome.alarms.create(EARNAPP_SYNC_ALARM, { periodInMinutes: 15 });
  return updated;
}

async function syncBoundEarnAppAccount() {
  const binding = await getBinding();
  if (!binding) return;
  try {
    const cookies = await collectEarnAppCookies();
    assertSameAccount(binding, cookies);
    const accountId = await postToCashPilot(binding.server, {
      profile_key: binding.profileKey,
      account_name: binding.accountName,
      email: binding.email,
      auth_method: binding.authMethod,
      cookies,
    });
    const updated = await persistSyncResult(binding, cookies, accountId);
    await notifyStatus("synced", { binding: publicBinding(updated) });
  } catch (error) {
    const updated = { ...binding, lastError: String(error?.message || "EarnApp sync failed") };
    await chrome.storage.local.set({ [EARNAPP_BINDING_KEY]: updated });
    await notifyStatus("error", { error: updated.lastError, binding: publicBinding(updated) });
  }
}

async function importEarnAppAccount(message) {
  const accountName = String(message.accountName || "").trim();
  const email = String(message.email || "").trim();
  const authMethod = String(message.authMethod || "").trim().toLowerCase();
  if (!accountName) throw new Error("EarnApp account name is required");
  if (!new Set(["google", "apple"]).has(authMethod)) throw new Error("Choose Google or Apple login");
  const server = normalizeCashPilotServer(message.server);
  const cookies = await collectEarnAppCookies();
  const existing = await getBinding();
  if (existing) {
    if (
      existing.accountName !== accountName ||
      existing.email !== email ||
      existing.authMethod !== authMethod ||
      existing.server !== server
    ) {
      throw new Error("This Chrome profile is already bound; use its existing EarnApp account and server");
    }
    assertSameAccount(existing, cookies);
  }
  const binding = existing || {
    profileKey: `earnapp-profile-${crypto.randomUUID()}`,
    accountName,
    email,
    authMethod,
    accountFingerprint: accountFingerprint(cookies, accountName || email),
    server,
    createdAt: new Date().toISOString(),
  };
  const accountId = await postToCashPilot(server, {
    profile_key: binding.profileKey,
    account_name: binding.accountName,
    email: binding.email,
    auth_method: binding.authMethod,
    cookies,
  });
  return persistSyncResult(binding, cookies, accountId);
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "GET_EARNAPP_BINDING") {
    getBinding()
      .then(binding => sendResponse({ ok: true, binding: publicBinding(binding) }))
      .catch(error => sendResponse({ ok: false, error: String(error?.message || error) }));
    return true;
  }
  if (message?.type === "IMPORT_EARNAPP_ACCOUNT") {
    importEarnAppAccount(message)
      .then(binding => sendResponse({ ok: true, binding: publicBinding(binding) }))
      .catch(error => sendResponse({ ok: false, error: String(error?.message || error) }));
    return true;
  }
  if (message?.type === "SYNC_EARNAPP_ACCOUNT") {
    syncBoundEarnAppAccount()
      .then(() => sendResponse({ ok: true }))
      .catch(error => sendResponse({ ok: false, error: String(error?.message || error) }));
    return true;
  }
  return false;
});

chrome.cookies.onChanged.addListener(changeInfo => {
  const cookie = changeInfo.cookie;
  const domain = String(cookie?.domain || "").replace(/^\./, "").toLowerCase();
  if ((domain === "earnapp.com" || domain.endsWith(".earnapp.com")) && EARNAPP_COOKIE_ALLOWLIST.includes(cookie.name)) {
    chrome.alarms.create(EARNAPP_COOKIE_DEBOUNCE_ALARM, { delayInMinutes: 0.5 });
  }
});

chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === EARNAPP_SYNC_ALARM || alarm.name === EARNAPP_COOKIE_DEBOUNCE_ALARM) {
    void syncBoundEarnAppAccount();
  }
});

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create(EARNAPP_SYNC_ALARM, { periodInMinutes: 15 });
});

chrome.runtime.onStartup.addListener(() => void syncBoundEarnAppAccount());
