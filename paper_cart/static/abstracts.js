(() => {
  const form = document.querySelector("[data-abstracts]");
  if (!form) return;
  const button = form.querySelector("button");
  const value = form.querySelector('input[name="abstracts"]');

  form.addEventListener("submit", async (event) => {
    if (form.dataset.native === "1") return;
    event.preventDefault();
    const open = value.value === "1";
    document.querySelectorAll("details.abstract").forEach((details) => {
      details.open = open;
    });
    button.classList.toggle("is-current", open);
    button.setAttribute("aria-pressed", open ? "true" : "false");
    const body = new FormData(form);
    value.value = open ? "0" : "1";
    try {
      const response = await fetch(form.action, { method: "POST", body });
      if (response.ok) return;
    } catch {}
    // Saving failed; fall back to a normal submit so the page shows the stored state.
    value.value = open ? "1" : "0";
    form.dataset.native = "1";
    form.requestSubmit();
  });
})();
