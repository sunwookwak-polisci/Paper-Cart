(function () {
  const STORAGE_KEY = "paper-cart-theme";
  const MODES = ["light", "dark", "system"];
  const LIGHTS = ["alucard", "tokyo-light", "ayu-light", "solarized-light"];
  const DARKS = ["dracula", "tokyo-night", "ayu-dark", "solarized-dark"];
  const FONTS = ["serif", "sans"];
  const FONT_KEY = "paper-cart-font";

  function storedAppearance() {
    const root = document.documentElement;
    const pref = {
      mode: MODES.includes(root.dataset.themePreference) ? root.dataset.themePreference : "system",
      light: root.dataset.themeLight || "alucard",
      dark: root.dataset.themeDark || "dracula",
    };
    if (pref.light === "catppuccin-latte") pref.light = "alucard";
    if (pref.dark === "catppuccin-mocha") pref.dark = "dracula";
    return pref;
  }

  function preference() {
    const pref = storedAppearance();
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === "light" || raw === "alucard") {
      pref.mode = "light";
      return pref;
    }
    if (raw === "dark" || raw === "dracula") {
      pref.mode = "dark";
      return pref;
    }
    if (raw === "tokyo-light") {
      pref.mode = "light";
      pref.light = "tokyo-light";
      return pref;
    }
    if (raw === "tokyo-night") {
      pref.mode = "dark";
      pref.dark = "tokyo-night";
      return pref;
    }
    if (raw === "system") {
      pref.mode = "system";
      return pref;
    }
    if (!raw) return pref;
    try {
      const parsed = JSON.parse(raw);
      if (MODES.includes(parsed.mode)) pref.mode = parsed.mode;
      if (LIGHTS.includes(parsed.light)) pref.light = parsed.light;
      else if (parsed.light === "catppuccin-latte") pref.light = "alucard";
      if (DARKS.includes(parsed.dark)) pref.dark = parsed.dark;
      else if (parsed.dark === "catppuccin-mocha") pref.dark = "dracula";
    } catch (error) {
      return pref;
    }
    return pref;
  }

  function systemDark() {
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  function resolvedMode(pref) {
    return pref.mode === "system" ? (systemDark() ? "dark" : "light") : pref.mode;
  }

  function apply(pref) {
    const mode = resolvedMode(pref);
    document.documentElement.dataset.theme = mode === "dark" ? pref.dark : pref.light;
    document.documentElement.dataset.themePreference = pref.mode;
    document.documentElement.style.colorScheme = mode;
  }

  function fontPreference() {
    const raw = localStorage.getItem(FONT_KEY);
    if (FONTS.includes(raw)) return raw;
    const saved = document.documentElement.dataset.font;
    return FONTS.includes(saved) ? saved : "serif";
  }

  function applyFont(font) {
    document.documentElement.dataset.font = font;
  }

  function menuRoot() {
    return document.querySelector("[data-theme-menu]");
  }

  function toggleButton() {
    return document.querySelector("[data-theme-toggle]");
  }

  function menuList() {
    return document.getElementById("theme-options");
  }

  function mark(attr, value) {
    document.querySelectorAll(`[${attr}]`).forEach((button) => {
      const active = button.getAttribute(attr) === value;
      button.classList.toggle("is-current", active);
      button.setAttribute("aria-checked", active ? "true" : "false");
    });
  }

  function syncControls(pref) {
    mark("data-theme-mode", pref.mode);
    mark("data-theme-light", pref.light);
    mark("data-theme-dark", pref.dark);
    mark("data-font", fontPreference());
  }

  function remember(pref, font) {
    const body = new URLSearchParams();
    body.set("mode", pref.mode);
    body.set("light", pref.light);
    body.set("dark", pref.dark);
    body.set("font", font);
    fetch("/appearance", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body.toString(),
    }).catch(() => {});
  }

  function save(pref) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(pref));
    apply(pref);
    syncControls(pref);
    remember(pref, fontPreference());
  }

  function choiceFrom(button) {
    if (button.hasAttribute("data-theme-mode")) return ["mode", button.getAttribute("data-theme-mode"), MODES];
    if (button.hasAttribute("data-theme-light")) return ["light", button.getAttribute("data-theme-light"), LIGHTS];
    if (button.hasAttribute("data-theme-dark")) return ["dark", button.getAttribute("data-theme-dark"), DARKS];
    return null;
  }

  function choose(button) {
    if (button.hasAttribute("data-font")) {
      const font = button.getAttribute("data-font");
      if (!FONTS.includes(font)) return;
      localStorage.setItem(FONT_KEY, font);
      applyFont(font);
      mark("data-font", font);
      remember(preference(), font);
      return;
    }
    const choice = choiceFrom(button);
    if (!choice) return;
    const [field, value, allowed] = choice;
    if (!allowed.includes(value)) return;
    const pref = preference();
    pref[field] = value;
    save(pref);
  }

  function isOpen() {
    const toggle = toggleButton();
    return Boolean(toggle && toggle.getAttribute("aria-expanded") === "true");
  }

  function setOpen(open) {
    const toggle = toggleButton();
    const list = menuList();
    if (!toggle || !list) return;
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    list.hidden = !open;
  }

  function focusCurrentMode() {
    const current = document.querySelector('[data-theme-mode][aria-checked="true"]');
    if (current) current.focus();
  }

  const storedTheme = localStorage.getItem(STORAGE_KEY);
  const pref = preference();
  apply(pref);
  applyFont(fontPreference());
  if (!storedTheme || storedTheme.includes("catppuccin")) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(pref));
    if (storedTheme && storedTheme.includes("catppuccin")) remember(pref, fontPreference());
  }
  if (!localStorage.getItem(FONT_KEY)) localStorage.setItem(FONT_KEY, fontPreference());

  document.addEventListener("DOMContentLoaded", () => {
    syncControls(preference());
    const toggle = toggleButton();
    const list = menuList();
    if (!toggle || !list) return;

    toggle.addEventListener("click", () => {
      const open = !isOpen();
      setOpen(open);
      if (open) focusCurrentMode();
    });

    list.querySelectorAll("[role='radio']").forEach((button) => {
      button.addEventListener("click", () => {
        choose(button);
      });
    });

    document.addEventListener("click", (event) => {
      const root = menuRoot();
      if (!isOpen() || !root || root.contains(event.target)) return;
      setOpen(false);
    });

    document.addEventListener("keydown", (event) => {
      if (!isOpen()) {
        if (document.activeElement === toggle && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
          event.preventDefault();
          setOpen(true);
          focusCurrentMode();
        }
        return;
      }

      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
        toggle.focus();
        return;
      }

      const group = document.activeElement && document.activeElement.closest("[role='radiogroup']");
      if (!group) return;
      const items = Array.from(group.querySelectorAll("[role='radio']")).filter((item) => item.parentElement === group);
      const index = items.indexOf(document.activeElement);
      if (index === -1) return;
      let next = null;
      if (event.key === "ArrowDown" || event.key === "ArrowRight") next = items[(index + 1) % items.length];
      if (event.key === "ArrowUp" || event.key === "ArrowLeft") next = items[(index - 1 + items.length) % items.length];
      if (event.key === "Home") next = items[0];
      if (event.key === "End") next = items[items.length - 1];
      if (!next) return;
      event.preventDefault();
      choose(next);
      next.focus();
    });
  });

  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    const pref = preference();
    if (pref.mode === "system") apply(pref);
  });
})();
