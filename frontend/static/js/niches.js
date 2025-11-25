// frontend/static/js/niches.js

document.addEventListener("DOMContentLoaded", () => {
  // toggle sublists
  document.querySelectorAll(".toggle").forEach(btn => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.id;
      const sub = document.querySelector(`.sublist[data-parent="${id}"]`);
      if (!sub) return;
      sub.classList.toggle("active");
      btn.textContent = sub.classList.contains("active") ? "▾" : "▸";
    });
  });

  // сохранить выбор
  const saveBtn = document.getElementById("saveBtn");
  const status = document.getElementById("status");

  saveBtn.addEventListener("click", async () => {
    const checked = Array.from(document.querySelectorAll(".sub-checkbox:checked"))
      .map(i => i.value);

    status.textContent = "Сохраняю...";
    try {
      const res = await fetch("/api/niches/select", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ selected: checked })
      });
      const j = await res.json();
      if (j.success) {
        status.textContent = `Сохранено: ${j.selected.length} ${j.selected.length === 1 ? "пункт" : "пунктов"}`;
      } else {
        status.textContent = "Ошибка сохранения";
      }
    } catch (e) {
      console.error(e);
      status.textContent = "Ошибка сети";
    }
    setTimeout(()=> status.textContent="", 3000);
  });
});
