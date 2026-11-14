// Maintenance page: run cleanup tasks, display scan results,
// and manage the quarantine folder (search, select, delete).
//
// Requires common.js (escapeHTML) to be loaded first.

let searchTimeout;
let allSelected = false;

document.addEventListener('DOMContentLoaded', () => { loadQuarantine(); });

async function runMaintenance(taskName, dryRun) {
    const logBox = document.getElementById('log-box');
    const resultsList = document.getElementById('scan-results');
    logBox.innerHTML = `> Triggering task: ${taskName}...`;
    resultsList.innerHTML = '<li class="list-group-item bg-dark text-info text-center py-4">Scanning...</li>';
    
    try {
        const response = await fetch('/api/run-task', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task: taskName, dry_run: dryRun })
        });
        const data = await response.json();
        logBox.innerHTML = `> ${data.message}`;
        
        if (data.files && data.files.length > 0) {
            const displayFiles = data.files.slice(0, 100);
            let html = displayFiles.map(f => `
                <li class="list-group-item bg-dark text-light border-secondary py-1 align-middle">
                    <div class="text-truncate" title="${escapeHTML(f)}">${escapeHTML(f)}</div>
                </li>
            `).join('');
            
            if (data.files.length > 100) {
                html += `<li class="list-group-item bg-dark text-warning border-secondary py-2 text-center">...and ${data.files.length - 100} more files.</li>`;
            }
            resultsList.innerHTML = html;
        } else {
            resultsList.innerHTML = '<li class="list-group-item bg-dark text-success border-secondary py-4 text-center">No files found.</li>';
        }
        if (!dryRun) loadQuarantine();
    } catch (e) {
        logBox.innerHTML = `> ERROR: ${e}`;
        resultsList.innerHTML = '<li class="list-group-item bg-dark text-danger border-secondary py-4 text-center">Error during scan.</li>';
    }
}

async function confirmReset(target) {
    const confirmed = confirm(`Are you sure you want to reset the ${target} tracking table?\n\nThis clears all tracked state and rows from the database. The next time the task runs, it will re-discover everything from scratch.`);
    if (!confirmed) return;
    
    const taskName = target === 'missing' ? 'db_clear_missing' : 'db_clear_stalled';
    await runMaintenance(taskName, false);
}

function searchQuarantine() { 
    clearTimeout(searchTimeout); 
    searchTimeout = setTimeout(() => { loadQuarantine(); }, 300); 
}

function toggleSelectAll() {
    allSelected = !allSelected;
    document.querySelectorAll('.q-file').forEach(cb => cb.checked = allSelected);
    document.getElementById('select-all-btn').innerText = allSelected ? "Select None" : "Select All";
}

async function loadQuarantine() {
    const list = document.getElementById('quarantine-list');
    const countLabel = document.getElementById('q-count');
    const search = document.getElementById('q-search').value;
    allSelected = false;
    document.getElementById('select-all-btn').innerText = "Select All";
    
    list.innerHTML = '<tr><td class="text-center text-muted py-4">Searching...</td></tr>';
    try {
        const response = await fetch(`/api/quarantine/list?search=${encodeURIComponent(search)}`);
        const data = await response.json();
        if (data.total === 0) {
            list.innerHTML = '<tr><td class="text-center text-muted py-4">No files found.</td></tr>';
            countLabel.innerText = `0 files`;
            return;
        }
        countLabel.innerText = (data.total > data.files.length) ? `Showing ${data.files.length} of ${data.total}` : `${data.total} files`;

        list.innerHTML = data.files.map(f => {
            const safeName = escapeHTML(f);
            return `
            <tr>
                <td class="align-middle py-1 w-100">
                    <div class="form-check mb-0 text-truncate">
                        <input class="form-check-input q-file" type="checkbox" value="${safeName}" id="q_${safeName}">
                        <label class="form-check-label text-truncate w-100 ms-1" for="q_${safeName}" title="${safeName}">${safeName}</label>
                    </div>
                </td>
            </tr>`;
        }).join('');
    } catch (e) { list.innerHTML = '<tr><td class="text-center text-danger py-4">Failed to load.</td></tr>'; }
}

async function deleteSelectedQuarantine() {
    const files = Array.from(document.querySelectorAll('.q-file:checked')).map(cb => cb.value);
    if (files.length === 0) { alert("No files selected."); return; }
    if (!confirm(`Are you sure you want to permanently delete ${files.length} files?`)) return;
    try {
        const response = await fetch('/api/quarantine/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ files }) });
        const data = await response.json(); alert(data.message); loadQuarantine();
    } catch (e) { alert("Failed to delete files."); }
}
