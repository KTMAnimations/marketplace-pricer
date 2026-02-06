/* eslint-disable no-console */

const $ = (id) => document.getElementById(id);

const state = {
  items: [],
  filtered: [],
  meta: null,
  watchlists: [],
  lastFetch: null,
};

function moneyFromCents(cents) {
  if (cents === null || cents === undefined) return "—";
  const abs = Math.abs(Number(cents));
  const sign = Number(cents) < 0 ? "-" : "";
  const dollars = Math.floor(abs / 100);
  const remainder = abs % 100;
  return `${sign}$${dollars.toLocaleString()}.${String(remainder).padStart(2, "0")}`;
}

function ago(iso) {
  if (!iso) return "—";
  const t = new Date(iso);
  if (Number.isNaN(t.getTime())) return iso;
  const delta = Date.now() - t.getTime();
  const mins = Math.floor(delta / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function safeText(s) {
  if (s === null || s === undefined) return "";
  return String(s);
}

function normalizeForSearch(s) {
  return safeText(s).toLowerCase();
}

function toast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.hidden = false;
  window.clearTimeout(toast._t);
  toast._t = window.setTimeout(() => {
    el.hidden = true;
  }, 1800);
}

function parseMoneyInput(raw) {
  if (!raw) return null;
  const s = String(raw).trim().replace(/[^0-9.-]/g, "");
  if (!s) return null;
  const n = Number(s);
  if (!Number.isFinite(n)) return null;
  return Math.round(n * 100);
}

function parsePctInput(raw) {
  if (!raw) return null;
  const s = String(raw).trim().replace(/[^0-9.]/g, "");
  if (!s) return null;
  const n = Number(s);
  if (!Number.isFinite(n)) return null;
  return n;
}

function buildEbayUrl(title) {
  const q = safeText(title).trim();
  if (!q) return "https://www.ebay.com/";
  const params = new URLSearchParams({ _nkw: q });
  return `https://www.ebay.com/sch/i.html?${params.toString()}`;
}

function computeStats(items) {
  const deals = items.filter((it) => it.spread_cents !== null && it.spread_cents > 0);
  const saved = items.filter((it) => it.status === "saved");
  const dismissed = items.filter((it) => it.status === "dismissed");
  return { deals: deals.length, saved: saved.length, dismissed: dismissed.length };
}

function applyFilters() {
  const q = normalizeForSearch($("q").value);
  const status = $("status").value;
  const source = $("source").value;
  const watchlist = $("watchlist").value;
  const minSpread = parseMoneyInput($("minSpread").value);
  const maxPct = parsePctInput($("maxPct").value);
  const onlyDeals = $("onlyDeals").checked;
  const onlyAlerted = $("onlyAlerted").checked;
  const includeUnpriced = $("includeUnpriced").checked;

  let items = state.items.slice();

  if (status !== "any") {
    items = items.filter((it) => it.status === status);
  }
  if (source !== "any") {
    items = items.filter((it) => it.source === source);
  }
  if (watchlist !== "any") {
    const wlId = Number(watchlist);
    items = items.filter((it) => it.watchlist_id === wlId);
  }
  if (onlyAlerted) {
    items = items.filter((it) => Number(it.alerts_count || 0) > 0);
  }

  items = items.filter((it) => {
    const priced = it.price_cents !== null && it.market_price_cents !== null;
    if (!includeUnpriced && !priced) return false;
    if (onlyDeals) {
      if (!priced) return false;
      if (Number(it.spread_cents || 0) <= 0) return false;
    }
    if (minSpread !== null) {
      if (it.spread_cents === null) return false;
      if (Number(it.spread_cents) < minSpread) return false;
    }
    if (maxPct !== null) {
      if (it.pct_of_market === null) return false;
      const pct = Number(it.pct_of_market) * 100;
      if (pct > maxPct) return false;
    }
    if (q) {
      const hay = [
        it.title,
        it.description,
        it.location,
        it.source,
        it.watchlist_name,
        it.unique_key,
        it.url,
      ]
        .map(normalizeForSearch)
        .join(" ");
      return hay.includes(q);
    }
    return true;
  });

  const sort = $("sort").value;
  const cmp = {
    last_seen_desc: (a, b) => String(b.last_seen_at).localeCompare(String(a.last_seen_at)),
    spread_desc: (a, b) => Number(b.spread_cents || -Infinity) - Number(a.spread_cents || -Infinity),
    discount_desc: (a, b) => Number(b.discount_pct || -Infinity) - Number(a.discount_pct || -Infinity),
    price_asc: (a, b) => Number(a.price_cents || Infinity) - Number(b.price_cents || Infinity),
  }[sort];
  if (cmp) items.sort(cmp);

  state.filtered = items;
}

function render() {
  const cards = $("cards");
  cards.textContent = "";

  const { deals, saved, dismissed } = computeStats(state.items);
  $("statDeals").textContent = String(deals);
  $("statSaved").textContent = String(saved);
  $("statDismissed").textContent = String(dismissed);

  const empty = $("empty");
  const error = $("error");
  error.hidden = true;

  if (!state.filtered.length) {
    empty.hidden = false;
    return;
  }
  empty.hidden = true;

  const tpl = $("cardTpl");
  for (const it of state.filtered) {
    const node = tpl.content.firstElementChild.cloneNode(true);

    node.querySelector('[data-role="source"]').textContent = safeText(it.source);
    const wlBadge = node.querySelector('[data-role="watchlist"]');
    if (it.watchlist_name) {
      wlBadge.hidden = false;
      wlBadge.textContent = safeText(it.watchlist_name);
    }

    const alerted = node.querySelector('[data-role="alerted"]');
    if (Number(it.alerts_count || 0) > 0) alerted.hidden = false;

    node.querySelector('[data-role="lastSeen"]').textContent = `seen ${ago(it.last_seen_at)}`;
    node.querySelector('[data-role="title"]').textContent = safeText(it.title || "(no title)");

    const desc = node.querySelector('[data-role="desc"]');
    const descText = it.description || "";
    desc.textContent = descText ? safeText(descText) : "—";

    const loc = node.querySelector('[data-role="location"]');
    const locText = it.location || it.seller || "Unknown location";
    loc.textContent = safeText(locText);

    node.querySelector('[data-role="key"]').textContent = safeText(it.unique_key);

    const price = it.price || moneyFromCents(it.price_cents);
    const market = it.market_price || moneyFromCents(it.market_price_cents);
    node.querySelector('[data-role="price"]').textContent = price;
    node.querySelector('[data-role="market"]').textContent = market;

    const spreadEl = node.querySelector('[data-role="spread"]');
    const spreadCents = it.spread_cents;
    spreadEl.textContent = it.spread || moneyFromCents(spreadCents);

    const discountEl = node.querySelector('[data-role="discount"]');
    if (it.discount_pct !== null && it.discount_pct !== undefined) {
      discountEl.textContent = `${Math.round(Number(it.discount_pct))}% under`;
    } else {
      discountEl.textContent = "";
    }

    const metricSpread = node.querySelector(".metricSpread .metricValue");
    if (spreadCents === null || spreadCents === undefined) {
      metricSpread.style.color = "rgba(148,163,184,0.82)";
    } else if (Number(spreadCents) > 0) {
      metricSpread.style.color = "rgb(34,197,94)";
    } else if (Number(spreadCents) < 0) {
      metricSpread.style.color = "rgb(251,113,133)";
    } else {
      metricSpread.style.color = "rgba(226,232,240,0.86)";
    }

    const open = node.querySelector('[data-role="open"]');
    open.href = safeText(it.url);

    const ebay = node.querySelector('[data-role="ebay"]');
    ebay.href = buildEbayUrl(it.title);

    const copy = node.querySelector('[data-role="copy"]');
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(safeText(it.url));
        toast("Link copied");
      } catch (err) {
        console.warn("clipboard failed", err);
        toast("Copy failed");
      }
    });

    const save = node.querySelector('[data-role="save"]');
    const isSaved = it.status === "saved";
    save.textContent = isSaved ? "Unsave" : "Save";
    save.addEventListener("click", async () => {
      await setStatus(it.unique_key, isSaved ? "active" : "saved");
    });

    const dismiss = node.querySelector('[data-role="dismiss"]');
    const isDismissed = it.status === "dismissed";
    dismiss.textContent = isDismissed ? "Restore" : "Dismiss";
    dismiss.addEventListener("click", async () => {
      await setStatus(it.unique_key, isDismissed ? "active" : "dismissed");
    });

    const img = node.querySelector(".thumbImg");
    const fallback = node.querySelector(".thumbFallback");
    if (it.image_url) {
      img.src = safeText(it.image_url);
      img.alt = safeText(it.title || "Listing image");
      img.addEventListener(
        "load",
        () => {
          img.style.display = "block";
          fallback.style.display = "none";
        },
        { once: true }
      );
      img.addEventListener(
        "error",
        () => {
          img.style.display = "none";
          fallback.style.display = "block";
        },
        { once: true }
      );
    }

    cards.appendChild(node);
  }
}

async function setStatus(uniqueKey, status) {
  try {
    const res = await fetch(`/api/listings/${encodeURIComponent(uniqueKey)}/status`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || `HTTP ${res.status}`);
    }
    const item = state.items.find((it) => it.unique_key === uniqueKey);
    if (item) item.status = status;
    applyFilters();
    render();
    toast(`Marked ${status}`);
  } catch (err) {
    console.error(err);
    toast("Update failed");
  }
}

async function fetchAll() {
  $("error").hidden = true;
  $("empty").hidden = true;
  $("cards").innerHTML = `<div class="empty"><h2>Loading…</h2><p>Pulling mispricings from your local DB.</p></div>`;

  const params = new URLSearchParams({
    // Fetch broadly, then filter client-side for a snappy UI.
    status: "any",
    only_deals: "false",
    include_unpriced: "true",
    limit: "1000",
  });

  try {
    const [metaRes, watchRes, dataRes] = await Promise.all([
      fetch("/api/meta"),
      fetch("/api/watchlists"),
      fetch(`/api/mispricings?${params.toString()}`),
    ]);

    state.meta = await metaRes.json();
    const watchlists = await watchRes.json();
    state.watchlists = watchlists.watchlists || [];
    const data = await dataRes.json();
    state.items = data.items || [];
    state.lastFetch = new Date();

    hydrateOptions();
    $("hintDb").textContent = state.meta?.sqlite_path ? `DB: ${state.meta.sqlite_path}` : "";

    applyFilters();
    render();
  } catch (err) {
    console.error(err);
    $("cards").textContent = "";
    $("error").hidden = false;
    $("errorMessage").textContent = safeText(err?.message || err);
  }
}

function hydrateOptions() {
  const sources = new Set(state.items.map((it) => it.source).filter(Boolean));
  const sourceSel = $("source");
  const existingSource = new Set([...sourceSel.options].map((o) => o.value));
  for (const s of sources) {
    if (existingSource.has(s)) continue;
    const opt = document.createElement("option");
    opt.value = s;
    opt.textContent = s;
    sourceSel.appendChild(opt);
  }

  const wlSel = $("watchlist");
  wlSel.textContent = "";
  const anyOpt = document.createElement("option");
  anyOpt.value = "any";
  anyOpt.textContent = "Any";
  wlSel.appendChild(anyOpt);

  for (const w of state.watchlists) {
    const opt = document.createElement("option");
    opt.value = String(w.id);
    opt.textContent = w.active ? w.name : `${w.name} (inactive)`;
    wlSel.appendChild(opt);
  }
}

function wire() {
  const inputs = ["q", "status", "source", "watchlist", "minSpread", "maxPct", "sort", "onlyDeals", "onlyAlerted", "includeUnpriced"];
  for (const id of inputs) {
    const el = $(id);
    el.addEventListener("input", () => {
      applyFilters();
      render();
    });
    el.addEventListener("change", () => {
      applyFilters();
      render();
    });
  }

  $("btnRefresh").addEventListener("click", async () => {
    await fetchAll();
    toast("Refreshed");
  });
}

wire();
fetchAll();
