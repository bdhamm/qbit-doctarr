// Stalled Torrent Monitor page: fetch current tracked torrents,
// render as a sortable/filterable table with per-row and bulk actions.
//
// Requires common.js (escapeHTML) to be loaded first.

let allStalledTorrents = [];
let currentSortField = null;
let currentSortDir = 'asc';
let selectedHashes = new Set();
let visibleHashes = [];

async function fetchStats() {
    try {
        const response = await fetch('/api/stats');
        const data = await response.json();
        allStalledTorrents = data.stalled;
        document.getElementById('stalled-count').innerText = allStalledTorrents.length;
        renderTorrents();
    } catch (e) { console.error("Failed to fetch stats", e); }
}

function clearSelectionAndRender() {
    selectedHashes.clear();
    renderTorrents();
}

function renderTorrents() {
    const searchInput = document.getElementById('search-input').value.toLowerCase();
    const statusFilter = document.getElementById('status-filter').value;
    const tbody = document.getElementById('stalled-tbody');

    let filteredData = allStalledTorrents.filter(t => {
        const name = (t.torrent_name || t.hash || '').toLowerCase();
        const status = (t.status || '').toLowerCase();
        if (statusFilter && status !== statusFilter) return false;
        return name.includes(searchInput) || status.includes(searchInput);
    });

    if (currentSortField !== null) {
        filteredData.sort((a, b) => {
            let valA, valB;
            if (currentSortField === 'name') {
                valA = (a.torrent_name || a.hash || '').toLowerCase();
                valB = (b.torrent_name || b.hash || '').toLowerCase();
            } else if (currentSortField === 'status') {
                valA = (a.status || '').toLowerCase();
                valB = (b.status || '').toLowerCase();
            } else if (currentSortField === 'first_seen') {
                valA = a.first_seen || '';
                valB = b.first_seen || '';
            }
            if (valA < valB) return currentSortDir === 'asc' ? -1 : 1;
            if (valA > valB) return currentSortDir === 'asc' ? 1 : -1;
            return 0;
        });
    }

    visibleHashes = filteredData.map(t => t.hash);
    syncSelectAll();

    if (filteredData.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-4">No matching torrents found.</td></tr>';
        updateBulkBar();
        return;
    }

    tbody.innerHTML = filteredData.map(t => {
        const displayName = escapeHTML(t.torrent_name || t.hash || '');
        const statusText = escapeHTML(t.status || '');
        const firstSeen = escapeHTML(t.first_seen || '');
        const badge = t.status === 'meta_stall' ? 'bg-warning text-dark'
                    : t.status === 'dl_stall' ? 'bg-danger'
                    : 'bg-info';
        const isChecked = selectedHashes.has(t.hash) ? 'checked' : '';
        return `
        <tr>
            <td class="align-middle py-1"><input type="checkbox" class="form-check-input row-check" data-hash="${t.hash}" ${isChecked} onchange="toggleRow('${t.hash}', this.checked)"></td>
            <td class="text-truncate align-middle py-1" style="max-width: 800px;" title="${displayName}">${displayName}</td>
            <td class="align-middle py-1"><span class="badge ${badge}">${statusText}</span></td>
            <td class="text-nowrap align-middle py-1">${firstSeen}</td>
            <td class="align-middle py-1">
                <button class="btn btn-sm btn-outline-danger" onclick="runAction('${t.hash}', '${displayName.replace(/'/g, "\\'")}')" title="Blocklist torrent and re-search in *arr"><i class="bi bi-shield-slash"></i> Blocklist &amp; Re-search</button>
            </td>
        </tr>`;
    }).join('');

    updateBulkBar();
}

function toggleRow(hash, checked) {
    if (checked) selectedHashes.add(hash);
    else selectedHashes.delete(hash);
    syncSelectAll();
    updateBulkBar();
}

function toggleSelectAll(checked) {
    if (checked) visibleHashes.forEach(h => selectedHashes.add(h));
    else visibleHashes.forEach(h => selectedHashes.delete(h));
    renderTorrents();
}

function syncSelectAll() {
    const el = document.getElementById('select-all');
    if (!el) return;
    const visibleSelected = visibleHashes.filter(h => selectedHashes.has(h)).length;
    el.checked = visibleHashes.length > 0 && visibleSelected === visibleHashes.length;
    el.indeterminate = visibleSelected > 0 && visibleSelected < visibleHashes.length;
}

function updateBulkBar() {
    const bar = document.getElementById('bulk-bar');
    const count = document.getElementById('bulk-count');
    if (selectedHashes.size === 0) {
        bar.classList.add('d-none');
    } else {
        bar.classList.remove('d-none');
        count.innerText = selectedHashes.size;
    }
}

function clearSelection() {
    selectedHashes.clear();
    renderTorrents();
}

function sortData(field) {
    if (currentSortField === field) currentSortDir = currentSortDir === 'asc' ? 'desc' : 'asc';
    else { currentSortField = field; currentSortDir = 'asc'; }
    renderTorrents();
}

async function runAction(hash, name) {
    if (!confirm(`Blocklist and re-search '${name}'?\n\nThis will remove it from qBittorrent (with files), blocklist the release in the *arr, and trigger a fresh search.`)) return;

    const logBox = document.getElementById('log-box');
    logBox.innerHTML = `> Blocklisting '${name}'...`;

    try {
        const response = await fetch('/api/stalled/bulk-action', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ hashes: [hash], action: 'purge_research' })
        });
        const data = await response.json();
        if (response.ok) {
            logBox.innerHTML = `> ${data.message}`;
            if (data.notes && data.notes.length) logBox.innerHTML += `<br>&gt; Notes: ${data.notes.join(' | ')}`;
            if (data.errors && data.errors.length) logBox.innerHTML += `<br>&gt; Errors: ${data.errors.join(' | ')}`;
            fetchStats();
        } else {
            logBox.innerHTML = `> ERROR: ${data.message}`;
            alert(data.message);
        }
    } catch (e) {
        logBox.innerHTML = `> ERROR: ${e}`;
    }
}

async function bulkAction() {
    const hashes = Array.from(selectedHashes);
    if (hashes.length === 0) return;

    const confirmMsg = `Blocklist and re-search ${hashes.length} torrent(s)?\n\n` +
        `This will remove them from qBittorrent (with files), blocklist their releases in the corresponding *arrs, and trigger fresh searches.\n\n` +
        `Actions run sequentially — large selections may take a minute. This cannot be undone.`;
    if (!confirm(confirmMsg)) return;

    const logBox = document.getElementById('log-box');
    logBox.innerHTML = `> Running bulk blocklist on ${hashes.length} torrent(s)...`;

    const buttons = document.querySelectorAll('#bulk-bar button');
    buttons.forEach(b => b.disabled = true);

    try {
        const response = await fetch('/api/stalled/bulk-action', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ hashes: hashes, action: 'purge_research' })
        });
        const data = await response.json();
        if (response.ok) {
            logBox.innerHTML = `> ${data.message}`;
            if (data.notes && data.notes.length) logBox.innerHTML += `<br>&gt; Notes: ${data.notes.slice(0,3).join(' | ')}`;
            if (data.errors && data.errors.length) logBox.innerHTML += `<br>&gt; Errors: ${data.errors.slice(0,3).join(' | ')}`;
            clearSelection();
            fetchStats();
        } else {
            logBox.innerHTML = `> ERROR: ${data.message}`;
            alert(data.message);
        }
    } catch (e) {
        logBox.innerHTML = `> ERROR: ${e}`;
    } finally {
        buttons.forEach(b => b.disabled = false);
    }
}

async function runTask(taskName, dryRun) {
    const logBox = document.getElementById('log-box');
    logBox.innerHTML = `> Triggering task: ${taskName}...`;
    try {
        const response = await fetch('/api/run-task', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task: taskName, dry_run: dryRun })
        });
        const data = await response.json();
        logBox.innerHTML = `> ${data.message}`;
        fetchStats();
    } catch (e) { logBox.innerHTML = `> ERROR: ${e}`; }
}

document.addEventListener('DOMContentLoaded', () => {
    fetchStats();
    setInterval(fetchStats, 60000);
});
