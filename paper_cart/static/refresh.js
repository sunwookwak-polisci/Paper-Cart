(() => {
  const button = document.querySelector("[data-update-button]");
  const list = document.querySelector("[data-paper-list]");

  async function poll() {
    let refreshing = true;
    try {
      const response = await fetch("/refresh/status", { cache: "no-store" });
      if (response.ok) refreshing = Boolean((await response.json()).refreshing);
    } catch {
      // Keep waiting; the server may be busy.
    }
    if (refreshing) {
      window.setTimeout(poll, 2000);
      return;
    }
    finished();
  }

  function finished() {
    if (button instanceof HTMLButtonElement) {
      button.disabled = false;
      button.textContent = "Update";
    }
    if (!list) return;
    const picked = document.querySelector("[data-bulk-pick]:checked");
    if (!picked) {
      window.location.reload();
      return;
    }
    // Keep the reader's selection; offer a reload instead.
    const banner = document.querySelector("[data-refresh-banner]");
    if (!banner) return;
    banner.textContent = "Update finished. ";
    const link = document.createElement("a");
    link.href = window.location.href;
    link.textContent = "Show new papers";
    banner.append(link);
  }

  window.setTimeout(poll, 2000);
})();
