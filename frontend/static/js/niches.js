document.addEventListener("DOMContentLoaded", () => {
  const root = document.getElementById("categories-root");

  // раскрыть/свернуть подсписок главной категории
  root.addEventListener("click", (e) => {
    const toggle = e.target.closest(".toggle");
    if (toggle) {
      const id = toggle.dataset.id;
      const card = root.querySelector(`.cat-card[data-id="${id}"]`);
      const sublist = card && card.querySelector(`.sublist[data-parent="${id}"]`);
      if (!sublist) return;
      const active = sublist.classList.toggle("active");
      toggle.setAttribute("aria-expanded", active ? "true" : "false");
      toggle.textContent = active ? "▾" : "▸";
      return;
    }

    // раскрыть/свернуть "узкие" категории внутри подкатегории
    const subToggle = e.target.closest(".sub-toggle");
    if (subToggle) {
      const id = subToggle.dataset.id;
      const inner = root.querySelector(`.sublist.inner[data-parent="${id}"]`);
      if (!inner) return;
      const isShown = inner.style.display === "block";
      inner.style.display = isShown ? "none" : "block";
      subToggle.setAttribute("aria-expanded", isShown ? "false" : "true");
      subToggle.textContent = isShown ? "▸" : "▾";
      return;
    }

    // клик по .subitem: если это не лист и клик не на кнопке/ссылке — развернуть подкатегорию
    const subItem = e.target.closest(".subitem");
    if (subItem && !subItem.classList.contains("leaf")) {
      const subId = subItem.dataset.id;
      const subToggleBtn = subItem.querySelector(".sub-toggle");
      if (subToggleBtn) {
        subToggleBtn.click();
      }
    }
  });

  // keyboard support
  root.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const btn = e.target.closest(".toggle, .sub-toggle");
    if (!btn) return;
    e.preventDefault();
    btn.click();
  });

});
