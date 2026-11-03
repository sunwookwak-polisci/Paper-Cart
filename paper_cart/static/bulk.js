(() => {
  const form = document.querySelector("[data-bulk]");
  const list = document.querySelector("[data-paper-list]");
  if (!form || !list) return;
  const all = form.querySelector("[data-bulk-all]");
  const allLabel = form.querySelector("[data-bulk-all-label]");
  const count = form.querySelector("[data-bulk-count]");
  const buttons = form.querySelectorAll(".status-group button, [data-copy-dois]");
  const copyButton = form.querySelector("[data-copy-dois]");
  const note = form.querySelector("[data-copy-note]");
  const hint = count ? count.textContent : "";
  let selectionKey = null;

  if (allLabel) allLabel.hidden = false;

  function picks() {
    return Array.from(list.querySelectorAll("[data-bulk-pick]"));
  }

  // Papers inside a folded journal are hidden, so "Select all shown" skips them.
  function shown() {
    return picks().filter((box) => !box.closest("details.journal-group:not([open])"));
  }

  function selectedDois() {
    return picks()
      .filter((box) => box.checked)
      .map((box) => box.value.trim())
      .filter(Boolean);
  }

  function showNote(message) {
    if (!note) return;
    note.hidden = false;
    note.textContent = message;
  }

  function clearNote() {
    if (!note) return;
    note.hidden = true;
    note.textContent = "";
  }

  function sync() {
    const boxes = picks();
    const pickedBoxes = boxes.filter((box) => box.checked);
    const key = pickedBoxes.map((box) => box.value).join("\n");
    if (selectionKey !== null && key !== selectionKey) clearNote();
    selectionKey = key;
    const picked = pickedBoxes.length;
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

  if (copyButton) {
    copyButton.addEventListener("click", (event) => {
      event.preventDefault();
      const dois = selectedDois();
      if (!dois.length) return;
      copyText(dois.join("\n")).then(
        () => {
          const label = dois.length === 1 ? "DOI" : "DOIs";
          showNote(`Copied ${dois.length} ${label}.`);
        },
        () => {
          showNote("Could not copy the DOIs.");
        },
      );
    });
  }

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text).catch(() => copyWithTextarea(text));
    }
    return copyWithTextarea(text);
  }

  function copyWithTextarea(text) {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.top = "0";
    area.style.left = "0";
    area.style.opacity = "0";
    document.body.append(area);
    area.focus();
    area.select();
    let ok = false;
    try {
      ok = document.execCommand("copy");
    } catch {
      ok = false;
    }
    area.remove();
    return ok ? Promise.resolve() : Promise.reject(new Error("copy failed"));
  }

  // Single-paper moves remove cards; keep the count honest.
  new MutationObserver(sync).observe(list, { childList: true, subtree: true });

  // A browser can put back ticks from an earlier visit after this script ran.
  window.addEventListener("pageshow", sync);

  sync();
})();
