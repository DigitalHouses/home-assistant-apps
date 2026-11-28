"use strict";
const button = document.getElementById("sync");
const statusNode = document.getElementById("status");
const requestError = document.getElementById("request_error");
const rendered = new Map();
let timer, loading = false, starting = false, busy = !!button?.disabled, generation = 0;
function schedule() {
  clearTimeout(timer);
  if (!document.hidden) timer = setTimeout(refresh, busy ? 1500 : 10000);
}
function showError(message) {
  const p = document.createElement("strong");
  p.className = "error";
  p.textContent = message;
  statusNode.replaceChildren(p);
}
function setBusy(value) {
  busy = value;
  if (button) {
    button.disabled = value || starting;
    button.textContent = value || starting ? "⟳ Выполняется проверка…" : "⟳ Проверить и обновить";
  }
}
async function refresh() {
  if (loading || starting || document.hidden) { schedule(); return; }
  loading = true;
  const requestGeneration = generation;
  try {
    const response = await fetch("./api/sync/status", {cache:"no-store"});
    if (!response.ok) throw Error("status");
    const data = await response.json();
    if (starting || requestGeneration !== generation) return;
    for (const [id, html] of Object.entries(data.fragments)) {
      const node = document.getElementById(id);
      // Fragments originate only from escaped server-rendered HTML.
      if (node && rendered.get(id) !== html) { node.innerHTML = html; rendered.set(id, html); }
    }
    if (data.running) requestError.textContent = "";
    setBusy(data.running);
  } catch (_) {
    if (requestGeneration !== generation) return;
    rendered.delete("status");
    showError("Не удалось получить статус DH Sync. Проверка состояния повторится автоматически.");
  } finally { loading = false; schedule(); }
}
if (button) button.addEventListener("click", async () => {
  if (busy || starting) return;
  starting = true;
  generation++;
  rendered.delete("status");
  requestError.textContent = "";
  clearTimeout(timer);
  setBusy(true);
  const p = document.createElement("strong");
  p.textContent = "⟳ Выполняется проверка GitHub…";
  statusNode.replaceChildren(p);
  try {
    const response = await fetch("./api/sync", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify({token:button.dataset.token})
    });
    if (!response.ok && response.status !== 409) throw Error("sync");
  } catch (_) {
    requestError.textContent = "Не удалось подтвердить запуск проверки. Уточняем состояние…";
  } finally {
    starting = false;
    await refresh();
  }
});
document.addEventListener("visibilitychange", () => {
  clearTimeout(timer);
  if (!document.hidden) refresh();
});
refresh();
