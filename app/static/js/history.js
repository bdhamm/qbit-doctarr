// History page: fetch paginated task history, render as a table,
// support client-side search over the loaded pages.
//
// Requires common.js (escapeHTML) to be loaded first.

let allHistory = [];
let currentOffset = 0;
const PAGE_SIZE = 100;

async function fetchHistory(reset = true) {
    const tbody = document.getElementById('history-tbody');
    const btn = document.getElementById('load-more-btn');

    if (reset) {
        currentOffset = 0;
        allHistory = [];
        tbody.innerHTML = '<tr><td colspan="3" class="text-center text-muted py-4"><span class="spinner-border spinner-border-sm"></span> Loading...</td></tr>';
        btn.classList.add('d-none');
    } else {
        btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Loading...';
        btn.disabled = true;
    }

    try {
        const response = await fetch(`/api/stats?limit=${PAGE_SIZE}&offset=${currentOffset}`);
        const data = await response.json();
        const newHistory = data.history || [];

        allHistory = allHistory.concat(newHistory);
        currentOffset += newHistory.length;

        renderHistory();

        // If we got exactly PAGE_SIZE, there might be more.
        if (newHistory.length === PAGE_SIZE) {
            btn.classList.remove('d-none');
        } else {
            btn.classList.add('d-none');
        }
    } catch (e) {
        if (reset) tbody.innerHTML = '<tr><td colspan="3" class="text-center text-danger py-4">Failed to load history.</td></tr>';
        else alert("Failed to load more history.");
    } finally {
        if (!reset) {
            btn.innerHTML = 'Load More';
            btn.disabled = false;
        }
    }
}

function loadMore() {
    fetchHistory(false);
}

function renderHistory() {
    const searchInput = (document.getElementById('search-input').value || '').toLowerCase();
    const tbody = document.getElementById('history-tbody');

    if (allHistory.length === 0) {
        tbody.innerHTML = '<tr><td colspan="3" class="text-center text-muted py-4">No history available.</td></tr>';
        return;
    }

    const filtered = allHistory.filter(h => {
        const task = (h.task_name || '').toLowerCase();
        const details = (h.details || '').toLowerCase();
        const time = (h.last_run || '').toLowerCase();
        return task.includes(searchInput) || details.includes(searchInput) || time.includes(searchInput);
    });

    if (filtered.length === 0) {
        tbody.innerHTML = '<tr><td colspan="3" class="text-center text-muted py-4">No matching history entries found in the currently loaded pages.</td></tr>';
        return;
    }

    tbody.innerHTML = filtered.map(h => `
        <tr>
            <td class="align-middle py-1"><span class="badge bg-secondary">${escapeHTML(h.task_name || '')}</span></td>
            <td class="align-middle py-1">${escapeHTML(h.details || '')}</td>
            <td class="align-middle py-1">${escapeHTML(h.last_run || '')}</td>
        </tr>
    `).join('');
}

document.addEventListener('DOMContentLoaded', () => {
    fetchHistory(true);
    setInterval(() => fetchHistory(true), 60000);
});
