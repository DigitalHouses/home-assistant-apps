const $ = (id) => document.getElementById(id);

const productNames = {
  digitalhouses_pve_agent: "PVE Agent",
  digitalhouses_plex_agent: "Plex Agent",
  digitalhouses_recorder_app: "Recorder App",
  digitalhouses_speedtest_app: "Internet App"
};

function productName(value) {
  return productNames[value] || value;
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

function renderChart(points) {
  const chart = $("chart");
  chart.innerHTML = "";
  const max = Math.max(1, ...points.map((p) => p.active_installations));
  for (const point of points) {
    const percent = Math.max(point.active_installations ? 3 : 1, (point.active_installations / max) * 100);
    const wrap = document.createElement("div");
    wrap.className = "bar-wrap";
    wrap.style.setProperty("--h", percent + "%");
    wrap.dataset.label = point.day + " · " + point.active_installations + " active · " + point.heartbeats + " heartbeats";
    const bar = document.createElement("div");
    bar.className = "bar";
    bar.style.height = percent + "%";
    wrap.appendChild(bar);
    chart.appendChild(wrap);
  }
}

async function load() {
  setStatus(true, "Loading");
  $("refresh").disabled = true;
  try {
    const days = Number($("history-days").value);
    const [summary, products, versions, countries, history] = await Promise.all([
      getJson("/api/summary"),
      getJson("/api/products"),
      getJson("/api/versions"),
      getJson("/api/countries"),
      getJson("/api/history?days=" + days)
    ]);

    $("known").textContent = summary.observed_installations;
    $("active24").textContent = summary.active_24h;
    $("active7").textContent = summary.active_7d;
    $("active30").textContent = summary.active_30d;

    tableRows("products", products, (r) =>
      '<tr><td class="product">' + productName(r.product) + '</td><td>' + r.observed_installations +
      '</td><td>' + r.active_24h + '</td><td>' + r.active_7d + '</td><td>' + r.active_30d + '</td></tr>', 5);

    tableRows("versions", versions, (r) =>
      '<tr><td class="product">' + productName(r.product) + '</td><td>' + r.version +
      '</td><td>' + r.observed_installations + '</td><td>' + r.active_7d + '</td></tr>', 4);

    tableRows("countries", countries, (r) =>
      '<tr><td class="product">' + r.country + '</td><td>' + r.observed_installations +
      '</td><td>' + r.active_7d + '</td><td>' + r.active_30d + '</td></tr>', 4);

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
$("history-days").addEventListener("change", load);
load();
