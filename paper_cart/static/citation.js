(() => {
  const buttons = document.querySelectorAll("[data-copy-citation]");
  const LABEL = "Copy citation";
  const live = document.createElement("p");
  live.className = "visually-hidden";
  live.setAttribute("role", "status");
  live.setAttribute("aria-live", "polite");
  document.body.append(live);

  // Copying needs this script, so the buttons only show when it runs.
  buttons.forEach((button) => {
    button.hidden = false;
    button.addEventListener("click", () => {
      const text = button.dataset.citationText || "";
      if (!text) return;
      copy(text, button.dataset.citationHtml || "", button).then(
        () => say(button, "Copied", "Copied the citation."),
        () => say(button, "Could not copy", "Could not copy the citation."),
      );
    });
  });

  function say(button, label, message) {
    button.textContent = label;
    live.textContent = message;
    clearTimeout(button.resetTimer);
    button.resetTimer = setTimeout(() => {
      button.textContent = LABEL;
    }, 2000);
  }

  // Word and Google Docs keep the italics from the HTML copy; plain text has none.
  function copy(text, html, button) {
    if (navigator.clipboard && window.isSecureContext) {
      if (html && window.ClipboardItem && navigator.clipboard.write) {
        const item = new ClipboardItem({
          "text/plain": new Blob([text], { type: "text/plain" }),
          "text/html": new Blob([html], { type: "text/html" }),
        });
        return navigator.clipboard
          .write([item])
          .catch(() => navigator.clipboard.writeText(text))
          .catch(() => copyWithTextarea(text, button));
      }
      return navigator.clipboard.writeText(text).catch(() => copyWithTextarea(text, button));
    }
    return copyWithTextarea(text, button);
  }

  function copyWithTextarea(text, button) {
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
    button.focus();
    return ok ? Promise.resolve() : Promise.reject(new Error("copy failed"));
  }
})();
