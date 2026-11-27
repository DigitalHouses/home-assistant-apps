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
    ? new Date(newest.first_seen).toLocaleString("en-GB", {
        timeZone: "Asia/Almaty", day: "2-digit", month: "short",
        year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false
      }).replace(",", " ·") + " (Almaty)"
    : "—";

  if (!rows.length) {
    body.innerHTML = '<tr><td class="empty" colspan="2">No data</td></tr>';
  }

  for (const country of rows) {
    const count = Number(country.observed_installations) || 0;
    total += count;
    body.insertAdjacentHTML("beforeend",
      '<tr class="country-summary-row"><td class="country-name">' +
      escapeHtml(countryName(country.country)) + '</td><td>' + count + '</td></tr>');

    for (const product of country.products || []) {
      body.insertAdjacentHTML("beforeend",
        '<tr class="country-product-row"><td class="country-product-name">' +
        escapeHtml(product.name || product.product) + '</td><td>' +
        (Number(product.observed_installations) || 0) + '</td></tr>');
    }
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
    exact: date.toLocaleString()
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

async function load() {
  setStatus(true, "Loading");
  $("refresh").disabled = true;

  try {
    const [summary, versions, countries, history] = await Promise.all([
      getJson("/api/summary"),
      getJson("/api/versions"),
      getJson("/api/countries"),
      getJson("/api/installation-history?days=7")
    ]);

    $("known").textContent = summary.observed_installations;
    $("active24").textContent = summary.active_24h;
    $("active7").textContent = summary.active_7d;
    $("active30").textContent = summary.active_30d;
    $("heartbeats").textContent = summary.heartbeats;

    const lastHeartbeat = formatLastHeartbeat(summary.last_heartbeat);
    $("last-heartbeat").textContent = lastHeartbeat.relative;
    $("last-heartbeat-exact").textContent = lastHeartbeat.exact;

    tableRows("versions", versions, (r) =>
      '<tr><td class="product">' + (r.name || r.product) + '</td><td>' + r.version +
      '</td><td>' + r.observed_installations + '</td><td>' + r.active_7d + '</td></tr>', 4);

    renderCountries(countries);

    renderChart(history);
    $("updated").textContent = "Updated " + new Date().toLocaleString();
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
