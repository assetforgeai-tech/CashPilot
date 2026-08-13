window.__cashpilotSaveImportedProviderConfig = async payload => {
  try {
    const data = payload?.data || {};
    if (!Object.keys(data).length) return { status: "empty" };
    const resp = await fetch("/api/config", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ data }),
    });
    if (!resp.ok) {
      const detail = await resp.text().catch(() => "");
      return { status: "error", error: `${resp.status} ${detail}`.trim() };
    }
    return { status: "saved" };
  } catch (err) {
    return { status: "error", error: err?.message || String(err) };
  }
};
