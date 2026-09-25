const $ = (id) => document.getElementById(id);

const productNames = {
  digitalhouses_pve_agent: "PVE Agent",
  digitalhouses_plex_agent: "Plex Agent",
  digitalhouses_recorder_app: "Recorder App",
  digitalhouses_speedtest_app: "Speedtest App",
  digitalhouses_internet_app: "Internet App"
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

  const totalHeartbeats = points.reduce((sum, point) => sum + point.heartbeats, 0);
  const activeDays = points.filter((point) => point.active_installations > 0).length;
  const peakActive = Math.max(0, ...points.map((point) => point.active_installations));
  const maxValue = Math.max(
    1,
    ...points.map((point) => Math.max(point.active_installations, point.heartbeats))
  );
  const labelEvery = Math.max(1, Math.ceil(points.length / 8));

  $("period-heartbeats").textContent = totalHeartbeats;
  $("period-active-days").textContent = activeDays;
  $("period-peak").textContent = peakActive;

  points.forEach((point, index) => {
    const activePercent = (point.active_installations / maxValue) * 100;
    const heartbeatPercent = (point.heartbeats / maxValue) * 100;

    const day = document.createElement("div");
    day.className = "day-wrap";
    day.title =
      point.day +
      " · " +
      point.active_installations +
      " active · " +
      point.heartbeats +
      " heartbeats";

    const bars = document.createElement("div");
    bars.className = "bars";

    const active = document.createElement("div");
    active.className = "bar active-bar";
    active.style.height = Math.max(point.active_installations ? 3 : 1, activePercent) + "%";

    const heartbeats = document.createElement("div");
    heartbeats.className = "bar heartbeat-bar";
    heartbeats.style.height = Math.max(point.heartbeats ? 3 : 1, heartbeatPercent) + "%";

    bars.appendChild(active);
    bars.appendChild(heartbeats);
    day.appendChild(bars);

    const label = document.createElement("span");
    label.className = "day-label";
    if (
      index === 0 ||
      index === points.length - 1 ||
      index % labelEvery === 0
    ) {
      label.textContent = dayLabel(point.day);
    }
    day.appendChild(label);

    chart.appendChild(day);
  });
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
    $("heartbeats").textContent = summary.heartbeats;

    const lastHeartbeat = formatLastHeartbeat(summary.last_heartbeat);
    $("last-heartbeat").textContent = lastHeartbeat.relative;
    $("last-heartbeat-exact").textContent = lastHeartbeat.exact;

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
