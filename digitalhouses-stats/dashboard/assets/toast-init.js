"use strict";
DHJournalToast.mount({
  product: "digitalhouses_stats",
  endpoint: "./api/log/toasts",
  language: "en",
  onEvents: () => load(),
  settingsTarget: document.getElementById("toast-settings")
});
