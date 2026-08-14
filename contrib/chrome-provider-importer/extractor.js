(() => {
  const host = location.hostname.toLowerCase();
  const href = location.href;
  const text = (document.body && document.body.innerText) || "";
  const cookie = document.cookie || "";

  const slug = detectSlug(host, href, text);
  const data = {};
  const notes = [];
  const local = snapshot(localStorage);
  const session = snapshot(sessionStorage);
  const stores = { ...local, ...session };
  const jsonStores = scanJsonStores(stores);

  const readers = {
    grass: () => {
      add("grass_store_wynd_status", pick([
        textMatch(/Registration Status:\s*(Registered|Unregistered)/i, 1),
        storeMatch(/wynd:?status|registration status|status/i),
      ]), "Grass registration state");
      add("grass_store_wynd_user_id", pick([storeMatch(/wynd:?user_id|user_id|user id|userid/i), jsonMatch(["wynd:user_id", "user_id", "userId", "user_id"]) ]), "Grass user id");
      add("grass_store_token_expiry", pick([storeMatch(/tokenExpiry|token_expiry|expires/i), jsonMatch(["tokenExpiry", "expiresAt", "expires_at"]) ]), "Grass token expiry");
      add("grass_store_auto_update", pick([storeMatch(/autoUpdate|auto_update/i), jsonMatch(["autoUpdate", "auto_update"]) ]), "Grass auto update");
      add("grass_store_wynd_authenticated", pick([storeMatch(/wynd:?authenticated|authenticated/i), jsonMatch(["wynd:authenticated", "authenticated"]) ]), "Grass auth flag");
      add("grass_store_refresh_token", pick([storeMatch(/refreshToken|refresh_token/i), jsonMatch(["refreshToken", "refresh_token"]) ]), "Grass refresh token");
      add("grass_store_access_token", pick([storeMatch(/accessToken|access_token/i), jsonMatch(["accessToken", "access_token"]) ]), "Grass access token");
      add("grass_access_token", pick([storeMatch(/accessToken|access_token/i), jsonMatch(["accessToken", "access_token"]) ]), "Grass access token");
    },
    uprock: () => {
      add("uprock_credentials_json", pick([jsonStoreMatch(/credentials_json/i), storeMatch(/credentials_json/i)]), "Uprock credentials_json");
      add("uprock_main_db", pick([storeMatch(/main_db|main\.db/i)]), "Uprock main.db");
    },
    wipter: () => {
      add("wipter_email", pick([storeMatch(/email/i), inputValue("email"), textMatch(/email[:\s]+([^\s@]+@[^\s@]+)/i, 1)]), "Wipter email");
      add("wipter_password", pick([storeMatch(/password/i), inputValue("password")]), "Wipter password");
    },
    traffmonetizer: () => add("traffmonetizer_token", pick([storeMatch(/access.*token|jwt|token/i), jsonStoreMatch(/token/i)]), "Traffmonetizer token"),
    packetstream: () => {
      add("packetstream_auth_token", pick([cookieValue("auth"), cookie, storeMatch(/auth|token/i), jsonStoreMatch(/auth|token/i)]), "PacketStream auth token");
      add("packetstream_cid", pick([queryValue("psr"), inputValue("referral-link").match(/[?&]psr=([^&\s]+)/i)?.[1], textMatch(/[?&]psr=([^&\s]+)/i, 1)]), "PacketStream CID");
    },
    bitping: () => add("bitping_dashboard_session", pick([cookie, storeMatch(/token|session|auth/i), jsonStoreMatch(/token|session|auth/i)]), "Bitping session"),
    earnapp: () => {
      add("earnapp_oauth_refresh_token", pick([cookieValue("oauth-refresh-token"), cookieValue("refresh-token"), storeMatch(/oauth.*refresh|refresh.*token/i), jsonStoreMatch(/oauth.*refresh|refresh.*token/i)]), "EarnApp oauth refresh token");
      add("earnapp_oauth_token", pick([cookieValue("oauth-token"), cookieValue("oauth-refresh-token"), cookieValue("refresh-token"), storeMatch(/oauth.*token|refresh.*token/i), jsonStoreMatch(/oauth.*token|refresh.*token/i)]), "EarnApp oauth token");
      add("earnapp_xsrf_token", pick([cookieValue("XSRF-TOKEN"), cookieValue("xsrf-token"), storeMatch(/xsrf/i), jsonStoreMatch(/xsrf/i)]), "EarnApp XSRF token");
      add("earnapp_brd_sess_id", pick([cookieValue("brd_sess_id"), storeMatch(/brd.*sess/i), jsonStoreMatch(/brd.*sess/i)]), "EarnApp BRD session id");
      add("earnapp_cg_uuid", pick([cookieValue("cg_uuid"), storeMatch(/cg.*uuid/i), jsonStoreMatch(/cg.*uuid/i)]), "EarnApp CG UUID");
    },
    earnfm: () => add("earnfm_token", pick([storeMatch(/api.*key|uuid|token/i), jsonStoreMatch(/api.*key|uuid|token/i)]), "Earn.fm API key"),
    iproyal: () => {
      add("iproyal_email", pick([inputValue("email"), storeMatch(/email/i), textMatch(/email[:\s]+([^\s@]+@[^\s@]+)/i, 1)]), "IPRoyal email");
      add("iproyal_password", pick([inputValue("password"), storeMatch(/password/i)]), "IPRoyal password");
      add("iproyal_device_name", pick([inputValue("device-name"), inputValue("device_name"), textMatch(/device name[:\s]+([^\s]+)/i, 1)]), "IPRoyal device name");
      add("iproyal_device_id", pick([inputValue("device-id"), inputValue("device_id"), textMatch(/device id[:\s]+([^\s]+)/i, 1)]), "IPRoyal device id");
    },
    packetstream2: () => {},
    proxies_sx: () => add("proxies-sx_api_key", pick([storeMatch(/api.*key|token/i), jsonStoreMatch(/api.*key|token/i)]), "Proxies.sx API key"),
    proxybase_xyz: () => add("proxybase-xyz_phrase", pick([storeMatch(/phase|phrase|mnemonic|seed/i), jsonStoreMatch(/phase|phrase|mnemonic|seed/i)]), "ProxyBase Markets wallet phrase"),
    proxybase: () => {
      const token = pick([storeMatch(/access.*token|token/i), jsonStoreMatch(/access.*token|token/i)]);
      add("proxybase_deploy_access_token", token, "ProxyBase deploy token");
      add("proxybase_dashboard_access_token", token, "ProxyBase dashboard token");
    },
    proxylite: () => add("proxylite_user_id", pick([textMatch(/(?:User\s*ID|USER_ID)\D+(\d{3,})/i, 1), storeMatch(/user[_-]?id|userid/i), inputValue("user_id")]), "ProxyLite user id"),
    proxyrack: () => add("proxyrack_api_key", pick([headerLike("api-key"), storeMatch(/api.*key|token/i), jsonStoreMatch(/api.*key|token/i)]), "ProxyRack API key"),
    repocket: () => {
      add("repocket_email", pick([inputValue("email"), storeMatch(/email/i), textMatch(/email[:\s]+([^\s@]+@[^\s]+)/i, 1)]), "Repocket email");
      add("repocket_api_key", pick([storeMatch(/api.*key|token/i), jsonStoreMatch(/api.*key|token/i)]), "Repocket API key");
    },
    spide: () => add("spide_dashboard_token", pick([cookie, storeMatch(/token|jwt|session/i), jsonStoreMatch(/token|jwt|session/i)]), "Spide dashboard token"),
    urnetwork: () => {
      add("urnetwork_auth_token", pick([storeMatch(/auth.*token|access.*token|jwt/i), jsonStoreMatch(/auth.*token|access.*token|jwt/i)]), "URnetwork auth token");
      add("urnetwork_api_key", pick([storeMatch(/api.*key|apikey/i), jsonStoreMatch(/api.*key|apikey/i)]), "URnetwork API key");
    },
    mysterium: () => {
      add("mysterium_dashboard_password", pick([storeMatch(/password/i), inputValue("password")]), "MYST dashboard password");
      add("mysterium_mmn_api_key", pick([storeMatch(/mmn.*key|api.*key|token/i), jsonStoreMatch(/mmn.*key|api.*key|token/i)]), "MYST MMN key");
    },
  };

  if (readers[slug]) readers[slug]();
  return {
    slug,
    url: href,
    data,
    notes,
    reason: slug ? (Object.keys(data).length ? "Imported readable values from this provider tab." : "Known provider, but no readable configured values were exposed on this page.") : `Unsupported provider host: ${host}`,
  };

  function detectSlug(hostname, url, pageText) {
    if (hostname.includes("app.grass.io")) return "grass";
    if (hostname.includes("uprock.com")) return "uprock";
    if (hostname.includes("wipter.com")) return "wipter";
    if (hostname.includes("traffmonetizer.com")) return "traffmonetizer";
    if (hostname.includes("app.packetstream.io") || hostname.includes("packetstream.io")) return "packetstream";
    if (hostname.includes("app.bitping.com") || hostname.includes("nodes.bitping.com")) return "bitping";
    if (hostname.includes("earnapp.com")) return "earnapp";
    if (hostname.includes("app.earn.fm")) return "earnfm";
    if (hostname.includes("pawns.app") || hostname.includes("dashboard.pawns.app")) return "iproyal";
    if (hostname.includes("peer.proxyrack.com")) return "proxyrack";
    if (hostname.includes("repocket.com")) return "repocket";
    if (hostname.includes("spide.network")) return "spide";
    if (hostname.includes("ur.network")) return "urnetwork";
    if (hostname.includes("peer.proxybase.org")) return "proxybase";
    if (hostname.includes("proxybase.xyz")) return "proxybase-xyz";
    if (hostname.includes("lk.proxylite.ru")) return "proxylite";
    if (hostname.includes("proxies.sx") || hostname.includes("farmer.proxies.sx")) return "proxies_sx";
    if (/myst/i.test(pageText) || hostname.includes("my.mystnodes.com")) return "mysterium";
    return "";
  }

  function snapshot(store) {
    const out = {};
    try {
      for (let i = 0; i < store.length; i += 1) {
        const key = store.key(i);
        if (key) out[key] = store.getItem(key) || "";
      }
    } catch (_) {}
    return out;
  }

  function scanJsonStores(obj) {
    const out = {};
    for (const [key, value] of Object.entries(obj)) {
      if (!value) continue;
      const trimmed = String(value).trim();
      if (!(trimmed.startsWith("{") || trimmed.startsWith("["))) continue;
      try { out[key] = JSON.parse(trimmed); } catch (_) {}
    }
    return out;
  }

  function add(key, value, note) {
    const val = String(value || "").trim();
    if (!key || !val) return;
    data[key] = val;
    if (note) notes.push(note);
  }

  function pick(values) {
    for (const value of values) {
      const val = String(value || "").trim();
      if (val) return val;
    }
    return "";
  }

  function storeMatch(pattern) {
    const re = pattern instanceof RegExp ? pattern : new RegExp(pattern, "i");
    for (const [key, value] of Object.entries(stores)) {
      if (re.test(key) && value) return value;
    }
    return "";
  }

  function jsonStoreMatch(pattern) {
    const re = pattern instanceof RegExp ? pattern : new RegExp(pattern, "i");
    for (const value of Object.values(jsonStores)) {
      const hit = walkJson(value, re);
      if (hit) return hit;
    }
    return "";
  }

  function walkJson(value, re) {
    if (!value || typeof value !== "object") return "";
    if (Array.isArray(value)) {
      for (const item of value) {
        const hit = walkJson(item, re);
        if (hit) return hit;
      }
      return "";
    }
    for (const [key, item] of Object.entries(value)) {
      if (re.test(key) && typeof item !== "object" && item != null) return String(item);
      const hit = walkJson(item, re);
      if (hit) return hit;
    }
    return "";
  }

  function jsonMatch(keys) {
    for (const obj of Object.values(jsonStores)) {
      const hit = lookup(obj, keys);
      if (hit) return hit;
    }
    return "";
  }

  function lookup(obj, keys) {
    if (!obj || typeof obj !== "object") return "";
    if (Array.isArray(obj)) {
      for (const item of obj) {
        const hit = lookup(item, keys);
        if (hit) return hit;
      }
      return "";
    }
    for (const key of keys) {
      if (Object.prototype.hasOwnProperty.call(obj, key) && obj[key] != null && typeof obj[key] !== "object") return String(obj[key]);
    }
    for (const value of Object.values(obj)) {
      const hit = lookup(value, keys);
      if (hit) return hit;
    }
    return "";
  }

  function cookieValue(name) {
    const match = cookie.match(new RegExp(`(?:^|;\\s*)${name.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\\\$&")}=([^;]+)`));
    return match ? decodeURIComponent(match[1]) : "";
  }

  function queryValue(name) {
    try {
      return new URL(href).searchParams.get(name) || "";
    } catch (_) {
      return "";
    }
  }

  function textMatch(regex, group = 1) {
    const match = text.match(regex);
    return match ? match[group] : "";
  }

  function inputValue(name) {
    const el = document.querySelector(`input[name="${cssEscape(name)}"], input[id="${cssEscape(name)}"], input[aria-label*="${cssEscape(name)}" i]`);
    return el && "value" in el ? el.value : "";
  }

  function headerLike(name) {
    const rx = new RegExp(`${name.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\\\$&")}[:=]\\s*([^\\s]+)`, "i");
    const hit = text.match(rx);
    return hit ? hit[1] : "";
  }

  function cssEscape(value) {
    return String(value).replace(/["\\\\]/g, "\\\\$&");
  }
})();
