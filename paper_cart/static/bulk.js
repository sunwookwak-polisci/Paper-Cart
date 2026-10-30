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

  function sync() {
    const boxes = picks();
    const picked = boxes.filter((box) => box.checked).length;
    if (count) count.textContent = picked ? `${picked} selected` : hint;
    buttons.forEach((button) => {
      button.disabled = picked === 0;
    });
    if (all instanceof HTMLInputElement) {
      all.checked = boxes.length > 0 && picked === boxes.length;
      all.indeterminate = picked > 0 && picked < boxes.length;
    }
    if (!boxes.length) form.hidden = true;
  }

  if (all instanceof HTMLInputElement) {
    all.addEventListener("change", () => {
      picks().forEach((box) => {
        box.checked = all.checked;
      });
      sync();
    });
  }

  list.addEventListener("change", (event) => {
    if (event.target instanceof HTMLInputElement && event.target.matches("[data-bulk-pick]")) sync();
  });

  // Single-paper moves remove cards; keep the count honest.
  new MutationObserver(sync).observe(list, { childList: true, subtree: true });

  sync();
})();
