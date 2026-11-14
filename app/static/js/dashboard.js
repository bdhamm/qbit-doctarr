// Dashboard page: task status cards, snapshot progress bars, customize modal,
// and a live countdown to each task's next run.

const TASKS = [
    { job: 'missing',    name: 'Missing Media Sync',       icon: 'bi-search',             color: 'primary',   path: '/missing' },
    { job: 'metadata',   name: 'Stale Metadata Cleanup',   icon: 'bi-hdd-stack',          color: 'info',      path: '/maintenance' },
    { job: 'cleanup',    name: 'Torrent Cleanup',          icon: 'bi-activity',           color: 'danger',    path: '/stalled' },
    { job: 'arr_health', name: 'Database Health',          icon: 'bi-heart-pulse',        color: 'success',   path: '/maintenance#card-arr-health' },
    { job: 'extensions', name: 'Dangerous File Blocker',   icon: 'bi-shield-x',           color: 'warning',   path: '/maintenance#card-extensions' },
    { job: 'unmonitor',  name: 'Unmonitor Items',          icon: 'bi-eye-slash',          color: 'secondary', path: '/settings' }
];

const MERGED_TASKS = {
    'metadata': ['BT_Backup Repair', 'Quarantine Cleanup'],
    'cleanup': ['Stalled Tracker', 'Unmanaged Torrents']
};

let latestRuns = {};
let missingCounts = {};
let stalledBreakdown = {};
let nextRuns = {};
let arrHealthData = null;
let hiddenCards = [];

function truncate(str, maxLen) {
    if (!str) return '—';
    if (str.length <= maxLen) return str;
    return str.substring(0, maxLen) + '…';
}

function formatTime(seconds) {
    if (seconds <= 0) return 'Running…';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
}

function renderArrHealthBody() {
    if (!arrHealthData || !arrHealthData.statuses) {
        return '<div class="small text-muted mb-2">No health data yet.</div>';
    }
    const entries = Object.values(arrHealthData.statuses);
    if (entries.length === 0) return '<div class="small text-muted mb-2">No enabled sources configured.</div>';

    const badgeFor = (status) => {
        const map = { 'ok': ['bg-success', 'Healthy'], 'unreachable': ['bg-warning text-dark', 'Unreachable'], 'error_warnings': ['bg-danger', 'Unhealthy'], 'unknown': ['bg-secondary', 'Unknown'] };
        return map[status] || map['unknown'];
    };

    let html = '<div class="d-grid mb-2" style="grid-template-columns: repeat(2, 1fr); column-gap: 1.5rem; row-gap: 0.35rem;">';
    entries.forEach(e => {
        const [cls, label] = badgeFor(e.last_status);
        html += `<div class="d-flex align-items-center gap-2">
                    <span class="small text-truncate" style="width: 90px; flex-shrink: 0;" title="${escapeHTML(e.arr_name)}">${escapeHTML(e.arr_name)}</span>
                    <span class="badge ${cls} flex-shrink-0" style="font-size:0.7rem;">${label}</span>
                 </div>`;
    });
    html += '</div>';
    return html;
}

function renderCards() {
    const container = document.getElementById('cards-container');
    const visibleTasks = TASKS.filter(t => !hiddenCards.includes(t.job));

    if (visibleTasks.length === 0) {
        container.innerHTML = '<div class="col-12 text-center text-muted py-4">All cards are hidden. Click Customize to show them.</div>';
        return;
    }

    container.innerHTML = visibleTasks.map(t => {
        let status = 'Never run';
        let statusClass = 'bg-secondary';
        let bodyContent = '';
        let nextDisp = '—';

        if (t.job === 'metadata' || t.job === 'cleanup') {
            const keys = MERGED_TASKS[t.job];
            const first = latestRuns[keys[0]] || {};
            const second = latestRuns[keys[1]] || {};

            let activeRun = (first.last_run > second.last_run) ? first : second;
            status = activeRun.status || 'Never run';
            statusClass = status === 'Success' ? 'bg-success' : status === 'Error' ? 'bg-danger' : 'bg-secondary';

            const details = truncate(activeRun.details ? escapeHTML(activeRun.details) : '', 80);
            bodyContent = `<div class="small text-muted mb-2" title="${details}">${details}</div>`;

            const j1 = t.job === 'metadata' ? 'bt_backup' : 'stalled';
            const j2 = t.job === 'metadata' ? 'quarantine' : 'unmanaged';
            const nr1 = nextRuns[j1] !== undefined ? nextRuns[j1] : Infinity;
            const nr2 = nextRuns[j2] !== undefined ? nextRuns[j2] : Infinity;
            const nextSec = Math.min(nr1, nr2);
            nextDisp = nextSec === Infinity ? '—' : nextSec <= 0 ? 'Running…' : formatTime(nextSec);

        } else {
            const lr = latestRuns[t.name] || {};
            status = lr.status || 'Never run';
            statusClass = status === 'Success' ? 'bg-success' : status === 'Error' ? 'bg-danger' : 'bg-secondary';

            const nextSec = nextRuns[t.job];
            nextDisp = nextSec === undefined ? '—' : nextSec <= 0 ? 'Running…' : formatTime(nextSec);

            if (t.job === 'arr_health') {
                bodyContent = renderArrHealthBody();
            } else {
                const details = truncate(lr.details ? escapeHTML(lr.details) : '', 80);
                bodyContent = `<div class="small text-muted mb-2" title="${details}">${details}</div>`;
            }
        }

        return `
        <div class="col">
            <div class="card h-100 shadow-sm border-${t.color}">
                <div class="card-header bg-dark border-secondary py-2">
                    <div class="d-flex justify-content-between align-items-center">
                        <a href="${t.path}" class="text-decoration-none text-reset me-2" style="min-width: 0;">
                            <h6 class="mb-0 text-truncate">
                                <i class="bi ${t.icon} text-${t.color}"></i> ${t.name}
                                <i class="bi bi-box-arrow-up-right small text-muted ms-1"></i>
                            </h6>
                        </a>
                        <span class="badge ${statusClass} flex-shrink-0">${status}</span>
                    </div>
                </div>
                <div class="card-body py-2 d-flex flex-column">
                    ${bodyContent}
                </div>
                <div class="card-footer bg-dark border-secondary py-2 d-flex justify-content-between align-items-center">
                    <span class="small text-muted">Next Run:</span>
                    <span class="small fw-bold">${nextDisp}</span>
                </div>
            </div>
        </div>`;
    }).join('');
}

function setBarWidth(id, count, total) {
    const el = document.getElementById(id);
    if (!el) return;
    if (total === 0 || count === 0) {
        el.style.width = '0%';
    } else {
        el.style.width = ((count / total) * 100) + '%';
    }
}

function renderSnapshot() {
    document.getElementById('snapshot-row').classList.remove('d-none');
    const mActive = missingCounts.active || 0;
    const mFailed = missingCounts.failed || 0;
    const mIgnored = missingCounts.ignored || 0;
    const mTotal = mActive + mFailed + mIgnored;
    document.getElementById('snap-missing-total').innerText = mTotal;
    setBarWidth('bar-missing-active', mActive, mTotal);
    setBarWidth('bar-missing-failed', mFailed, mTotal);
    setBarWidth('bar-missing-ignored', mIgnored, mTotal);

    const sDl = stalledBreakdown.dl_stall || 0;
    const sMeta = stalledBreakdown.meta_stall || 0;
    const sSeed = stalledBreakdown.seed_stall || 0;
    const sTotal = sDl + sMeta + sSeed;
    document.getElementById('snap-stalled-total').innerText = sTotal;
    setBarWidth('bar-stalled-dl', sDl, sTotal);
    setBarWidth('bar-stalled-meta', sMeta, sTotal);
    setBarWidth('bar-stalled-seed', sSeed, sTotal);
}

function renderCustomizeModal() {
    const list = document.getElementById('customize-list');
    list.innerHTML = TASKS.map(t => {
        const isVisible = !hiddenCards.includes(t.job);
        return `
        <div class="form-check form-switch">
            <input class="form-check-input" type="checkbox" role="switch" id="toggle-${t.job}" ${isVisible ? 'checked' : ''} onchange="toggleCard('${t.job}')">
            <label class="form-check-label text-light" for="toggle-${t.job}">${t.name}</label>
        </div>`;
    }).join('');
}

async function toggleCard(job) {
    const checkbox = document.getElementById('toggle-' + job);
    if (checkbox.checked) {
        hiddenCards = hiddenCards.filter(c => c !== job);
    } else {
        if (!hiddenCards.includes(job)) hiddenCards.push(job);
    }
    renderCards();
    try {
        await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ dashboard_hidden_cards: hiddenCards })
        });
    } catch (e) { console.error('Failed to save card visibility', e); }
}

async function showAllCards() {
    hiddenCards = [];
    renderCustomizeModal();
    renderCards();
    try {
        await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ dashboard_hidden_cards: hiddenCards })
        });
    } catch (e) { console.error('Failed to save card visibility', e); }
}

async function fetchDashboard() {
    try {
        const [r1, r2] = await Promise.all([
            fetch('/api/dashboard'),
            fetch('/api/arr-health')
        ]);
        const d = await r1.json();
        const h = await r2.json().catch(() => null);
        
        latestRuns              = d.latest_runs              || {};
        missingCounts           = d.missing_counts           || {};
        stalledBreakdown        = d.stalled_breakdown        || {};
        nextRuns                = d.next_runs                || {};
        arrHealthData           = h || { statuses: {}, warnings: [] };
        hiddenCards             = d.dashboard_hidden_cards   || [];

        // --- SMART ALIAS MATCHING (Restored) ---
        // Find the exact task name in the backend logs and map it to the UI card name.
        // Uses .includes() to catch variations like "Extensions", "Extensions Checker", "Dangerous Files", etc.
        const extKey = Object.keys(latestRuns).find(k => k.toLowerCase().includes('extens') || k.toLowerCase().includes('dangerous'));
        if (extKey) latestRuns['Dangerous File Blocker'] = latestRuns[extKey];

        const missKey = Object.keys(latestRuns).find(k => k.toLowerCase().includes('missing'));
        if (missKey) latestRuns['Missing Media Sync'] = latestRuns[missKey];

        const unmKey = Object.keys(latestRuns).find(k => k.toLowerCase().includes('unmonitor'));
        if (unmKey) latestRuns['Unmonitor Items'] = latestRuns[unmKey];

        // Migration: If old card names were hidden, map them to the new merged names
        if (hiddenCards.includes('bt_backup') || hiddenCards.includes('quarantine')) {
            if (!hiddenCards.includes('metadata')) hiddenCards.push('metadata');
            hiddenCards = hiddenCards.filter(c => c !== 'bt_backup' && c !== 'quarantine');
        }
        if (hiddenCards.includes('stalled') || hiddenCards.includes('unmanaged')) {
            if (!hiddenCards.includes('cleanup')) hiddenCards.push('cleanup');
            hiddenCards = hiddenCards.filter(c => c !== 'stalled' && c !== 'unmanaged');
        }
        
        renderCards();
        renderSnapshot();
        renderCustomizeModal();
    } catch (e) {
        console.error('Dashboard fetch failed', e);
        document.getElementById('cards-container').innerHTML =
            '<div class="col-12 text-center text-danger py-4">Failed to load dashboard.</div>';
    }
}

setInterval(() => {
    let updated = false;
    for (let k in nextRuns) {
        if (nextRuns[k] > 0) { nextRuns[k]--; updated = true; }
    }
}, 1000);

document.addEventListener('DOMContentLoaded', () => {
    fetchDashboard();
    setInterval(fetchDashboard, 60000);
});
