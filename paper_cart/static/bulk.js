(() => {
  const form = document.querySelector("[data-bulk]");
  const list = document.querySelector("[data-paper-list]");
  if (!form || !list) return;
  const all = form.querySelector("[data-bulk-all]");
  const allLabel = form.querySelector("[data-bulk-all-label]");
  const count = form.querySelector("[data-bulk-count]");
  const buttons = form.querySelectorAll(".status-group button");
  const hint = count ? count.textContent : "";

  if (allLabel) allLabel.hidden = false;

  function picks() {
    return Array.from(list.querySelectorAll("[data-bulk-pick]"));
  }

  // Papers inside a folded journal are hidden, so "Select all shown" skips them.
  function shown() {
    return picks().filter((box) => !box.closest("details.journal-group:not([open])"));
  }

  function sync() {
    const picked = picks().filter((box) => box.checked).length;
    if (count) count.textContent = picked ? `${picked} selected` : hint;
    buttons.forEach((button) => {
      button.disabled = picked === 0;
    });
    if (all instanceof HTMLInputElement) {
      const boxes = shown();
      const pickedShown = boxes.filter((box) => box.checked).length;
      all.checked = boxes.length > 0 && pickedShown === boxes.length;
      all.indeterminate = pickedShown > 0 && pickedShown < boxes.length;
    }
    if (!picks().length) form.hidden = true;
  }

  if (all instanceof HTMLInputElement) {
    all.addEventListener("change", () => {
      shown().forEach((box) => {
        box.checked = all.checked;
      });
      sync();
    });
  }

  list.addEventListener("change", (event) => {
    if (event.target instanceof HTMLInputElement && event.target.matches("[data-bulk-pick]")) sync();
  });

  list.addEventListener("toggle", sync, true);

  // Single-paper moves remove cards; keep the count honest.
  new MutationObserver(sync).observe(list, { childList: true, subtree: true });

  // A browser can put back ticks from an earlier visit after this script ran.
  window.addEventListener("pageshow", sync);

  sync();
})();
