const $ = (id) => document.getElementById(id);

// Browser-provided ISO 3166 region names, always in English.
const countryNames = typeof Intl.DisplayNames === "function"
  ? new Intl.DisplayNames(["en"], { type: "region" }) : null;

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[char]);
}

async function getJson(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) throw new Error(path + " returned HTTP " + response.status);
  return response.json();
}

function setStatus(ok, message) {
  $("status-dot").className = "dot " + (ok ? "ok" : "error");
  $("status-text").textContent = message;
}

function tableRows(target, rows, render, colspan) {
  const body = $(target);
  body.innerHTML = "";
  if (!rows.length) {
    body.innerHTML = '<tr><td class="empty" colspan="' + colspan + '">No data</td></tr>';
    return;
  }
  for (const row of rows) body.insertAdjacentHTML("beforeend", render(row));
}

function countryName(code) {
  if (!code || ["XX", "ZZ"].includes(String(code).toUpperCase())) return "Unknown";
  try {
    return countryNames?.of(String(code).toUpperCase()) || String(code);
  } catch {
    return String(code);
  }
}

// Numeric version ordering, newest first (e.g. 0.5.107 before 0.5.96).
const versionOrder = new Intl.Collator("en", {numeric:true, sensitivity:"base"});
function compareVersions(a,b) {
  return versionOrder.compare(String(b.version), String(a.version));
}

const expandedCountries = new Set();
let siteTimezone = "UTC", timezoneFallback = true;

function formatSiteTime(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    timeZone:siteTimezone, day:"2-digit", month:"short", year:"numeric",
    hour:"2-digit", minute:"2-digit", second:"2-digit", hourCycle:"h23"
  }).format(new Date(value));
}
function timezoneLabel() {
  return siteTimezone + (timezoneFallback ? " (temporary: HA timezone unavailable)" : "");
}
function updateTimezone(data) {
  const changed = siteTimezone !== data.timezone || timezoneFallback !== Boolean(data.timezone_fallback);
  if (typeof data.timezone !== "string") return false;
  siteTimezone = data.timezone;
  timezoneFallback = Boolean(data.timezone_fallback);
  $("timezone").textContent = timezoneLabel();
  return changed;
}
const countryPalette = ["#699bd4", "#50bba7", "#e0ae72", "#a58bd4", "#d67f91", "#80c6e1", "#9ebc76", "#a0a8bd", "#7889a0"];

function renderCountryChart(rows) {
  const entries = rows.map(r => ({name: countryName(r.country), count: Math.max(0, Number(r.observed_installations) || 0)}))
    .filter(r => r.count > 0).sort((a,b) => b.count-a.count || a.name.localeCompare(b.name));
  const total = entries.reduce((sum,r) => sum+r.count, 0);
  const visible = entries.slice(0,8);
  if (entries.length > 8) visible.push({name:"Other", count:entries.slice(8).reduce((sum,r)=>sum+r.count,0)});
  const donut = $("country-donut"), legend = $("country-legend");
  $("donut-total").textContent = total;
  legend.replaceChildren();
  let start = 0;
  const stops = visible.map((r,i) => {
    const end = start + r.count / total * 100;
    const color = countryPalette[i];
    const stop = color + " " + start + "% " + end + "%";
    start = end;
    const line = document.createElement("div");
    line.className = "legend-row";
    const swatch = document.createElement("i");
    swatch.style.background = color;
    const name = document.createElement("span");
    name.textContent = r.name;
    name.title = r.name;
    const count = document.createElement("strong");
    count.textContent = r.count;
    const pct = document.createElement("small");
    pct.textContent = (r.count / total * 100).toFixed(1) + "%";
    line.append(swatch,name,count,pct);
    legend.append(line);
    return stop;
  });
  donut.style.background = stops.length ? "conic-gradient(" + stops.join(",") + ")" : "var(--border)";
  donut.setAttribute("aria-label", total ? visible.map(r=>r.name+": "+r.count+" installations").join("; ") : "No country data");
  if (!total) legend.textContent = "No data";
}

function renderCountries(rows) {
  const body = $("countries");
  body.innerHTML = "";
  let total = 0;

  $("country-count").textContent = rows.length;
  const newest = rows
    .filter((row) => row.first_seen)
    .reduce((latest, row) =>
      !latest || new Date(row.first_seen) > new Date(latest.first_seen) ? row : latest,
      null);
  $("country-newest-name").textContent = newest ? countryName(newest.country) : "—";
  $("country-newest-first-seen").textContent = newest
    ? formatSiteTime(newest.first_seen)
    : "—";

  if (!rows.length) {
    body.innerHTML = '<tr><td class="empty" colspan="2">No data</td></tr>';
  }

  for (const country of rows) {
    const count = Number(country.observed_installations) || 0;
    const key = String(country.country || "XX");
    total += count;
    const group = document.createElement("tr");
    group.className = "country-summary-row";
    const nameCell = group.insertCell();
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "country-toggle";
    toggle.textContent = countryName(country.country);
    const products = country.products || [];
    toggle.disabled = !products.length;
    nameCell.append(toggle);
    group.insertCell().textContent = count;
    body.append(group);
    const details = products.map(product => {
      const tr = document.createElement("tr");
      tr.className = "country-product-row";
      const name = tr.insertCell();
      name.className = "country-product-name";
      name.textContent = product.name || product.product;
      tr.insertCell().textContent = Number(product.observed_installations) || 0;
      body.append(tr);
      return tr;
    });
    function update() {
      const open = expandedCountries.has(key);
      toggle.setAttribute("aria-expanded", String(open));
      for (const tr of details) tr.hidden = !open;
    }
    toggle.addEventListener("click", () => {
      if (expandedCountries.has(key)) expandedCountries.delete(key);
      else expandedCountries.add(key);
      update();
    });
    update();
  }

  $("country-total").textContent = total;
}

function formatLastHeartbeat(value) {
  if (!value) {
    return { relative: "—", exact: "No data" };
  }

  const date = new Date(value);
  const deltaSeconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));

  let relative;
  if (deltaSeconds < 60) {
    relative = "just now";
  } else if (deltaSeconds < 3600) {
    relative = Math.floor(deltaSeconds / 60) + " min ago";
  } else if (deltaSeconds < 86400) {
    relative = Math.floor(deltaSeconds / 3600) + " h ago";
  } else {
    relative = Math.floor(deltaSeconds / 86400) + " d ago";
  }

  return {
    relative,
    exact: formatSiteTime(date)
  };
}

function dayLabel(day) {
  return new Date(day + "T00:00:00Z").toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
    timeZone: "UTC"
  });
}

function renderChart(points) {
  const chart = $("chart");
  chart.innerHTML = "";

  if (!points.length) {
    chart.textContent = "No data";
    return;
  }

  const maxTotal = Math.max(1, ...points.map((p) => Number(p.total_installations) || 0));
  for (const point of points) {
    const total = Number(point.total_installations) || 0;
    const active = Math.min(total, Number(point.active_installations) || 0);
    const inactive = Math.max(0, total - active);

    const day = document.createElement("div");
    day.className = "day-wrap";
    day.title = point.day + " · Total: " + total + " · Inactive: " + inactive;
    day.setAttribute("aria-label", day.title);
    day.setAttribute("tabindex", "0");

    const bars = document.createElement("div");
    bars.className = "bars comparison-bars";

    for (const [kind, count] of [["total", total], ["inactive", inactive]]) {
      const column = document.createElement("div");
      column.className = "comparison-column " + kind + "-column";
      column.style.height = (count / maxTotal * 100) + "%";

      const value = document.createElement("span");
      value.className = "bar-value";
      value.textContent = String(count);
      column.appendChild(value);
      bars.appendChild(column);
    }

    day.appendChild(bars);

    const label = document.createElement("span");
    label.className = "day-label";
    label.textContent = dayLabel(point.day);
    day.appendChild(label);
    chart.appendChild(day);
  }
}

// Manual and event-driven refresh share one queue. A batch received during
// a request schedules one follow-up, never overlapping requests.
let refreshRunning = false;
let refreshQueued = false;
async function load() {
  if (refreshRunning) {
    refreshQueued = true;
    return;
  }
  refreshRunning = true;
  try {
    do {
      refreshQueued = false;
      await loadData();
    } while (refreshQueued);
  } finally {
    refreshRunning = false;
  }
}

async function loadData() {
  setStatus(true, "Loading");
  $("refresh").disabled = true;

  try {
    const [summary, versions, countries, history] = await Promise.all([
      getJson("/api/summary"),
      getJson("/api/versions"),
      getJson("/api/countries"),
      getJson("/api/installation-history?days=7")
    ]);

    // Capture immediately before updating, not before the asynchronous requests.
    const scrollX = window.scrollX, scrollY = window.scrollY;
    updateTimezone(summary);
    $("known").textContent = summary.observed_installations;
    $("active24").textContent = summary.active_24h;
    $("active7").textContent = summary.active_7d;
    $("active30").textContent = summary.active_30d;
    $("heartbeats").textContent = summary.heartbeats;

    const lastHeartbeat = formatLastHeartbeat(summary.last_heartbeat);
    $("last-heartbeat").textContent = lastHeartbeat.relative;
    $("last-heartbeat-exact").textContent = lastHeartbeat.exact;

    const grouped = new Map();
    for (const r of versions) {
      const key = r.product || r.name;
      if (!grouped.has(key)) grouped.set(key, []);
      grouped.get(key).push(r);
    }
    tableRows("versions", Array.from(grouped.values()).flatMap(group =>
      group.sort(compareVersions).map((r,i) => ({...r, first:i===0}))), r =>
      '<tr><td class="product">' + (r.first ? escapeHtml(r.name || r.product) : "") +
      '</td><td>' + escapeHtml(r.version) + '</td><td>' + escapeHtml(r.observed_installations) +
      '</td><td>' + escapeHtml(r.active_7d) + '</td></tr>', 4);

    renderCountries(countries);
    renderCountryChart(countries);

    renderChart(history);
    if (window.scrollX !== scrollX || window.scrollY !== scrollY) {
      window.scrollTo({left: scrollX, top: scrollY, behavior: "instant"});
    }
    $("updated").textContent = "Updated " + formatSiteTime(new Date());
    setStatus(true, "Online");
  } catch (error) {
    console.error(error);
    setStatus(false, "Unavailable");
    $("updated").textContent = error.message;
  } finally {
    $("refresh").disabled = false;
  }
}

$("refresh").addEventListener("click", load);
load();
