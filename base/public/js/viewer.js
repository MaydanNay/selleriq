// knowledge/js/viewer.js
import { isSafeUrl } from './render.js';

const sel = q => document.querySelector(q);
const backdrop = sel('#viewer-backdrop');
const body = sel('#viewer-body');
const titleEl = sel('#viewer-title');
const closeBtn = sel('#viewer-close');
const headerDownloadWrap = sel('#viewer-download-wrap');
const headerDownloadBtn = sel('#viewer-download-btn');
const headerDownloadMenu = sel('#viewer-download-menu');

let _downloadKeyHandler = null;
let _downloadOutsideClickHandler = null;

async function fetchDetailsIfNeeded(s) {
    if (s && (s.preview_pdf_url || s.downloads || s.type === 'text')) return s;
    if (!s || !s.source_id) return null;
    try {
        const resp = await fetch(`/knowledge/view?source_id=${encodeURIComponent(s.source_id)}`, { credentials: 'same-origin' });
        if (!resp.ok) return null;
        const data = await resp.json();
        if (data && data.ok) return data;
    } catch (e) {
        console.error('Failed to fetch source details', e);
    }
    return null;
}

function makeButtonLink(text, href, opts = {}) {
    const a = document.createElement('a');
    a.className = 'btn-ghost';
    a.textContent = text;
    a.href = href || '#';
    a.target = opts.target || '_blank';
    a.rel = 'noopener noreferrer';
    if (opts.download) a.setAttribute('download', opts.download === true ? '' : opts.download);
    return a;
}

function closeHeaderDownloadMenu() {
    if (!headerDownloadWrap || !headerDownloadMenu || !headerDownloadBtn) return;
    headerDownloadMenu.style.display = 'none';
    try { headerDownloadBtn.setAttribute('aria-expanded', 'false'); } catch(e) {}
    if (_downloadKeyHandler) {
        document.removeEventListener('keydown', _downloadKeyHandler);
        _downloadKeyHandler = null;
    }
    if (_downloadOutsideClickHandler) {
        document.removeEventListener('click', _downloadOutsideClickHandler);
        _downloadOutsideClickHandler = null;
    }
}

function clearHeaderDownload() {
    if (!headerDownloadWrap) return;
    headerDownloadWrap.style.display = 'none';

    // remove event listener if added via addEventListener
    try {
        if (headerDownloadBtn && headerDownloadBtn._handler) {
            headerDownloadBtn.removeEventListener('click', headerDownloadBtn._handler);
            headerDownloadBtn._handler = null;
        }
    } catch (e){}
    closeHeaderDownloadMenu();
}


async function openWithSource(rawSource) {
    clearHeaderDownload();

    backdrop.style.display = 'flex';
    body.innerHTML = '<div class="small-muted">Загрузка...</div>';
    titleEl.textContent = rawSource.title || rawSource.name || 'Источник';

    const s = await fetchDetailsIfNeeded(rawSource);
    if (!s) {
        body.innerHTML = '<div class="small-muted">Не удалось загрузить</div>';
        clearHeaderDownload();
        return;
    }

    // TEXT
    if ((s.type || '').includes('text')) {
        const content = s.content || s.preview || '';
        body.innerHTML = `<pre style="white-space:pre-wrap;line-height:1.45;">${escapeHtml(content)}</pre>`;
        clearHeaderDownload();
        return;
    }

    // FILE
    if ((s.type || '').includes('file') || s.type === 'file') {
        const previewPdf = s.preview_pdf_url || (s.file_url ? `${s.file_url}?format=pdf` : null);
        const downloads = Array.isArray(s.downloads) ? s.downloads : [
            { label: 'Оригинал', url: s.download_url || (s.file_url ? s.file_url.replace('/file/', '/download/') : null) },
            { label: 'PDF', url: previewPdf }
        ];

        // фильтруем валидные ссылки
        const validDownloads = (downloads || []).filter(d => d && d.url);

        body.innerHTML = '';

        // show hint when preview not available and server gave generation status
        if (!previewPdf && s.preview_pdf_generation) {
            const warn = document.createElement('div');
            warn.style.marginTop = '8px';
            warn.style.color = '#ffb86b';
            if (s.preview_pdf_generation === 'skipped_no_soffice') {
                warn.textContent = 'Предпросмотр не сгенерирован: в серверном окружении отсутствует libreoffice (soffice).';
            } else if (s.preview_pdf_generation === 'failed') {
                warn.textContent = 'Предпросмотр не сгенерирован: попытка конвертации завершилась с ошибкой.';
            }
            body.appendChild(warn);
        }

        if (previewPdf && isSafeUrl(previewPdf)) {
            const iframe = document.createElement('iframe');
            iframe.style.width = '100%';
            iframe.style.height = '60vh';
            iframe.style.border = '0';
            iframe.src = previewPdf;
            body.appendChild(iframe);
        } else {
            const hint = document.createElement('div');
            hint.className = 'small-muted';
            hint.innerHTML = 'Предпросмотр недоступен. Ниже - ссылки для скачивания / открытия.';
            body.appendChild(hint);
        }

        // toolbar with open + downloads
        const toolbar = document.createElement('div');
        toolbar.style.marginTop = '8px';
        toolbar.style.display = 'flex';
        toolbar.style.gap = '8px';
        toolbar.style.flexWrap = 'wrap';
        toolbar.style.alignItems = 'center';

        // Open in new tab (first available preview/pdf/original)
        const primaryOpenUrl = (previewPdf || validDownloads.find(d => d && d.url)?.url) || '#';
        const openBtn = makeButtonLink('Открыть в новой вкладке', primaryOpenUrl, { target: '_blank' });
        toolbar.appendChild(openBtn);

        // --- new: show extracted text toggle button ---
        const showTextBtn = document.createElement('button');
        showTextBtn.type = 'button';
        showTextBtn.className = 'btn-ghost';
        showTextBtn.textContent = 'Показать извлечённый текст';
        showTextBtn.style.whiteSpace = 'nowrap';
        showTextBtn.setAttribute('aria-expanded', 'false');
        toolbar.appendChild(showTextBtn);

        // container for extracted text (will be appended below toolbar)
        let extractedContainer = null;

        function createExtractedContainer(text) {
            const sep = document.createElement('hr');
            sep.style.margin = '12px 0';

            const textTitle = document.createElement('div');
            textTitle.style.fontWeight = '600';
            textTitle.style.marginBottom = '6px';
            textTitle.textContent = 'Текст (извлечённый):';

            const txtWrap = document.createElement('pre');
            txtWrap.style.whiteSpace = 'pre-wrap';
            txtWrap.style.lineHeight = '1.4';
            txtWrap.style.maxHeight = '35vh';
            txtWrap.style.overflow = 'auto';
            txtWrap.style.background = 'transparent';
            txtWrap.textContent = text;

            const wrapper = document.createElement('div');
            wrapper.appendChild(sep);
            wrapper.appendChild(textTitle);
            wrapper.appendChild(txtWrap);
            return wrapper;
        }

        // toggle handler
        const showTextHandler = (ev) => {
            ev.preventDefault();
            ev.stopPropagation();

            // if no extracted text available
            if (!s.extracted_text) {
                const hint = document.createElement('div');
                hint.className = 'small-muted';
                hint.style.marginTop = '8px';
                hint.textContent = 'Извлечённый текст недоступен.';
                body.appendChild(hint);
                setTimeout(() => {
                    try { hint.remove(); } catch(e) {}
                }, 3000);
                return;
            }

            // if container already present -> toggle visibility
            if (extractedContainer && body.contains(extractedContainer)) {
                extractedContainer.remove();
                showTextBtn.textContent = 'Показать извлечённый текст';
                showTextBtn.setAttribute('aria-expanded', 'false');
                return;
            }

            // create + append and scroll into view
            extractedContainer = createExtractedContainer(s.extracted_text);
            body.appendChild(extractedContainer);
            showTextBtn.textContent = 'Свернуть текст';
            showTextBtn.setAttribute('aria-expanded', 'true');
            extractedContainer.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        };
        showTextBtn.addEventListener('click', showTextHandler);

        // reset previous header download state
        if (headerDownloadWrap && headerDownloadMenu && headerDownloadBtn) {
            headerDownloadMenu.innerHTML = '';
            headerDownloadWrap.style.display = 'none';
            headerDownloadBtn.setAttribute('aria-expanded', 'false');
        }

        if (validDownloads.length > 0 && headerDownloadWrap && headerDownloadBtn && headerDownloadMenu) {
            validDownloads.forEach(d => {
                const item = document.createElement('a');
                item.setAttribute('role','menuitem');
                item.href = d.url;
                item.target = '_blank';
                item.rel = 'noopener noreferrer';
                item.textContent = d.label ? d.label : d.url;
                item.style.display = 'block';
                item.style.padding = '8px 10px';
                item.style.textDecoration = 'none';
                item.style.color = 'inherit';
                item.setAttribute('download', '');

                // close menu after click
                item.addEventListener('click', () => closeHeaderDownloadMenu());
                headerDownloadMenu.appendChild(item);
            });

            // show header download button
            headerDownloadWrap.style.display = '';

            // If only one download option — make button perform direct download (UX convenience)
            if (validDownloads.length === 1) {
                const singleUrl = validDownloads[0].url;

                const singleHandler = (ev) => {
                    ev.stopPropagation();
                    window.open(singleUrl, '_blank', 'noopener');
                };
                headerDownloadBtn._handler = singleHandler;
                headerDownloadBtn.addEventListener('click', singleHandler);
            } else {
                function _localOnKey(ev) {
                    if (ev.key === 'Escape' && headerDownloadMenu.style.display === 'block') {
                        closeHeaderDownloadMenu();
                    }
                }

                const toggleHandler = (ev) => {
                    ev.stopPropagation();
                    const visible = headerDownloadMenu.style.display === 'block';
                    if (visible) {
                        closeHeaderDownloadMenu();
                    } else {
                        headerDownloadMenu.style.display = 'block';
                        headerDownloadBtn.setAttribute('aria-expanded', 'true');
                        if (!_downloadKeyHandler) {
                            _downloadKeyHandler = _localOnKey;
                            document.addEventListener('keydown', _downloadKeyHandler);
                        }
                        if (_downloadOutsideClickHandler) {
                            document.removeEventListener('click', _downloadOutsideClickHandler);
                            _downloadOutsideClickHandler = null;
                        }
                        _downloadOutsideClickHandler = (ev) => {
                            if (!headerDownloadWrap.contains(ev.target)) {
                                closeHeaderDownloadMenu();
                            }
                        };
                        document.addEventListener('click', _downloadOutsideClickHandler);
                    }
                };
                headerDownloadBtn._handler = toggleHandler;
                headerDownloadBtn.addEventListener('click', toggleHandler);
            }
        } else {
            if (headerDownloadWrap) headerDownloadWrap.style.display = 'none';
        }
        body.appendChild(toolbar);
        return;
    }

    // URL
    if ((s.type || '').includes('url') || (s.type || '').includes('site')) {
        body.innerHTML = '';
        const wrap = document.createElement('div');
        wrap.style.marginBottom = '8px';
        wrap.style.color = 'var(--muted)';
        const strong = document.createElement('strong');
        strong.textContent = 'URL: ';
        const a = document.createElement('a');
        a.target = '_blank'; 
        a.rel = 'noopener noreferrer';
        a.textContent = s.uri || s.file_url || '';
        if (isSafeUrl(s.uri || s.file_url)) a.href = s.uri || s.file_url;
        wrap.appendChild(strong);
        wrap.appendChild(a);
        body.appendChild(wrap);

        const pr = document.createElement('div');
        pr.style.color = 'var(--muted)';
        pr.textContent = s.preview || '';
        body.appendChild(pr);

        clearHeaderDownload();
        return;
    }
    body.innerHTML = '<div class="small-muted">Невозможно отобразить</div>';
    clearHeaderDownload();
}

function close() {
    backdrop.style.display = 'none';
    body.innerHTML = '';
    titleEl.textContent = 'Просмотр источника';
    
    // hide & clear header download
    clearHeaderDownload();

    if (_downloadOutsideClickHandler) {
        document.removeEventListener('click', _downloadOutsideClickHandler);
        _downloadOutsideClickHandler = null;
    }
    if (_downloadKeyHandler) {
        document.removeEventListener('keydown', _downloadKeyHandler);
        _downloadKeyHandler = null;
    }
}

function escapeHtml(s) {
    return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function init() {
    closeBtn?.addEventListener('click', close);
    backdrop?.addEventListener('click', (e) => { if (e.target === backdrop) close(); });
}

export default { init, openWithSource, close };
