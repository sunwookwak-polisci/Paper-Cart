(() => {
  const form = document.querySelector(".export-form");
  if (!form) return;

  form.addEventListener("submit", () => {
    document.querySelector("[data-notice]")?.remove();
    const url = new URL(window.location.href);
    if (!url.searchParams.has("notice")) return;
    url.searchParams.delete("notice");
    const query = url.searchParams.toString();
    history.replaceState(null, "", query ? `${url.pathname}?${query}` : url.pathname);
  });
})();
