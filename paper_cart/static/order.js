(() => {
  const panel = document.querySelector("#journal-order-panel");
  const list = document.querySelector("#journal-order");
  if (!list) return;

  let pending = Promise.resolve();
  let drag = null;
  let settling = false;
  let ticking = false;

  if (panel) {
    panel.addEventListener("toggle", () => {
      const body = new FormData();
      body.set("order_open", panel.open ? "1" : "0");
      body.set("next", nextValue(list));
      enqueue(() => postView(body));
    });
  }

  list.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (form.dataset.native === "1") {
      delete form.dataset.native;
      return;
    }
    event.preventDefault();
    const submitter = event.submitter;
    if (!(submitter instanceof HTMLButtonElement) || submitter.disabled) return;
    const direction = submitter.value === "up" ? "up" : "down";
    const row = form.closest(".order-row");
    if (!(row instanceof HTMLElement) || !step(row, direction)) return;
    const journalId = row.dataset.journalId || "";
    const next = nextValue(form);
    enqueue(() => postStep(journalId, direction, next));
  });

  list.addEventListener("pointerdown", (event) => {
    if (drag || settling) return;
    if (!(event instanceof PointerEvent) || event.button !== 0) return;
    const target = event.target;
    if (!(target instanceof Element)) return;
    if (target.closest("button, a, input") && !target.closest(".drag-handle")) return;
    const row = target.closest(".order-row");
    if (!(row instanceof HTMLElement) || !list.contains(row)) return;
    const rows = [...list.querySelectorAll(".order-row")];
    const from = rows.indexOf(row);
    if (from < 0) return;
    event.preventDefault();

    const boxes = rows.map((item) => item.getBoundingClientRect());
    const scrollY = window.scrollY;
    drag = {
      row,
      rows,
      from,
      target: from,
      pointerId: event.pointerId,
      startClientY: event.clientY,
      startScrollY: scrollY,
      lastClientY: event.clientY,
      tops: boxes.map((box) => box.top + scrollY),
      heights: boxes.map((box) => box.height),
      outers: boxes.map((box, index) => {
        const gap =
          index < boxes.length - 1
            ? boxes[index + 1].top - box.bottom
            : index > 0
              ? box.top - boxes[index - 1].bottom
              : 0;
        return box.height + Math.max(0, gap);
      }),
      active: false,
      ended: false,
    };

    window.addEventListener("pointermove", onPointerMove, { passive: false });
    window.addEventListener("pointerup", endDrag);
    window.addEventListener("pointercancel", endDrag);
    row.addEventListener("lostpointercapture", endDrag);
    try {
      row.setPointerCapture(event.pointerId);
    } catch {
      /* The window listeners still receive the gesture. */
    }
    startTick();
  });

  function onPointerMove(event) {
    if (!drag || event.pointerId !== drag.pointerId) return;
    drag.lastClientY = event.clientY;
    if (drag.active) event.preventDefault();
    updateDrag();
  }

  function updateDrag() {
    if (!drag) return;
    const delta = drag.lastClientY - drag.startClientY;
    if (!drag.active) {
      if (Math.abs(delta) < 4) return;
      drag.active = true;
      drag.row.classList.add("is-lifted");
      document.body.classList.add("is-order-dragging");
    }
    const scrollDelta = window.scrollY - drag.startScrollY;
    drag.row.style.transform = `translateY(${delta + scrollDelta}px)`;
    const target = indexForPointer(drag.lastClientY);
    if (target !== drag.target) {
      drag.target = target;
      applyShifts();
    }
  }

  function indexForPointer(clientY) {
    const scrollY = window.scrollY;
    for (let index = 0; index < drag.rows.length; index += 1) {
      if (index === drag.from) continue;
      const mid = drag.tops[index] - scrollY + drag.heights[index] / 2;
      if (clientY < mid) return index > drag.from ? index - 1 : index;
    }
    return drag.rows.length - 1;
  }

  function applyShifts() {
    const shift = drag.outers[drag.from];
    drag.rows.forEach((item, index) => {
      if (index === drag.from) return;
      let offset = 0;
      if (drag.target > drag.from && index > drag.from && index <= drag.target) offset = -shift;
      else if (drag.target < drag.from && index >= drag.target && index < drag.from) offset = shift;
      item.style.transform = offset ? `translateY(${offset}px)` : "";
    });
  }

  function endDrag(event) {
    if (!drag || drag.ended) return;
    if (event instanceof PointerEvent && event.pointerId !== drag.pointerId) return;
    if (event instanceof PointerEvent && event.type !== "lostpointercapture") {
      drag.lastClientY = event.clientY;
      updateDrag();
    }
    drag.ended = true;
    const state = drag;
    drag = null;
    window.removeEventListener("pointermove", onPointerMove);
    window.removeEventListener("pointerup", endDrag);
    window.removeEventListener("pointercancel", endDrag);
    state.row.removeEventListener("lostpointercapture", endDrag);
    if (state.row.hasPointerCapture?.(state.pointerId)) {
      try {
        state.row.releasePointerCapture(state.pointerId);
      } catch {
        /* The pointer is already released. */
      }
    }
    settle(state);
  }

  function settle(state) {
    document.body.classList.remove("is-order-dragging");
    const { rows, from, target, row } = state;
    if (!state.active) {
      clearMotion(rows, row);
      return;
    }
    const visualTop = row.getBoundingClientRect().top;
    rows.forEach((item) => {
      item.style.transition = "none";
    });
    if (target !== from) {
      const anchor = rows[target];
      if (target < from) list.insertBefore(row, anchor);
      else list.insertBefore(row, anchor.nextSibling);
    }
    rows.forEach((item) => {
      item.style.transform = "";
    });
    const correction = visualTop - row.getBoundingClientRect().top;
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion || Math.abs(correction) < 1) {
      clearMotion(rows, row);
    } else {
      settling = true;
      row.style.transform = `translateY(${correction}px)`;
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          let cleaned = false;
          const cleanup = () => {
            if (cleaned) return;
            cleaned = true;
            settling = false;
            clearMotion(rows, row);
          };
          row.addEventListener("transitionend", (endEvent) => {
            if (endEvent.target !== row || endEvent.propertyName !== "transform") return;
            cleanup();
          });
          row.style.transition = "transform 160ms ease";
          row.style.transform = "";
          row.classList.remove("is-lifted");
          window.setTimeout(cleanup, 240);
        });
      });
    }
    if (target === from) return;
    refresh();
    enqueue(() => postOrder(journalIds(), nextValue(list)));
  }

  function clearMotion(rows, row) {
    row.classList.remove("is-lifted");
    rows.forEach((item) => {
      item.style.transition = "";
      item.style.transform = "";
    });
  }

  function startTick() {
    if (ticking) return;
    ticking = true;
    const tick = () => {
      if (!drag) {
        ticking = false;
        return;
      }
      const speed = drag.active ? scrollSpeed(drag.lastClientY) : 0;
      if (speed) {
        window.scrollBy(0, speed);
        updateDrag();
      }
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  function scrollSpeed(clientY) {
    const edge = 64;
    const max = 16;
    if (clientY < edge) return -Math.ceil(((edge - clientY) / edge) * max);
    const limit = window.innerHeight - edge;
    if (clientY > limit) return Math.ceil(((clientY - limit) / edge) * max);
    return 0;
  }

  function step(row, direction) {
    const sibling = direction === "up" ? row.previousElementSibling : row.nextElementSibling;
    if (!(sibling instanceof HTMLElement) || !sibling.classList.contains("order-row")) return false;
    if (direction === "up") list.insertBefore(row, sibling);
    else list.insertBefore(sibling, row);
    refresh();
    return true;
  }

  function refresh() {
    const rows = [...list.querySelectorAll(".order-row")];
    rows.forEach((row, index) => {
      const up = row.querySelector('button[value="up"]');
      const down = row.querySelector('button[value="down"]');
      if (up instanceof HTMLButtonElement) up.disabled = index === 0;
      if (down instanceof HTMLButtonElement) down.disabled = index === rows.length - 1;
    });
    syncPaperGroups(rows.map((row) => row.querySelector(".order-title")?.textContent?.trim() || ""));
  }

  function syncPaperGroups(titles) {
    const papers = document.querySelector("[data-paper-list]");
    if (!papers) return;
    const rank = new Map(titles.map((title, index) => [title, index]));
    const groups = [];
    for (const heading of [...papers.querySelectorAll(":scope > h2.journal-name")]) {
      const nodes = [heading];
      let node = heading.nextElementSibling;
      while (node && !(node instanceof HTMLElement && node.classList.contains("journal-name"))) {
        const next = node.nextElementSibling;
        nodes.push(node);
        node = next;
      }
      groups.push({ title: heading.textContent.trim(), nodes });
    }
    groups.sort((left, right) => {
      const leftRank = rank.has(left.title) ? rank.get(left.title) : Number.MAX_SAFE_INTEGER;
      const rightRank = rank.has(right.title) ? rank.get(right.title) : Number.MAX_SAFE_INTEGER;
      return leftRank - rightRank;
    });
    for (const group of groups) {
      for (const node of group.nodes) papers.append(node);
    }
  }

  function journalIds() {
    return [...list.querySelectorAll(".order-row")].map((row) => row.dataset.journalId || "");
  }

  function nextValue(root) {
    const input = root.querySelector('input[name="next"]');
    return input instanceof HTMLInputElement ? input.value : "/";
  }

  function enqueue(task) {
    pending = pending.then(task, task);
  }

  async function postView(body) {
    const response = await fetch("/view", { method: "POST", body });
    if (!response.ok) window.location.reload();
  }

  async function postStep(journalId, direction, next) {
    const body = new FormData();
    body.set("journal_id", journalId);
    body.set("direction", direction);
    body.set("next", next);
    const response = await fetch("/journals/order", { method: "POST", body });
    if (!response.ok) window.location.reload();
  }

  async function postOrder(ids, next) {
    const body = new FormData();
    ids.forEach((id) => body.append("order", id));
    body.set("next", next);
    const response = await fetch("/journals/order", { method: "POST", body });
    if (!response.ok) window.location.reload();
  }
})();
