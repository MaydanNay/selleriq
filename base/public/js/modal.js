// knowledge/js/modal.js
let _onSubmit = null;
let _currentTab = 'text';
let _editingId = null;

const sel = (q) => document.querySelector(q);

const addModal = sel('#add-modal');
const addBackdrop = sel('#add-backdrop');
const addTabs = sel('#add-tabs');
const addSubmitBtn = sel('#add-modal-submit');
const addCancelBtn = sel('#add-modal-cancel');
const addCloseBtn = sel('#add-modal-close');

const m_text_title = sel('#modal-text-title');
const m_text_body  = sel('#modal-src-text');
const m_file_input = sel('#modal-src-file');
const m_choose_file = sel('#modal-choose-file');
const m_chosen_filename = sel('#modal-chosen-filename');
const m_site_input = sel('#modal-site-url');

// extensions of image types to filter by extension (fallback)
const IMAGE_EXTS = ['.png','.jpg','.jpeg','.gif','.bmp','.webp','.svg','.tiff','.tif'];

// only replace updateSubmit and small behavior; rest file stays as-is
function updateSubmit(){
    let ok = false;
    if (_currentTab === 'text') {
        ok = !!(m_text_body && m_text_body.value.trim().length > 0);
    } else if (_currentTab === 'file') {
        if (_editingId) {
            ok = true;
        } else {
            ok = !!(m_file_input && m_file_input.files && m_file_input.files.length > 0);
        }
    } else if (_currentTab === 'site') {
        ok = !!(m_site_input && m_site_input.value.trim().length > 0);
    }
    addSubmitBtn.disabled = !ok;
}


function open(tab='text', source=null){
    _currentTab = tab;
    _editingId = source ? source.source_id : null;
    addModal.classList.add('visible');
    addModal.setAttribute('aria-hidden','false');

    // set active tab
    Array.from(addTabs.querySelectorAll('button')).forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
    Array.from(document.querySelectorAll('[data-tab-body]')).forEach(el => {
        el.style.display = (el.getAttribute('data-tab-body') === tab ? 'block' : 'none');
    });

    // prefill if editing
    if (source){
        if (source.type === 'text'){
            m_text_title.value = source.title || '';
            m_text_body.value = source.content || source.preview || '';
        } else if (source.type === 'file'){
            m_chosen_filename.textContent = source.filename || source.title || '';
        } else if (source.type === 'url'){
            m_site_input.value = source.uri || source.title || '';
        }
    }
    updateSubmit();
}

function close(){
    addModal.classList.remove('visible');
    addModal.setAttribute('aria-hidden','true');
    m_text_title.value = '';
    m_text_body.value = '';
    m_file_input.value = '';
    m_chosen_filename.textContent = '';
    m_site_input.value = '';
    _editingId = null;
    addSubmitBtn.disabled = true;
}


function setOnSubmit(cb) { 
    _onSubmit = cb; 
}


function init() {
    // tab clicks
    addTabs?.addEventListener('click', (ev) => {
        const b = ev.target.closest('button[data-tab]');
        if (!b) return;

        _currentTab = b.dataset.tab;
        Array.from(addTabs.querySelectorAll('button'))
            .forEach(x => x.classList.toggle('active', x === b));
        Array.from(document.querySelectorAll('[data-tab-body]'))
            .forEach(el => el.style.display = (el.getAttribute('data-tab-body') === _currentTab ? 'block' : 'none'));
        updateSubmit();
    });

    // file chooser
    m_choose_file?.addEventListener('click', () => m_file_input?.click());

    function isImageFile(file) {
        // 1) try MIME type first
        if (file && file.type && file.type.startsWith('image/')) return true;

        // 2) fallback by extension
        const name = (file && file.name || '').toLowerCase();
        for (const e of IMAGE_EXTS) if (name.endsWith(e)) return true;
        return false;
    }

    m_file_input?.addEventListener('change', () => {
        const files = Array.from(m_file_input.files || []);
        if (!files.length) {
            m_chosen_filename.textContent = '';
            updateSubmit();
            return;
        }

        // filter out images
        const nonImages = files.filter(f => !isImageFile(f));
        const imageCount = files.length - nonImages.length;

        if (nonImages.length === 0) {
            m_file_input.value = '';
            m_chosen_filename.textContent = '';
            showNotification('Загрузка изображений временно отключена. Пожалуйста, выберите другой файл.');
            updateSubmit();
            return;
        }

        // если был выбран микс — используем только non-images (берём первый файл)
        if (imageCount > 0) {
            showNotification(`Изображения были отброшены (${imageCount}). Загружен(ы) только недопустимые файлы.`);
        }

        // сохраняем первый non-image файл
        const f = nonImages[0];
        try {
            const dt = new DataTransfer();
            dt.items.add(f);
            m_file_input.files = dt.files;
        } catch (e){}

        m_chosen_filename.textContent = f ? f.name : '';
        updateSubmit();
    });

    [m_text_body, m_text_title, m_site_input].forEach(inp=> inp && inp.addEventListener('input', updateSubmit));

    addCloseBtn?.addEventListener('click', close);
    addCancelBtn?.addEventListener('click', close);
    addBackdrop?.addEventListener('click', (e)=> { if (e.target === addBackdrop) close(); });

    addSubmitBtn?.addEventListener('click', async (ev)=>{
        ev.preventDefault();
        addSubmitBtn.disabled = true;
        try {
        const tab = _currentTab;
        const payload = { tab, editingId: _editingId };
        if (tab === 'text'){
            payload.title = m_text_title.value || '';
            payload.content = m_text_body.value || '';
            payload.type = 'text';
        } else if (tab === 'file'){
            payload.file = (m_file_input.files && m_file_input.files[0]) || null;
            payload.type = 'file';
        } else {
            payload.uri = m_site_input.value || '';
            payload.type = 'url';
        }

        if (_onSubmit) await _onSubmit(payload);
        } finally {
        addSubmitBtn.disabled = false;
        }
    });
}

export default { init, open, close, setOnSubmit, updateSubmit };
