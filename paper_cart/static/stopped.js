// When Paper Cart stops (Ctrl+C in Terminal), swap this tab for the same
// "stopped" page that Quit shows, so it no longer looks like it still works.
(() => {
  const template = document.querySelector("template[data-stopped-page]");
  if (!(template instanceof HTMLTemplateElement)) return;
  const CHECK_MS = 5000;
  const RECHECK_MS = 1000;
  let timer = 0;
  let checking = false;
  let misses = 0;

  // Only a refused connection counts as a miss. A slow answer means the
  // server is busy, not stopped, so there is no timeout here.
  async function reachable() {
    try {
      const response = await fetch("/healthz", { cache: "no-store" });
      return response.ok;
    } catch {
      return false;
    }
  }

  async function check() {
    window.clearTimeout(timer);
    if (checking) return;
    if (document.hidden) return;
    checking = true;
    const up = await reachable();
    checking = false;
    if (up) {
      misses = 0;
      schedule(CHECK_MS);
      return;
    }
    misses += 1;
    // Check twice, a second apart, so a brief hiccup (like waking from sleep)
    // does not hide the page.
    if (misses >= 2) {
      showStopped();
      return;
    }
    schedule(RECHECK_MS);
  }

  function schedule(delay) {
    window.clearTimeout(timer);
    timer = window.setTimeout(check, delay);
  }

  function showStopped() {
    document.removeEventListener("visibilitychange", onVisible);
    window.removeEventListener("pageshow", onVisible);
    window.removeEventListener("focus", onVisible);
    document.title = "Stopped · Paper Cart";
    document.body.replaceChildren(template.content.cloneNode(true));
    window.scrollTo(0, 0);
  }

  function onVisible() {
    if (!document.hidden) check();
  }

  document.addEventListener("visibilitychange", onVisible);
  window.addEventListener("pageshow", onVisible);
  window.addEventListener("focus", onVisible);
  schedule(CHECK_MS);
})();
