// knowledge/js/main.js
import * as Data from './data.js';
import * as Renderer from './render.js';
import Modal from './modal.js';
import Viewer from './viewer.js';

const listEl = document.getElementById('source-list');
const loadingHint = document.getElementById('sources-loading');

let EDITING_SOURCE_ID = null;

async function refreshList(){
    try {
        loadingHint.style.display = 'inline';
        const sources = await Data.getSources();
        await Renderer.render(listEl, sources);
    } catch (err) {
        console.error(err);
        listEl.innerHTML = '<div class="text-danger">Ошибка загрузки</div>';
    } finally {
        loadingHint.style.display = 'none';
    }
}

/* Подписка на событие изменения источников (диспатчится из data.js) */
document.addEventListener('sources:changed', () => refreshList());

/* Универсальный делегированный обработчик кликов (карточки, кнопки, меню) */
document.addEventListener('click', async (e) => {
    // menu action
    const menuActionBtn = e.target.closest('button[data-menu-action]');
    if (menuActionBtn){
        const action = menuActionBtn.dataset.menuAction || menuActionBtn.getAttribute('data-menu-action');
        const id = menuActionBtn.dataset.id;
        handleMenuAction(action, id);
        document.querySelectorAll('.card-menu-popup').forEach(p=>p.classList.remove('visible'));
        return;
    }

    // toggle menu
    const menuToggle = e.target.closest('.card-menu-btn');
    if (menuToggle){
        const id = menuToggle.dataset.id;
        const popup = document.querySelector(`.card-menu-popup[data-for="${id}"]`);
        if (popup) {
            const vis = popup.classList.toggle('visible');
            document.querySelectorAll('.card-menu-popup').forEach(p => { if (p !== popup) p.classList.remove('visible'); });
        }
        return;
    }

    // specific buttons inside card (.btn-ghost with data-action)
    const actionBtn = e.target.closest('button[data-action]');
    if (actionBtn) {
        const id = actionBtn.dataset.id;
        const action = actionBtn.dataset.action;
        handleCardAction(action, id);
        return;
    }

    // click on card -> open viewer (ignore if clicked on control)
    const card = e.target.closest('.note-card');
    if (card) {
        if (e.target.closest('.btn-ghost') || e.target.closest('.card-menu-popup')) return;
        const id = card.dataset.id;
        const sources = await Data.getSources();
        const s = sources.find(x=>x.source_id===id);
        if (!s) { 
            showNotification('Источник не найден'); 
            return; 
        }
        Viewer.openWithSource(s);
    }
});

/* Обработчики карт (кнопки внизу карточки) */
async function handleCardAction(action, id){
    try {
        if (action === 'open') {
            const sources = await Data.getSources();
            const s = sources.find(x=>x.source_id===id);
            if (!s) return showNotification('Источник не найден');
            Viewer.openWithSource(s);
        }
        if (action === 'reindex') {
            await Data.reindexSource(id);
            showNotification('Переиндексация запущена');
        }
        if (action === 'remove') {
            if (!confirm('Удалить источник?')) return;
            await Data.removeSource(id);
            showNotification('Источник удалён');
        }
    } catch (err) {
        console.error(err);
        showNotification('Ошибка');
    }
}

/* Меню (трёхточки) действия */
async function handleMenuAction(action, id) {
    try {
        if (action === 'pin') {
            const sources = await Data.getSources();
            const s = sources.find(x => x.source_id===id);
            if (!s) return;
            await Data.updateSource(id, { pinned: !s.pinned });
            if (!s.pinned) {
                // если закрепили — поместим в начало в mock реализовано в data.updateSource
            }
        }
        if (action === 'edit') {
            const sources = await Data.getSources();
            const s = sources.find(x => x.source_id===id);
            if (!s) return showNotification('Источник не найден');
            EDITING_SOURCE_ID = id;
            Modal.open(s.type || 'text', s);
        }
        if (action === 'refresh') {
            await Data.reindexSource(id);
            showNotification('Переиндексация запущена');
        }
        if (action === 'delete') {
            if (!confirm('Удалить источник?')) return;
                await Data.removeSource(id);
                showNotification('Источник удалён');
        }
    } catch (err) {
        console.error(err);
        showNotification('Ошибка действия меню');
    }
}

/* Modal submit: создание / редактирование */
Modal.setOnSubmit(async (payload) => {
    try {
        if (payload.editingId) {
            if (payload.tab === 'text'){
                await Data.updateSource(payload.editingId, { title: payload.title, content: payload.content, preview: (payload.content || '').slice(0,400) });
            } else if (payload.tab === 'file') {
                if (payload.file) {
                    const res = await Data.uploadFile(payload.file);
                    await Data.updateSource(payload.editingId, { filename: payload.file.name, file_url: res.file_url || '', title: payload.file.name }).catch(() => {});
                }
            } else {
                await Data.updateSource(payload.editingId, { uri: payload.uri, title: payload.uri });
            }
            showNotification('Источник обновлён');
            Modal.close();
            return;
        }

        /* создание нового */
        if (payload.tab === 'text') {
            await Data.addSource({ type:'text', title: payload.title || (payload.content||'').slice(0,80), content: payload.content, preview: (payload.content||'').slice(0,400) });
            showNotification('Текст добавлен');
        } else if (payload.tab === 'file') {
            if (payload.file) {
                const res = await Data.uploadFile(payload.file);
                if (!res) {
                    showNotification('Ошибка при загрузке');
                } else if (!res.ok) {
                    if (res.error === 'images_not_allowed') {
                        showNotification('Загрузка изображений отключена. Выберите, пожалуйста, другой файл.');
                    } else {
                        showNotification('Ошибка при загрузке: ' + (res.error || 'unknown'));
                    }
                } else {
                    showNotification('Файл добавлен');
                }
            } else {
                showNotification('Файл не выбран');
            }
        } else {
            await Data.addSource({ type:'url', title: payload.uri, uri: payload.uri, preview: '' });
            showNotification('Ссылка добавлена');
        }
        Modal.close();
    } catch (err) {
        console.error(err);
        showNotification('Ошибка при добавлении / редактировании');
    }
});

/* Инициализация */
async function init() {
    Modal.init();
    Viewer.init();
    await refreshList();

    // кнопки сверху
    document.getElementById('add-knowledge-btn')?.addEventListener('click', () => Modal.open('text'));
    document.getElementById('reindex-all-btn')?.addEventListener('click', async () => {
        if (!confirm('Переиндексировать все источники?')) return;
        const sources = await Data.getSources();
        for (const s of sources) { Data.reindexSource(s.source_id); }
        showNotification('Переиндексация всех источников запущена');
    });
    document.getElementById('export-knowledge-btn')?.addEventListener('click', () => showNotification('Экспорт'));
}

init();
