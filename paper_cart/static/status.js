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
    const fresh = await replaceCounts(response);
    if (nextStatus === view) return;
    const article = form.closest("article");
    if (article && view === "all" && nextStatus !== "removed") {
      refreshArticle(article, fresh);
    } else if (article) {
      removeArticle(article);
    }
    restoreScroll(scrollY);
  }

  // On All the paper stays; swap in its new status label and buttons.
  function refreshArticle(article, fresh) {
    const doi = article.getAttribute("data-doi");
    const updated = Array.from(fresh.querySelectorAll("[data-paper-list] article")).find(
      (node) => node.getAttribute("data-doi") === doi
    );
    if (!updated) {
      removeArticle(article);
      return;
    }
    const replacement = document.importNode(updated, true);
    const pick = article.querySelector("[data-bulk-pick]");
    const freshPick = replacement.querySelector("[data-bulk-pick]");
    if (pick instanceof HTMLInputElement && freshPick instanceof HTMLInputElement) {
      freshPick.checked = pick.checked;
    }
    const abstract = article.querySelector("details.abstract");
    const freshAbstract = replacement.querySelector("details.abstract");
    if (abstract instanceof HTMLDetailsElement && freshAbstract instanceof HTMLDetailsElement) {
      freshAbstract.open = abstract.open;
    }
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    article.replaceWith(replacement);
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
    // Undo and Redo now point at this move.
    const history = document.querySelector("[data-history]");
    const freshHistory = fresh.querySelector("[data-history]");
    if (history && freshHistory) history.replaceWith(document.importNode(freshHistory, true));
    return fresh;
  }

  function removeArticle(article) {
    const group = article.closest("details.journal-group");
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    article.remove();
    if (group) {
      const left = group.querySelectorAll("article").length;
      const count = group.querySelector("[data-journal-count]");
      if (!left) group.remove();
      else if (count) count.textContent = `${left} ${left === 1 ? "paper" : "papers"}`;
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
