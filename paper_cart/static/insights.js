(() => {
  const chart = document.querySelector("[data-contributions]");
  if (!chart) return;
  const squares = Array.from(chart.querySelectorAll(".heat-cell"));
  if (!squares.length) return;
  const detail = chart.querySelector("[data-heat-detail]");
  const hint = detail.textContent;
  const initial = chart.querySelector(".heat-cell[aria-current]") || squares[squares.length - 1];
  for (const square of squares) square.tabIndex = square === initial ? 0 : -1;

  if (chart.dataset.period === "recent") {
    const scroller = chart.querySelector(".contribution-scroll");
    const distance = initial.getBoundingClientRect().right - scroller.getBoundingClientRect().right;
    if (distance > 0) scroller.scrollLeft += distance + 4;
  }

  function describe(square) {
    detail.textContent = square?.getAttribute("aria-label") || hint;
  }
  chart.addEventListener("pointerover", (event) => describe(event.target.closest(".heat-cell")));
  chart.addEventListener("pointerleave", () => describe(document.activeElement.closest(".heat-cell")));
  chart.addEventListener("focusin", (event) => {
    const square = event.target.closest(".heat-cell");
    if (!square) return;
    chart.querySelector('.heat-cell[tabindex="0"]').tabIndex = -1;
    square.tabIndex = 0;
    describe(square);
  });
  chart.addEventListener("focusout", () => describe(null));
  chart.addEventListener("keydown", (event) => {
    const index = squares.indexOf(event.target);
    if (index < 0) return;
    const offsets = {ArrowLeft: -7, ArrowRight: 7, ArrowUp: -1, ArrowDown: 1};
    let target;
    if (event.key === "Home") target = 0;
    else if (event.key === "End") target = squares.length - 1;
    else if (Object.hasOwn(offsets, event.key)) target = index + offsets[event.key];
    else return;
    event.preventDefault();
    squares[target]?.focus();
  });
})();
