(() => {
  const list = document.querySelector("[data-paper-list]");
  if (!list) return;
  const view = list.dataset.status || "";

  list.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.classList.contains("status-form")) return;
    if (form.dataset.native === "1") {
      delete form.dataset.native;
      return;
    }
    event.preventDefault();
    if (form.dataset.pending === "1") return;
    form.dataset.pending = "1";
    const submitter = event.submitter;
    submitStatus(form, submitter).finally(() => {
      delete form.dataset.pending;
    });
  });

  async function submitStatus(form, submitter) {
    const body = new FormData(form);
    if (submitter instanceof HTMLButtonElement && submitter.name) {
      body.set(submitter.name, submitter.value);
    }
    const scrollY = window.scrollY;
    let response;
    try {
      response = await fetch(form.action, { method: "POST", body });
    } catch {
      submitNatively(form, submitter);
      return;
    }
    if (!response.ok) {
      submitNatively(form, submitter);
      return;
    }
    const nextStatus = String(body.get("status") || "");
    await replaceCounts(response);
    if (nextStatus === view) return;
    const article = form.closest("article");
    if (article) removeArticle(article);
    restoreScroll(scrollY);
  }

  function submitNatively(form, submitter) {
    form.dataset.native = "1";
    if (submitter instanceof HTMLElement) form.requestSubmit(submitter);
    else form.requestSubmit();
  }

  async function replaceCounts(response) {
    const html = await response.text();
    const fresh = new DOMParser().parseFromString(html, "text/html");
    document.querySelectorAll("[data-count]").forEach((node) => {
      const status = node.getAttribute("data-count");
      const updated = fresh.querySelector(`[data-count="${status}"]`);
      if (updated) node.textContent = updated.textContent;
    });
  }

  function removeArticle(article) {
    const previous = article.previousElementSibling;
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    article.remove();
    if (previous instanceof HTMLElement && previous.classList.contains("journal-name")) {
      const next = previous.nextElementSibling;
      if (!(next instanceof HTMLElement) || next.tagName !== "ARTICLE") previous.remove();
    }
    if (!list.querySelector("article")) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = list.dataset.empty || "";
      list.append(empty);
    }
  }

  function restoreScroll(scrollY) {
    const apply = () => window.scrollTo(0, scrollY);
    apply();
    requestAnimationFrame(apply);
  }
})();
