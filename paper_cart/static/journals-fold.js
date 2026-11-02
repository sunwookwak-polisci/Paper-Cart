(() => {
  const list = document.querySelector("[data-paper-list]");
  const form = document.querySelector("[data-journal-folds]");
  if (!list || !form) return;
  const next = form.querySelector('input[name="next"]');
  let bulk = false;

  function groups() {
    return Array.from(list.querySelectorAll("details.journal-group"));
  }

  async function save(body) {
    try {
      const response = await fetch(form.action, { method: "POST", body });
      if (response.ok) return;
    } catch {}
    // Saving failed; reload so the page shows the stored state.
    window.location.reload();
  }

  // One journal opened or folded by its heading.
  list.addEventListener(
    "toggle",
    (event) => {
      const group = event.target;
      if (bulk || !(group instanceof HTMLDetailsElement) || !group.classList.contains("journal-group")) return;
      const body = new FormData();
      body.set("next", next instanceof HTMLInputElement ? next.value : "/");
      body.set("journal", group.dataset.journal || "");
      body.set("journal_open", group.open ? "1" : "0");
      save(body);
    },
    true,
  );

  form.addEventListener("submit", (event) => {
    if (form.dataset.native === "1") return;
    event.preventDefault();
    const button = event.submitter;
    if (!(button instanceof HTMLButtonElement)) return;
    const open = button.value === "open";
    bulk = true;
    groups().forEach((group) => {
      group.open = open;
    });
    // toggle events fire after this task; let them pass before listening again.
    setTimeout(() => {
      bulk = false;
    }, 0);
    const body = new FormData(form);
    body.set("journals", button.value);
    save(body);
  });
})();
