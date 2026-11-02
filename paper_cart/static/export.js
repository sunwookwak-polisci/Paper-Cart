(() => {
  const form = document.querySelector(".export-form");
  if (!form) return;
  const button = form.querySelector("[data-export-button]");
  const panel = form.querySelector("[data-export-progress]");
  const message = panel.querySelector("[data-export-message]");
  const current = panel.querySelector("[data-export-current]");
  const track = panel.querySelector("[data-export-track]");
  const fill = panel.querySelector("[data-export-fill]");
  const download = panel.querySelector("[data-export-download]");
  const cancel = panel.querySelector("[data-export-cancel]");
  const POLL_MS = 500;
  let jobId = "";
  let misses = 0;

  form.addEventListener("submit", async (event) => {
    clearNotice();
    if (form.dataset.native === "1") {
      delete form.dataset.native;
      return;
    }
    event.preventDefault();
    if (jobId) return;
    setBusy(true);
    showStarting();
    let data = null;
    try {
      const response = await fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        headers: { Accept: "application/json" },
      });
      if (response.ok) data = await response.json();
    } catch {}
    if (!data) {
      // Fall back to the plain form post, which waits for the file.
      setBusy(false);
      panel.hidden = true;
      form.dataset.native = "1";
      form.requestSubmit(button);
      return;
    }
    if (data.redirect) {
      location.assign(data.redirect);
      return;
    }
    follow(data);
  });

  cancel.addEventListener("click", async () => {
    if (!jobId) return;
    cancel.disabled = true;
    try {
      const response = await fetch(`/journals/export/${jobId}/cancel`, { method: "POST" });
      if (response.ok) render(await response.json());
    } catch {}
  });

  if (form.dataset.exportJob) {
    jobId = form.dataset.exportJob;
    setBusy(true);
    showStarting();
    poll();
  }

  function follow(job) {
    jobId = job.id;
    render(job);
    if (job.state === "running") setTimeout(poll, POLL_MS);
  }

  async function poll() {
    if (!jobId) return;
    let job = null;
    try {
      const response = await fetch(`/journals/export/${jobId}`, { cache: "no-store" });
      if (response.ok) job = await response.json();
      else if (response.status === 404) return lost("This export is no longer available. Try again.");
    } catch {}
    if (!job) {
      misses += 1;
      if (misses >= 6) return lost("Paper Cart stopped responding. Check that it is still running.");
      setTimeout(poll, POLL_MS * 2);
      return;
    }
    misses = 0;
    follow(job);
  }

  function render(job) {
    panel.hidden = false;
    message.textContent = job.message;
    current.textContent = job.current ? `Now: ${job.current}` : "";
    const running = job.state === "running";
    track.hidden = !(running || job.state === "ready");
    fill.style.width = `${job.percent}%`;
    track.setAttribute("aria-valuenow", String(job.percent));
    cancel.hidden = !running;
    cancel.disabled = Boolean(job.cancelling);
    if (job.state === "ready") {
      download.href = job.download;
      download.download = job.filename;
      download.textContent = `Download ${job.filename} again`;
      download.hidden = false;
      // Another open Journals tab may have fetched the file already.
      if (jobId && !job.downloaded) download.click();
    } else {
      download.hidden = true;
    }
    if (!running) finish();
  }

  function showStarting() {
    panel.hidden = false;
    message.textContent = "Exporting abstracts…";
    current.textContent = "";
    track.hidden = false;
    fill.style.width = "0%";
    track.setAttribute("aria-valuenow", "0");
    cancel.hidden = true;
    download.hidden = true;
  }

  function lost(text) {
    panel.hidden = false;
    message.textContent = text;
    current.textContent = "";
    track.hidden = true;
    cancel.hidden = true;
    download.hidden = true;
    finish();
  }

  function finish() {
    jobId = "";
    misses = 0;
    setBusy(false);
  }

  function setBusy(busy) {
    button.disabled = busy;
    button.textContent = busy ? "Exporting…" : "Export abstracts";
  }

  function clearNotice() {
    document.querySelector("[data-notice]")?.remove();
    const url = new URL(window.location.href);
    if (!url.searchParams.has("notice")) return;
    url.searchParams.delete("notice");
    const query = url.searchParams.toString();
    history.replaceState(null, "", query ? `${url.pathname}?${query}` : url.pathname);
  }
})();
