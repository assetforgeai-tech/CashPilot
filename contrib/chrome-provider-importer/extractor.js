(() => {
  const host = location.hostname.toLowerCase();
  const href = location.href;
  const text = document.body?.innerText || "";
  const cookie = document.cookie || "";

  function storageSnapshot(store) {
    const out = {};
    try {
      for (let i = 0; i < store.length; i += 1) {
        const key = store.key(i);
        if (key) out[key] = store.getItem(key) || "";
      }
    } catch (_) {
      return {};
    }
    return out;
  }

  const local = storageSnapshot(localStorage);
  const session = storageSnapshot(sessionStorage);
  const stores = { ...local, ...session };
  const data = {};
  const notes = [];

  function add(key, value, note) {
    const val = String(value || "").trim();
    if (!key || !val) return;
    data[key] = val;
    if (note) notes.push(note);
  }

  function cookieValue(name) {
    const match = cookie.match(new RegExp(`(?:^|;\\s*)${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}=([^;]+)`));
    return match ? decodeURIComponent(match[1]) : "";
  }

  function findStoreValue(pattern) {
    const re = pattern instanceof RegExp ? pattern : new RegExp(pattern, "i");
    for (const [key, value] of Object.entries(stores)) {
      if (re.test(key) && value) return value;
    }
    return "";
  }

  function findText(regex) {
    const match = text.match(regex);
    return match ? match[1] : "";
  }

  let slug = "";

  if (host.includes("dawninternet.com")) {
    slug = "dawn";
    add("dawn_dashboard_session", cookie, "Dawn dashboard cookie/session string");
  } else if (host.includes("titannet.info")) {
    slug = "titan";
    add("titan_dashboard_session", cookie, "Titan dashboard cookie/session string");
  } else if (host.includes("traffmonetizer.com")) {
    slug = "traffmonetizer";
    add("traffmonetizer_token", findStoreValue(/access.*token|jwt|token/i), "Traffmonetizer browser token");
  } else if (host.includes("packetstream.io")) {
    slug = "packetstream";
    add("packetstream_auth_token", cookieValue("auth") || cookie, "PacketStream auth cookie");
  } else if (host.includes("app.grass.io")) {
    slug = "grass";
    add("grass_access_token", findStoreValue(/^accessToken$|access[_-]?token/i), "Grass access token");
    add("grass_store_access_token", findStoreValue(/^accessToken$|access[_-]?token/i), "Grass store access token");
    add("grass_store_refresh_token", findStoreValue(/^refreshToken$|refresh[_-]?token/i), "Grass refresh token");
    add("grass_store_token_expiry", findStoreValue(/tokenExpiry|token_expiry|expires/i), "Grass token expiry");
    add("grass_store_wynd_user_id", findStoreValue(/user[_-]?id|userId/i), "Grass user id");
  } else if (host.includes("spide.network")) {
    slug = "spide";
    add("spide_dashboard_token", cookie || findStoreValue(/token|jwt|session/i), "Spide dashboard session/token");
  } else if (host.includes("ur.network")) {
    slug = "urnetwork";
    add("urnetwork_auth_token", findStoreValue(/auth.*token|access.*token|jwt/i), "URnetwork auth token");
    add("urnetwork_api_key", findStoreValue(/api.*key|apikey/i), "URnetwork API key");
  } else if (host.includes("peer.proxybase.org")) {
    slug = "proxybase";
    add("proxybase_dashboard_access_token", findStoreValue(/access.*token|jwt|token/i) || cookieValue("access_token"), "ProxyBase dashboard token");
  } else if (host.includes("lk.proxylite.ru")) {
    slug = "proxylite";
    add("proxylite_user_id", findText(/(?:User\s*ID|ID пользователя|USER_ID)\D+(\d{3,})/i), "ProxyLite dashboard user id");
  }

  return {
    slug,
    url: href,
    data,
    notes,
    reason: slug ? "Known provider, but no readable configured values were exposed on this page." : `Unsupported provider host: ${host}`,
  };
})();
