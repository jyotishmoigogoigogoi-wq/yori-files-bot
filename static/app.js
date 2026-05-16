const tg = window.Telegram.WebApp;
tg.expand(); tg.ready();

let jwtToken = null, currentFolderId = null;
let selectMode = false, selectedFiles = new Set(), selectedFolders = new Set();
let clipboard = []; // {id, type, action}
let rawFolders = [], rawFiles = [];
const API_BASE = '/api';

async function init() {
    try {
        const res = await fetch(`${API_BASE}/auth`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ initData: tg.initData }) });
        const data = await res.json();
        jwtToken = data.token;
        document.getElementById('app').classList.remove('hidden');
        await updateStorage();
        loadFolder(null);
    } catch (e) { tg.showAlert("Auth error."); }
}

async function api(path, options = {}) {
    options.headers = { ...options.headers, 'Authorization': `Bearer ${jwtToken}` };
    const res = await fetch(`${API_BASE}${path}`, options);
    if (!res.ok) throw new Error(); return res.json();
}

// Formatters
function formatBytes(bytes) {
    if(bytes === 0) return '0 B';
    const k = 1024, sizes = ['B', 'KB', 'MB', 'GB', 'TB'], i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}
function getIconForMime(mime) {
    if(mime.startsWith('image/')) return 'ph-image';
    if(mime.startsWith('video/')) return 'ph-video-camera';
    if(mime.startsWith('audio/')) return 'ph-music-notes';
    return 'ph-file';
}

// Storage Logic
async function updateStorage() {
    const data = await api('/user');
    const pct = Math.min((data.storage_used / data.storage_limit) * 100, 100);
    document.getElementById('storage-bar').style.width = `${pct}%`;
    document.getElementById('storage-text').innerText = `${formatBytes(data.storage_used)} / ${formatBytes(data.storage_limit)}`;
}
document.getElementById('btn-store').onclick = () => document.getElementById('store-modal').classList.remove('hidden');

// Loading & Rendering
async function loadFolder(folderId) {
    currentFolderId = folderId;
    const data = await api(`/vault${folderId ? '?folder_id='+folderId : ''}`);
    rawFolders = data.folders; rawFiles = data.files;
    
    // Breadcrumbs
    const bc = document.getElementById('breadcrumbs');
    bc.innerHTML = `<div class="cursor-pointer font-bold ${data.breadcrumbs.length===0?'text-[var(--tg-theme-text-color)]':'text-[var(--tg-theme-button-color)]'}" onclick="loadFolder(null)"><i class="ph ph-house text-lg"></i> Root</div>`;
    data.breadcrumbs.forEach((b, i) => {
        bc.innerHTML += `<i class="ph ph-caret-right text-[var(--tg-theme-hint-color)] mx-1"></i>`;
        bc.innerHTML += `<div class="cursor-pointer ${i===data.breadcrumbs.length-1?'text-[var(--tg-theme-text-color)] font-bold':'text-[var(--tg-theme-button-color)]'}" onclick="loadFolder('${b.id}')">${b.name}</div>`;
    });
    
    renderContent();
}

function renderContent() {
    const query = document.getElementById('search-input').value.toLowerCase();
    const sortMode = document.getElementById('sort-select').value;
    
    let fld = rawFolders.filter(f => f.name.toLowerCase().includes(query));
    let fil = rawFiles.filter(f => f.name.toLowerCase().includes(query));
    
    const sorter = (a, b) => {
        if(sortMode === 'name') return a.name.localeCompare(b.name);
        if(sortMode === 'size') return (b.size || 0) - (a.size || 0);
        return new Date(b.created_at) - new Date(a.created_at);
    };
    fld.sort(sorter); fil.sort(sorter);

    const container = document.getElementById('vault-content');
    container.innerHTML = `<div class="grid grid-cols-2 gap-4"></div>`;
    const grid = container.firstChild;

    fld.forEach(f => {
        const el = document.createElement('div');
        el.className = 'bg-[var(--tg-theme-bg-color)] rounded-xl p-3 flex flex-col items-center justify-center cursor-pointer shadow-sm relative text-center';
        el.innerHTML = `<div class="checkbox-indicator absolute top-2 right-2 pointer-events-none"></div><i class="ph ph-folder-fill text-5xl text-[var(--tg-theme-button-color)] mb-2"></i><span class="text-xs font-medium line-clamp-2">${f.name}</span>`;
        el.onclick = () => selectMode ? toggleSelection('folder', f.id, el) : loadFolder(f.id);
        bindContextMenu(el, 'folder', f.id, f.name);
        grid.appendChild(el);
    });

    fil.forEach(f => {
        const el = document.createElement('div');
        el.className = 'bg-[var(--tg-theme-bg-color)] rounded-xl p-3 flex flex-col items-center justify-center cursor-pointer shadow-sm relative text-center';
        el.innerHTML = `<div class="checkbox-indicator absolute top-2 right-2 pointer-events-none"></div><i class="ph ${getIconForMime(f.mime_type)} text-5xl text-gray-400 mb-2"></i><span class="text-xs font-medium line-clamp-2">${f.name}</span><span class="text-[10px] text-[var(--tg-theme-hint-color)] mt-1">${formatBytes(f.size)}</span>`;
        
        el.onclick = () => {
            if(selectMode) return toggleSelection('file', f.id, el);
            const dlUrl = `${window.location.origin}${API_BASE}/files/download/${f.id}?token=${jwtToken}`;
            if(f.mime_type.startsWith('image/')) {
                document.getElementById('iv-img').src = dlUrl;
                document.getElementById('iv-name').innerText = f.name;
                document.getElementById('iv-dl').onclick = () => tg.openLink(dlUrl);
                document.getElementById('image-viewer').classList.remove('hidden');
            } else if(f.mime_type.startsWith('audio/')) {
                const au = document.getElementById('ap-audio');
                au.src = dlUrl; au.play();
                document.getElementById('ap-name').innerText = f.name;
                document.getElementById('audio-player').classList.remove('hidden');
            } else tg.openLink(dlUrl);
        };
        bindContextMenu(el, 'file', f.id, f.name);
        grid.appendChild(el);
    });
}

document.getElementById('search-input').onkeyup = renderContent;
document.getElementById('sort-select').onchange = renderContent;
function closeViewer() { document.getElementById('image-viewer').classList.add('hidden'); document.getElementById('iv-img').src = ''; }
function closeAudio() { document.getElementById('audio-player').classList.add('hidden'); document.getElementById('ap-audio').pause(); }

// Context & Select Logic
let longPressTimer;
function bindContextMenu(el, type, id, name) {
    const bind = (e) => {
        e.preventDefault(); tg.HapticFeedback.impactOccurred('medium');
        const menu = document.getElementById('context-menu');
        menu.style.left = `${Math.min(e.pageX||e.touches[0].pageX, window.innerWidth-170)}px`;
        menu.style.top = `${Math.min(e.pageY||e.touches[0].pageY, window.innerHeight-150)}px`;
        menu.classList.remove('hidden');
        
        document.getElementById('ctx-download').classList.toggle('hidden', type==='folder');
        document.getElementById('ctx-download').onclick = () => { menu.classList.add('hidden'); tg.openLink(`${window.location.origin}${API_BASE}/files/download/${id}?token=${jwtToken}`); };
        document.getElementById('ctx-delete').onclick = async () => { menu.classList.add('hidden'); tg.showConfirm("Delete?", async(ok)=>{ if(ok){ await api(type==='folder'?`/folders/${id}`:`/files/${id}`,{method:'DELETE'}); updateStorage(); loadFolder(currentFolderId); } }); };
        document.getElementById('ctx-rename').onclick = () => { menu.classList.add('hidden'); const nn = prompt("New name:", name); if(nn) api(`/rename/${type}/${id}`, {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name:nn})}).then(()=>loadFolder(currentFolderId)); };
    };
    el.oncontextmenu = bind;
    el.addEventListener('touchstart', (e) => { if(!selectMode) longPressTimer = setTimeout(()=>{ bind(e); toggleSelection(type,id,el); }, 500); });
    el.addEventListener('touchend', () => clearTimeout(longPressTimer));
    el.addEventListener('touchmove', () => clearTimeout(longPressTimer));
}
document.addEventListener('click', (e) => { if(!e.target.closest('#context-menu')) document.getElementById('context-menu').classList.add('hidden'); });

function toggleSelection(type, id, el) {
    if (!selectMode) { selectMode = true; document.getElementById('selection-bar').classList.remove('translate-y-full', 'hidden'); document.getElementById('fab-container').classList.add('translate-y-32'); }
    const set = type === 'folder' ? selectedFolders : selectedFiles;
    if (set.has(id)) { set.delete(id); el.classList.remove('ring-2', 'ring-[var(--tg-theme-button-color)]'); el.querySelector('.checkbox-indicator').innerHTML = ''; } 
    else { set.add(id); el.classList.add('ring-2', 'ring-[var(--tg-theme-button-color)]'); el.querySelector('.checkbox-indicator').innerHTML = '<i class="ph ph-check-circle text-xl text-[var(--tg-theme-button-color)] bg-white rounded-full"></i>'; }
    document.getElementById('selected-count').innerText = selectedFiles.size + selectedFolders.size;
    if (selectedFiles.size===0 && selectedFolders.size===0) cancelSelection();
}
function cancelSelection() { selectMode = false; selectedFiles.clear(); selectedFolders.clear(); document.getElementById('selection-bar').classList.add('translate-y-full'); setTimeout(()=>document.getElementById('selection-bar').classList.add('hidden'), 200); document.getElementById('fab-container').classList.remove('translate-y-32'); renderContent(); }

// Cut / Copy / Paste
document.getElementById('btn-cut').onclick = () => executeClipboard('cut');
document.getElementById('btn-copy').onclick = () => executeClipboard('copy');
function executeClipboard(action) {
    clipboard = [];
    selectedFiles.forEach(id => clipboard.push({type: 'file', id, action}));
    selectedFolders.forEach(id => clipboard.push({type: 'folder', id, action}));
    cancelSelection();
    document.getElementById('paste-count').innerText = clipboard.length;
    document.getElementById('paste-bar').classList.remove('hidden');
}
function clearClipboard() { clipboard = []; document.getElementById('paste-bar').classList.add('hidden'); }
document.getElementById('btn-do-paste').onclick = async () => {
    tg.MainButton.setText("Pasting...").show().showProgress();
    await api('/paste', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({target_folder: currentFolderId, items: clipboard})});
    clearClipboard(); tg.MainButton.hide(); updateStorage(); loadFolder(currentFolderId);
};

// Bulk Delete
document.getElementById('btn-bulk-delete').onclick = () => { tg.showConfirm(`Delete items?`, async (ok) => { if(ok) { await api('/bulk/delete', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ file_ids: Array.from(selectedFiles), folder_ids: Array.from(selectedFolders) }) }); updateStorage(); cancelSelection(); loadFolder(currentFolderId); } }); };
document.getElementById('btn-zip').onclick = () => {
    if (selectedFiles.size === 0) {
        tg.showAlert("Please select at least one file to ZIP.");
        return;
    }
    const ids = Array.from(selectedFiles).join(',');
    const dlUrl = `${window.location.origin}${API_BASE}/bulk/zip?ids=${ids}&token=${jwtToken}`;
    tg.openLink(dlUrl);
    cancelSelection();
};
// Folders & Upload
document.getElementById('btn-create-folder').onclick = () => { const name = prompt("Folder Name:"); if(name) api('/folders', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name, parent_id:currentFolderId})}).then(()=>loadFolder(currentFolderId)); };
document.getElementById('file-input').onchange = async (e) => {
    const files = e.target.files; if(!files.length) return;
    for(let f of files) if(f.size > 40*1024*1024) { tg.showAlert(`❌ "${f.name}" is over 40MB limit.`); return e.target.value=''; }
    tg.MainButton.setText("Uploading...").show().showProgress();
    for(let f of files) { const fd = new FormData(); fd.append('file', f); if(currentFolderId) fd.append('folder_id', currentFolderId); await fetch(`${API_BASE}/files/upload`, {method:'POST', headers:{'Authorization':`Bearer ${jwtToken}`}, body:fd}); }
    tg.MainButton.hide(); updateStorage(); loadFolder(currentFolderId); e.target.value='';
};
init();
