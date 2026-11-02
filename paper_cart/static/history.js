(() => {
  const SCROLL_KEY = "paper-cart-history-scroll";
  let pending = false;

  restoreScroll();

  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.matches("[data-history]")) return;
    if (form.dataset.native === "1") {
      delete form.dataset.native;
      return;
    }
    event.preventDefault();
    const button = event.submitter instanceof HTMLButtonElement ? event.submitter : null;
    if (button) run(form, button);
  });

  document.addEventListener("keydown", (event) => {
    if (event.defaultPrevented || event.altKey || !(event.metaKey || event.ctrlKey)) return;
    const key = event.key.toLowerCase();
    let selector = "";
    if (key === "z") selector = event.shiftKey ? "[data-history-redo]" : "[data-history-undo]";
    else if (key === "y" && event.ctrlKey && !event.shiftKey) selector = "[data-history-redo]";
    if (!selector || typing(event.target)) return;
    event.preventDefault();
    const button = document.querySelector(selector);
    if (!(button instanceof HTMLButtonElement) || button.disabled || !button.form) return;
    run(button.form, button);
  });

  async function run(form, button) {
    if (pending) return;
    pending = true;
    form.querySelectorAll("button").forEach((each) => {
      each.disabled = true;
    });
    let response;
    try {
      response = await fetch(button.hasAttribute("formaction") ? button.formAction : form.action, {
        method: "POST",
        body: new FormData(form),
      });
    } catch {
      response = null;
    }
    if (!response || !response.ok) {
      pending = false;
      form.dataset.native = "1";
      button.disabled = false;
      form.requestSubmit(button);
      return;
    }
    // Reload the page in place so restored papers show up where they belong.
    const target = new URL(response.url || location.href, location.href);
    try {
      sessionStorage.setItem(
        SCROLL_KEY,
        JSON.stringify({ path: target.pathname + target.search, y: window.scrollY }),
      );
    } catch {}
    location.replace(target.href);
  }

  function typing(target) {
    if (!(target instanceof HTMLElement)) return false;
    if (target.isContentEditable || target instanceof HTMLTextAreaElement) return true;
    if (target instanceof HTMLSelectElement) return true;
    if (!(target instanceof HTMLInputElement)) return false;
    return !["checkbox", "radio", "button", "submit", "reset", "range", "color", "file"].includes(
      target.type,
    );
  }

  function restoreScroll() {
    let saved = null;
    try {
      saved = JSON.parse(sessionStorage.getItem(SCROLL_KEY) || "null");
      sessionStorage.removeItem(SCROLL_KEY);
    } catch {
      return;
    }
    if (!saved || saved.path !== location.pathname + location.search) return;
    const apply = () => window.scrollTo(0, Number(saved.y) || 0);
    apply();
    requestAnimationFrame(apply);
  }
})();
