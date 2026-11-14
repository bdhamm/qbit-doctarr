// Missing Media Manager page: fetch tracked missing items, render as a
// sortable/filterable table with per-row and bulk actions.
//
// Requires common.js (escapeHTML) to be loaded first.

let allItems = [];
let currentSortCol = null;
let currentSortDir = 'asc';
let selectedIds = new Set();
let visibleIds = [];

async function fetchMissingMedia() {
    const tbody = document.getElementById('missing-tbody');
    tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-4"><span class="spinner-border spinner-border-sm"></span> Loading...</td></tr>';
    try {
        const response = await fetch('/api/missing/list');
        allItems = await response.json();
        renderTable();
    } catch (e) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center text-danger py-4">Failed to load data.</td></tr>';
    }
}

function fmtLastSeen(v) {
    if (!v || v.startsWith('1970')) return 'Never';
    return v;
}

function clearSelectionAndRender() {
    selectedIds.clear();
    renderTable();
}

function renderTable() {
    const tbody = document.getElementById('missing-tbody');
    const countBadge = document.getElementById('missing-count');
    const filter = document.getElementById('search-input').value.toLowerCase();
    const statusFilter = document.getElementById('status-filter').value;

    let filtered = allItems.filter(item => {
        if (statusFilter && item.status !== statusFilter) return false;
        return `${item.title} ${item.arr_name} ${item.status}`.toLowerCase().includes(filter);
    });

    if (currentSortCol !== null) {
        filtered.sort((a, b) => {
            let valA, valB;
            if (currentSortCol === 0) { valA = a.title.toLowerCase(); valB = b.title.toLowerCase(); }
            else if (currentSortCol === 1) { valA = a.arr_name.toLowerCase(); valB = b.arr_name.toLowerCase(); }
            else if (currentSortCol === 2) { valA = a.attempts; valB = b.attempts; }
            else if (currentSortCol === 3) { valA = a.status.toLowerCase(); valB = b.status.toLowerCase(); }
            else if (currentSortCol === 4) { valA = a.last_searched || ''; valB = b.last_searched || ''; }
            if (valA < valB) return currentSortDir === 'asc' ? -1 : 1;
            if (valA > valB) return currentSortDir === 'asc' ? 1 : -1;
            return 0;
        });
    }

    visibleIds = filtered.map(i => i.id);
    countBadge.innerText = `${filtered.length} items`;
    syncSelectAll();

    if (filtered.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-4">No matching items found.</td></tr>';
        updateBulkBar();
        return;
    }

    tbody.innerHTML = filtered.map(item => {
        let statusBadge = '';
        if (item.status === 'failed') statusBadge = '<span class="badge bg-danger">Failed</span>';
        else if (item.status === 'ignored') statusBadge = '<span class="badge bg-secondary">Ignored</span>';
        else statusBadge = '<span class="badge bg-primary">Active</span>';

        let actionButtons = `
            <button class="btn btn-sm btn-outline-success" onclick="runAction(${item.id}, 'retry')" title="Reset attempts and try again"><i class="bi bi-arrow-clockwise"></i> Retry</button>
        `;
        if (item.status !== 'ignored') {
            actionButtons += `<button class="btn btn-sm btn-outline-warning" onclick="runAction(${item.id}, 'ignore')" title="Stop searching for this"><i class="bi bi-eye-slash"></i> Ignore</button>`;
        }
        actionButtons += `<button class="btn btn-sm btn-outline-danger" onclick="runAction(${item.id}, 'blocklist_research')" title="Blocklist failed releases in *arr and search again"><i class="bi bi-shield-slash"></i> Blocklist &amp; Re-search</button>`;

        const isChecked = selectedIds.has(item.id) ? 'checked' : '';
        const safeTitle = escapeHTML(item.title);
        const safeArr = escapeHTML(item.arr_name);

        return `<tr>
            <td class="align-middle py-1"><input type="checkbox" class="form-check-input row-check" data-id="${item.id}" ${isChecked} onchange="toggleRow(${item.id}, this.checked)"></td>
            <td class="text-truncate align-middle py-1" style="max-width: 400px;" title="${safeTitle}">${safeTitle}</td>
            <td class="align-middle py-1">${safeArr}</td>
            <td class="align-middle py-1">${item.attempts}</td>
            <td class="align-middle py-1">${statusBadge}</td>
            <td class="text-nowrap align-middle py-1">${fmtLastSeen(item.last_searched)}</td>
            <td class="align-middle py-1"><div class="d-flex gap-1 text-nowrap">${actionButtons}</div></td>
        </tr>`;
    }).join('');

    updateBulkBar();
}

function toggleRow(id, checked) {
    if (checked) selectedIds.add(id);
    else selectedIds.delete(id);
    syncSelectAll();
    updateBulkBar();
}

function toggleSelectAll(checked) {
    if (checked) visibleIds.forEach(id => selectedIds.add(id));
    else visibleIds.forEach(id => selectedIds.delete(id));
    renderTable();
}

function syncSelectAll() {
    const el = document.getElementById('select-all');
    if (!el) return;
    const visibleSelected = visibleIds.filter(id => selectedIds.has(id)).length;
    el.checked = visibleIds.length > 0 && visibleSelected === visibleIds.length;
    el.indeterminate = visibleSelected > 0 && visibleSelected < visibleIds.length;
}

function updateBulkBar() {
    const bar = document.getElementById('bulk-bar');
    const count = document.getElementById('bulk-count');
    if (selectedIds.size === 0) {
        bar.classList.add('d-none');
    } else {
        bar.classList.remove('d-none');
        count.innerText = selectedIds.size;
    }
}

function clearSelection() {
    selectedIds.clear();
    renderTable();
}

async function runAction(id, action) {
    if (action === 'blocklist_research') {
        if (!confirm("Blocklist failed releases for this item in *arr and trigger a new search?\n\nFailed releases will not be attempted again by your *arr.")) return;
    }
    if (action === 'ignore') {
        if (!confirm("Mark this item as ignored? doctarr will stop searching for it. Your *arr will keep monitoring.")) return;
    }
    const logBox = document.getElementById('log-box');
    logBox.innerHTML = `> Processing action: ${action}...`;
    try {
        const response = await fetch('/api/missing/action', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: id, action: action })
        });
        const data = await response.json();
        if (response.ok) { logBox.innerHTML = `> ${data.message}`; fetchMissingMedia(); }
        else { logBox.innerHTML = `> ERROR: ${data.message}`; alert(data.message); }
    } catch (e) { logBox.innerHTML = `> ERROR: ${e}`; }
}

async function bulkAction(action) {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;

    if (action === 'ignore') {
        if (!confirm(`Mark ${ids.length} item(s) as ignored?\n\ndoctarr will stop searching for them. Your *arrs will keep monitoring.`)) return;
    }
    if (action === 'blocklist_research') {
        if (!confirm(`Blocklist failed releases and trigger new searches for ${ids.length} item(s)?\n\nThis removes failed releases from future attempts in *arr. Actions run sequentially — large selections may take a minute or two.`)) return;
    }

    const logBox = document.getElementById('log-box');
    logBox.innerHTML = `> Running bulk ${action} on ${ids.length} item(s)...`;

    const buttons = document.querySelectorAll('#bulk-bar button');
    buttons.forEach(b => b.disabled = true);

    try {
        const response = await fetch('/api/missing/bulk-action', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ids: ids, action: action })
        });
        const data = await response.json();
        if (response.ok) {
            logBox.innerHTML = `> ${data.message}` + (data.errors && data.errors.length ? `<br>&gt; First errors: ${data.errors.slice(0,3).join(' | ')}` : '');
            clearSelection();
            fetchMissingMedia();
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

function sortData(col) {
    if (currentSortCol === col) currentSortDir = currentSortDir === 'asc' ? 'desc' : 'asc';
    else { currentSortCol = col; currentSortDir = 'asc'; }
    renderTable();
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
        fetchMissingMedia();
    } catch (e) { logBox.innerHTML = `> ERROR: ${e}`; }
}

document.addEventListener('DOMContentLoaded', fetchMissingMedia);
