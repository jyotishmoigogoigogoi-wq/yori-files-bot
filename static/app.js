const tg = window.Telegram.WebApp;
tg.expand();
tg.ready();

let jwtToken = null;
let currentFolderId = null;
let passcodeBuffer = "";
let contextTarget = null;

const API_BASE = '/api';

async function init() {
    try {
        const res = await fetch(`${API_BASE}/auth`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ initData: tg.initData })
        });
        
        if (!res.ok) throw new Error("Auth failed");
        
        const data = await res.json();
        jwtToken = data.token;
        
        document.getElementById('loading-screen').classList.add('hidden');
        
        if (data.has_passcode) {
            showLockScreen();
        } else {
            document.getElementById('app').classList.remove('hidden');
            loadFolder(null);
        }
    } catch (e) {
        tg.showAlert("Authentication error. Please restart the app.");
    }
}

function showLockScreen() {
    document.getElementById('lock-screen').classList.remove('hidden');
    const numpad = document.getElementById('numpad');
    numpad.innerHTML = '';
    
    [1,2,3,4,5,6,7,8,9,'',0,'⌫'].forEach(num => {
        const btn = document.createElement('div');
        if (num === '') {
            numpad.appendChild(btn);
            return;
        }
        btn.className = 'w-16 h-16 rounded-full flex items-center justify-center bg-[var(--tg-theme-secondary-bg-color)] active:bg-[var(--tg-theme-hint-color)] mx-auto';
        btn.innerText = num;
        btn.onclick = () => handleNumpad(num);
        numpad.appendChild(btn);
    });
}

async function handleNumpad(val) {
    if (val === '⌫') {
        passcodeBuffer = passcodeBuffer.slice(0, -1);
    } else if (passcodeBuffer.length < 4) {
        passcodeBuffer += val;
    }
    
    updatePasscodeUI();
    
    if (passcodeBuffer.length === 4) {
        try {
            const res = await fetch(`${API_BASE}/lock/verify`, {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${jwtToken}`
                },
                body: JSON.stringify({ passcode: passcodeBuffer })
            });
            if (res.ok) {
                const data = await res.json();
                jwtToken = data.token;
                document.getElementById('lock-screen').classList.add('hidden');
                document.getElementById('app').classList.remove('hidden');
                loadFolder(null);
            } else {
                tg.HapticFeedback.notificationOccurred('error');
                passcodeBuffer = "";
                updatePasscodeUI();
            }
        } catch(e) {
            passcodeBuffer = "";
            updatePasscodeUI();
        }
    }
}

function updatePasscodeUI() {
    const dots = document.getElementById('passcode-dots').children;
    for (let i = 0; i < 4; i++) {
        if (i < passcodeBuffer.length) {
            dots[i].classList.add('dot-filled');
        } else {
            dots[i].classList.remove('dot-filled');
        }
    }
}

async function api(path, options = {}) {
    options.headers = { ...options.headers, 'Authorization': `Bearer ${jwtToken}` };
    const res = await fetch(`${API_BASE}${path}`, options);
    if (!res.ok) throw new Error("API Error");
    return res.json();
}

async function loadFolder(folderId) {
    currentFolderId = folderId;
    const data = await api(`/vault${folderId ? '?folder_id='+folderId : ''}`);
    renderBreadcrumbs(data.breadcrumbs);
    renderContent(data.folders, data.files);
}

function renderBreadcrumbs(breadcrumbs) {
    const bcContainer = document.getElementById('breadcrumbs');
    bcContainer.innerHTML = '';
    
    const rootItem = document.createElement('div');
    rootItem.className = 'flex items-center gap-1 cursor-pointer font-bold';
    rootItem.innerHTML = `<i class="ph ph-house text-xl text-[var(--tg-theme-button-color)]"></i> <span class="${breadcrumbs.length === 0 ? 'text-[var(--tg-theme-text-color)]' : 'text-[var(--tg-theme-hint-color)]'}">Root</span>`;
    rootItem.onclick = () => loadFolder(null);
    bcContainer.appendChild(rootItem);

    breadcrumbs.forEach((bc, idx) => {
        const separator = document.createElement('i');
        separator.className = 'ph ph-caret-right text-[var(--tg-theme-hint-color)] text-sm mx-1';
        bcContainer.appendChild(separator);

        const item = document.createElement('div');
        const isLast = idx === breadcrumbs.length - 1;
        item.className = `cursor-pointer ${isLast ? 'text-[var(--tg-theme-text-color)] font-bold' : 'text-[var(--tg-theme-hint-color)]'}`;
        item.innerText = bc.name;
        item.onclick = () => loadFolder(bc.id);
        bcContainer.appendChild(item);
    });
}

function formatBytes(bytes) {
    if(bytes === 0) return '0 B';
    const k = 1024, sizes = ['B', 'KB', 'MB', 'GB', 'TB'], i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function getIconForMime(mime) {
    if(mime.startsWith('image/')) return 'ph-image';
    if(mime.startsWith('video/')) return 'ph-video-camera';
    if(mime.startsWith('audio/')) return 'ph-music-notes';
    if(mime.includes('pdf')) return 'ph-file-pdf';
    if(mime.includes('zip') || mime.includes('tar')) return 'ph-file-archive';
    return 'ph-file';
}

let longPressTimer;
function renderContent(folders, files) {
    const container = document.getElementById('vault-content');
    container.innerHTML = '';

    if (folders.length === 0 && files.length === 0) {
        container.innerHTML = `<div class="flex flex-col items-center justify-center h-full text-[var(--tg-theme-hint-color)] mt-20">
            <i class="ph ph-folder-open text-6xl mb-4 opacity-50"></i>
            <p>Folder is empty</p>
        </div>`;
        return;
    }

    const grid = document.createElement('div');
    grid.className = 'grid grid-cols-2 gap-4';

    folders.forEach(f => {
        const el = document.createElement('div');
        el.className = 'vault-item rounded-2xl p-4 flex flex-col items-center justify-center cursor-pointer shadow-sm relative';
        el.innerHTML = `<i class="ph ph-folder-fill text-5xl text-[var(--tg-theme-button-color)] mb-2"></i>
                        <span class="text-sm font-medium text-center line-clamp-1 w-full truncate">${f.name}</span>`;
        
        el.onclick = () => loadFolder(f.id);
        
        const bindContextMenu = (e) => {
            e.preventDefault();
            showContextMenu(e.pageX || e.touches[0].pageX, e.pageY || e.touches[0].pageY, 'folder', f.id, f.name);
        };
        el.oncontextmenu = bindContextMenu;
        el.addEventListener('touchstart', (e) => {
            longPressTimer = setTimeout(() => bindContextMenu(e), 600);
        });
        el.addEventListener('touchend', () => clearTimeout(longPressTimer));
        el.addEventListener('touchmove', () => clearTimeout(longPressTimer));

        grid.appendChild(el);
    });

    files.forEach(f => {
        const el = document.createElement('div');
        el.className = 'vault-item rounded-2xl p-4 flex flex-col items-center justify-center cursor-pointer shadow-sm relative';
        el.innerHTML = `<i class="ph ${getIconForMime(f.mime_type)} text-5xl text-gray-400 mb-2"></i>
                        <span class="text-sm font-medium text-center line-clamp-1 w-full truncate mb-1">${f.name}</span>
                        <span class="text-xs text-[var(--tg-theme-hint-color)]">${formatBytes(f.size)}</span>`;
        
        // THIS IS THE FIX FOR DOWNLOADING
        const downloadAction = () => {
            const dlUrl = `${window.location.origin}${API_BASE}/files/download/${f.id}?token=${jwtToken}`;
            tg.openLink(dlUrl);
        };
        
        el.onclick = downloadAction;

        const bindContextMenu = (e) => {
            e.preventDefault();
            showContextMenu(e.pageX || e.touches[0].pageX, e.pageY || e.touches[0].pageY, 'file', f.id, f.name, downloadAction);
        };
        el.oncontextmenu = bindContextMenu;
        el.addEventListener('touchstart', (e) => {
            longPressTimer = setTimeout(() => bindContextMenu(e), 600);
        });
        el.addEventListener('touchend', () => clearTimeout(longPressTimer));
        el.addEventListener('touchmove', () => clearTimeout(longPressTimer));

        grid.appendChild(el);
    });

    container.appendChild(grid);
}

function showContextMenu(x, y, type, id, name, downloadCb) {
    tg.HapticFeedback.impactOccurred('medium');
    const menu = document.getElementById('context-menu');
    menu.style.left = `${Math.min(x, window.innerWidth - 170)}px`;
    menu.style.top = `${Math.min(y, window.innerHeight - 100)}px`;
    menu.classList.remove('hidden');

    const dlBtn = document.getElementById('ctx-download');
    if(type === 'folder') dlBtn.classList.add('hidden');
    else {
        dlBtn.classList.remove('hidden');
        dlBtn.onclick = () => { menu.classList.add('hidden'); downloadCb(); };
    }

    document.getElementById('ctx-delete').onclick = async () => {
        menu.classList.add('hidden');
        tg.showConfirm(`Delete ${name}?`, async (ok) => {
            if(ok) {
                const endpoint = type === 'folder' ? `/folders/${id}` : `/files/${id}`;
                await api(endpoint, { method: 'DELETE' });
                loadFolder(currentFolderId);
            }
        });
    };
}

document.addEventListener('click', (e) => {
    if(!e.target.closest('#context-menu')) {
        document.getElementById('context-menu').classList.add('hidden');
    }
});

document.getElementById('btn-create-folder').onclick = () => {
    const name = window.prompt("Folder Name:");
    if (name) {
        api('/folders', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, parent_id: currentFolderId })
        }).then(() => loadFolder(currentFolderId));
    }
};

document.getElementById('file-input').onchange = async (e) => {
    const files = e.target.files;
    if(files.length === 0) return;

    tg.MainButton.setText("Uploading...").show().showProgress();

    for(let file of files) {
        const formData = new FormData();
        formData.append('file', file);
        if(currentFolderId) formData.append('folder_id', currentFolderId);

        await fetch(`${API_BASE}/files/upload`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${jwtToken}` },
            body: formData
        });
    }

    tg.MainButton.hide();
    loadFolder(currentFolderId);
    e.target.value = '';
};

init();
