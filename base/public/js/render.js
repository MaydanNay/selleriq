// knowledge/js/render.js
import { getSources } from './data.js';

function esc(s) { 
    return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); 
}
function shortText(s, len=240) { 
    if(!s) return ''; return s.length>len ? s.slice(0,len).trim() + '…' : s; 
}

export function isSafeUrl(u){
    if (!u) return false;
    try {
        const url = new URL(u, location.href);
        return url.protocol === 'http:' || url.protocol === 'https:' || url.protocol === 'blob:';
    } catch(e){
        return false;
    }
}
function setLinkAttr(aEl, url){
    if (isSafeUrl(url)) aEl.href = url;
    else aEl.removeAttribute('href');
}


export function createCardElement(s){
    const card = document.createElement('div');
    card.className = 'note-card clickable' + (s.pinned ? ' pinned' : '');
    card.dataset.id = s.source_id;

    const t = (s.type || '').toLowerCase();
    const title = s.title || s.uri || s.filename || s.source_id;
    const metaText = `${t || 'unknown'} • ${s.status || '-'}${s.last_updated ? ' • ' + s.last_updated : ''}`;
    const progress = Number(s.progress || 0);

    // badge
    const badge = document.createElement('div');
    badge.className = 'note-badge';
    badge.textContent = (t==='text' ? 'Текст' : (t==='file' ? 'Файл' : (t==='url' || t==='site' ? 'Ссылка' : 'Источник')));
    card.appendChild(badge);

    if (s.pinned){
        const pl = document.createElement('div'); 
        pl.className = 'pinned-label'; 
        pl.textContent = 'Закреплено';
        card.appendChild(pl);
    }

    // menu btn
    const menuBtn = document.createElement('button'); 
    menuBtn.className='card-menu-btn'; 
    menuBtn.type='button';
    menuBtn.title = 'Меню'; 
    menuBtn.innerText = '⋯'; 
    menuBtn.dataset.id = s.source_id;
    card.appendChild(menuBtn);

    // menu popup
    const menu = document.createElement('div'); 
    menu.className = 'card-menu-popup'; 
    menu.dataset.for = s.source_id;

    function addMenuBtn(text, action, color){
        const b = document.createElement('button');
        b.dataset.menuAction = action;
        b.dataset.id = s.source_id;
        b.textContent = text;
        if (color) b.style.color = color;
        menu.appendChild(b);
    }
    addMenuBtn(s.pinned ? 'Открепить' : 'Закрепить', 'pin');
    addMenuBtn('Редактировать', 'edit');
    addMenuBtn('Обновить', 'refresh');
    addMenuBtn('Удалить', 'delete', '#ff8b8b');

    card.appendChild(menu);

    const head = document.createElement('div'); 
    head.className = 'note-head';

    const ttl = document.createElement('div'); 
    ttl.className = 'note-title'; 
    ttl.textContent = title;
    head.appendChild(ttl);
    card.appendChild(head);

    const excerpt = document.createElement('div'); 
    excerpt.className = 'note-excerpt';
    const preview = s.preview || s.content || s.summary || s.uri || s.filename || '';
    if (t.includes('text')) {
        excerpt.innerHTML = esc(shortText(preview || s.content || '-', 500));
    } else if (t.includes('file')) {
        excerpt.innerHTML = `<strong>Файл:</strong> ${esc(s.filename || preview || '-')}`;
    } else if (t.includes('url')) {
        const strong = document.createElement('strong'); strong.textContent = 'URL: ';
        const a = document.createElement('a');
        a.target = '_blank'; a.rel = 'noopener noreferrer';
        a.textContent = s.uri || '';
        if (isSafeUrl(s.uri)) a.href = s.uri;
        excerpt.appendChild(strong);
        excerpt.appendChild(a);
    }else {
        excerpt.textContent = preview || '';
    }
    card.appendChild(excerpt);

    const meta = document.createElement('div'); 
    meta.className = 'note-meta';

    const leftMeta = document.createElement('div'); 
    leftMeta.className = 'note-meta-left small-muted'; 
    leftMeta.textContent = metaText;

    const controls = document.createElement('div'); 
    controls.className = 'note-actions';

    const prog = document.createElement('div'); 
    prog.className = 'progress-bar'; 
    prog.title = 'Индексация';

    const fill = document.createElement('div'); 
    fill.className = 'progress-fill'; 
    fill.style.width = progress + '%';

    prog.appendChild(fill);

    controls.appendChild(prog);
    meta.appendChild(leftMeta);
    meta.appendChild(controls);
    card.appendChild(meta);

    return card;
}

export async function render(container, sources){
    container.innerHTML = '';
    if (!sources || !sources.length){
        container.innerHTML = '<div class="small-muted">Источники не добавлены</div>';
        return;
    }
    const frag = document.createDocumentFragment();
    sources.forEach(s => frag.appendChild(createCardElement(s)));
    container.appendChild(frag);
}
