// knowledge/js/data.js

/* Вспомогательное: диспатчим событие при изменении источников */
function notifyChange() {
    document.dispatchEvent(new CustomEvent('sources:changed'));
}


function handleFetchError(resp){
    return resp.text().then(txt => {
        const msg = txt || resp.statusText || `status ${resp.status}`;
        throw new Error(msg);
    }).catch(()=> { throw new Error(resp.statusText || `status ${resp.status}`); });
}


export async function getSources(){
    const resp = await fetch('/knowledge/list', { credentials:'same-origin' });
    if (!resp.ok) await handleFetchError(resp);

    const data = await resp.json();
    if (Array.isArray(data)) return data;
    if (data && data.ok && Array.isArray(data.sources)) return data.sources;
    return [];
}


export async function addSource(obj){
    const resp = await fetch('/knowledge/add', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify(obj)
    });
    if (!resp.ok) await handleFetchError(resp);

    const data = await resp.json();
    notifyChange();
    return data;
}


// upload file to backend
export async function uploadFile(file){
    const fd = new FormData();
    fd.append('file', file);
    const resp = await fetch('/knowledge/upload', {
        method: 'POST',
        credentials: 'same-origin',
        body: fd
    });
    if (!resp.ok) await handleFetchError(resp);
    const data = await resp.json();
    notifyChange();
    return data;
}


export async function updateSource(id, updates){
    const resp = await fetch('/knowledge/update', {
        method: 'POST',
        credentials:'same-origin',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ source_id: id, ...updates })
    });
    if (!resp.ok) await handleFetchError(resp);
    const data = await resp.json();
    notifyChange();
    return data;
}

export async function removeSource(id){
    const resp = await fetch('/knowledge/remove', {
        method:'POST',
        credentials:'same-origin',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ source_id: id })
    });
    if (!resp.ok) await handleFetchError(resp);
    notifyChange();
    return true;
}

export async function reindexSource(id) {
    const resp = await fetch('/knowledge/reindex', {
        method:'POST',
        credentials:'same-origin',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ source_id: id })
    });
    if (!resp.ok) await handleFetchError(resp);
    const data = await resp.json();
    notifyChange();
    return data;
}
