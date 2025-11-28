
// Mobile-first accordion behaviour for categories/subcategories
document.addEventListener("DOMContentLoaded", () => {
  const root = document.getElementById("categories-root");
  const searchInput = document.getElementById("category-search");
  const periodBtn = document.getElementById("period-btn");

  // Toggle main category sublist
  root.addEventListener("click", (e) => {
    const toggle = e.target.closest(".toggle");
    if (toggle) {
      const id = toggle.dataset.id;
      const card = root.querySelector(`.cat-card[data-id="${id}"]`);
      const sublist = card && card.querySelector(`.sublist[data-parent="${id}"]`);
      if (!sublist) return;

      const isActive = sublist.classList.toggle("active");
      card.classList.toggle("open", isActive);
      toggle.setAttribute("aria-expanded", isActive ? "true" : "false");
      // chevron character
      const chev = toggle.querySelector(".chev");
      if (chev) chev.textContent = isActive ? "▾" : "▸";
      return;
    }

    // Toggle inner (sub) group
    const subToggle = e.target.closest(".sub-toggle");
    if (subToggle) {
      const id = subToggle.dataset.id;
      const inner = root.querySelector(`.sublist.inner[data-parent="${id}"]`);
      if (!inner) return;
      const isShown = inner.classList.toggle("active");
      subToggle.setAttribute("aria-expanded", isShown ? "true" : "false");
      subToggle.textContent = isShown ? "▾" : "▸";
      return;
    }

    // If click on subitem row (not a link/button) — toggle its sublist if present
    const subItem = e.target.closest(".subitem");
    if (subItem && !subItem.classList.contains("leaf")) {
      // ignore clicks on anchor links
      if (e.target.closest("a")) return;
      const subToggleBtn = subItem.querySelector(".sub-toggle");
      if (subToggleBtn) subToggleBtn.click();
    }
  });

  // keyboard support for toggles
  root.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const btn = e.target.closest(".toggle, .sub-toggle");
    if (!btn) return;
    e.preventDefault();
    btn.click();
  });

  // Simple search: фильтрация по названию категории/подкатегории
  if (searchInput) {
    searchInput.addEventListener("input", (e) => {
      const q = (e.target.value || "").trim().toLowerCase();
      filterCategories(q);
    });
  }

  // period button placeholder — можно заменить на модал или фильтр
  if (periodBtn) {
    periodBtn.addEventListener("click", () => {
      const pressed = periodBtn.getAttribute("aria-pressed") === "true";
      periodBtn.setAttribute("aria-pressed", (!pressed).toString());
      // тут можно открывать селектор периодов — оставим базовый toggle
      const txt = periodBtn.querySelector(".period-text");
      if (txt) txt.textContent = pressed ? "Последние 30 дней" : "Последние 30 дней"; // placeholder
    });
  }

  // Filtering function: показывает карточки, где есть совпадение в имени (категории / подкатегории / листы)
  function filterCategories(query) {
    const cards = root.querySelectorAll(".cat-card");
    cards.forEach(card => {
      let showCard = false;
      // check main category name
      const name = (card.querySelector(".cat-name")?.textContent || "").toLowerCase();
      if (name.includes(query)) showCard = true;

      // check subitems
      const subNames = Array.from(card.querySelectorAll(".sub-name, .leaf-link")).map(n => (n.textContent || "").toLowerCase());
      if (!showCard && subNames.some(n => n.includes(query))) showCard = true;

      // toggle visibility
      card.style.display = query ? (showCard ? "" : "none") : "";
      // if search matches subitems only — expand main so user sees matches
      const sublist = card.querySelector(".sublist");
      if (sublist) {
        if (query && showCard && !name.includes(query)) {
          sublist.classList.add("active");
          card.classList.add("open");
          const toggle = card.querySelector(".toggle");
          if (toggle) {
            toggle.setAttribute("aria-expanded", "true");
            const chev = toggle.querySelector(".chev");
            if (chev) chev.textContent = "▾";
          }
        } else if (!query) {
          sublist.classList.remove("active");
          card.classList.remove("open");
          const toggle = card.querySelector(".toggle");
          if (toggle) {
            toggle.setAttribute("aria-expanded", "false");
            const chev = toggle.querySelector(".chev");
            if (chev) chev.textContent = "▸";
          }
        }
      }
    });
  }

});
