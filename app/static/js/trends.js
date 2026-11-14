// Trends page: two stacked-bar charts (Missing Media, Torrent Cleanup)
// with 24h / 7d / 30d range selector and manual "Snapshot Now" trigger.
//
// Requires chart.min.js (vendored Chart.js 4.x) to be loaded first.
// No dependency on common.js — this page doesn't use escapeHTML or other helpers.

const COLORS = {
    primary:   '#0d6efd',
    danger:    '#dc3545',
    secondary: '#6c757d',
    warning:   '#ffc107',
    info:      '#0dcaf0'
};

let currentDays = 1;
let loadToken = 0;
let chartMissing = null;
let chartStalled = null;

function formatLabel(ts, days) {
    if (!ts) return '';
    const d = new Date(ts.replace(' ', 'T'));
    if (days <= 1) {
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

// Keep the last snapshot of each local day. Gives "end-of-day state"
// which is what matters for backlog metrics over a 30-day view.
function aggregateDaily(rows) {
    const byDay = {};
    for (const row of rows) {
        if (!row.snapshot_at) continue;
        const day = row.snapshot_at.substring(0, 10);
        byDay[day] = row;
    }
    return Object.keys(byDay).sort().map(d => byDay[d]);
}

function buildStackedBarChart(canvasEl, labels, datasets) {
    return new Chart(canvasEl, {
        type: 'bar',
        data: { labels, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            interaction: { mode: 'index', intersect: false },
            scales: {
                x: {
                    stacked: true,
                    ticks: { color: '#adb5bd', maxRotation: 0, autoSkip: true, maxTicksLimit: 24 },
                    grid: { color: 'rgba(255,255,255,0.05)' }
                },
                y: {
                    stacked: true,
                    beginAtZero: true,
                    ticks: { color: '#adb5bd', precision: 0 },
                    grid: { color: 'rgba(255,255,255,0.05)' }
                }
            },
            plugins: {
                legend: { labels: { color: '#dee2e6' } },
                tooltip: {
                    backgroundColor: 'rgba(33,37,41,0.95)',
                    titleColor: '#fff',
                    bodyColor: '#dee2e6'
                }
            }
        }
    });
}

function summarize(rows, keys) {
    if (rows.length === 0) {
        return 'No snapshots yet — click "Snapshot Now" or wait for the top of the hour.';
    }
    const latest = rows[rows.length - 1];
    const earliest = rows[0];
    const latestTotal   = keys.reduce((s, k) => s + (latest[k]   || 0), 0);
    const earliestTotal = keys.reduce((s, k) => s + (earliest[k] || 0), 0);
    const delta = latestTotal - earliestTotal;
    const deltaStr = delta === 0
        ? 'no change'
        : (delta > 0 ? `▲ ${delta}` : `▼ ${Math.abs(delta)}`) + ' vs start of window';
    return `Currently <strong>${latestTotal}</strong> · ${deltaStr}`;
}

async function loadTrends(days) {
    const myToken = ++loadToken;
    currentDays = days;

    document.querySelectorAll('.range-btn').forEach(b => {
        b.classList.toggle('active', parseInt(b.dataset.days, 10) === days);
    });

    let rows = [];
    try {
        const resp = await fetch(`/api/metrics/history?days=${days}`);
        const data = await resp.json();
        if (myToken !== loadToken) return; // stale response; a newer click landed
        rows = data.history || [];
    } catch (e) {
        document.getElementById('summary-missing').textContent = 'Failed to load metrics.';
        document.getElementById('summary-stalled').textContent = 'Failed to load metrics.';
        return;
    }

    // 30-day view aggregates to daily (720 hourly rows -> 30 bars).
    // 7-day view keeps hourly resolution (168 bars) per original spec.
    // If 7d looks too dense, change the threshold below to `days >= 7`.
    if (days >= 30) rows = aggregateDaily(rows);

    const labels = rows.map(r => formatLabel(r.snapshot_at, days));

    // Missing Media Sync
    if (chartMissing) { chartMissing.destroy(); chartMissing = null; }
    chartMissing = buildStackedBarChart(
        document.getElementById('chart-missing'),
        labels,
        [
            { label: 'Active',  data: rows.map(r => r.missing_active),  backgroundColor: COLORS.primary },
            { label: 'Failed',  data: rows.map(r => r.missing_failed),  backgroundColor: COLORS.danger },
            { label: 'Ignored', data: rows.map(r => r.missing_ignored), backgroundColor: COLORS.secondary },
        ]
    );
    document.getElementById('summary-missing').innerHTML =
        summarize(rows, ['missing_active', 'missing_failed', 'missing_ignored']);

    // Torrent Cleanup
    if (chartStalled) { chartStalled.destroy(); chartStalled = null; }
    chartStalled = buildStackedBarChart(
        document.getElementById('chart-stalled'),
        labels,
        [
            { label: 'DL Stall',   data: rows.map(r => r.stalled_dl),   backgroundColor: COLORS.danger },
            { label: 'Meta Stall', data: rows.map(r => r.stalled_meta), backgroundColor: COLORS.warning },
            { label: 'Seed Stall', data: rows.map(r => r.stalled_seed), backgroundColor: COLORS.info },
        ]
    );
    document.getElementById('summary-stalled').innerHTML =
        summarize(rows, ['stalled_dl', 'stalled_meta', 'stalled_seed']);
}

function resizeCharts() {
    // Flexbox layout reflows when the alert appears/disappears; Chart.js's
    // ResizeObserver usually catches this, but an explicit resize guarantees
    // the canvas re-renders at the correct size on every browser.
    setTimeout(() => {
        if (chartMissing) chartMissing.resize();
        if (chartStalled) chartStalled.resize();
    }, 50);
}

function showSnapshotAlert(message, level) {
    // level: 'success' | 'warning' | 'danger'
    const row = document.getElementById('snapshot-alert-row');
    const box = document.getElementById('snapshot-alert');
    const txt = document.getElementById('snapshot-alert-text');
    box.className = `alert alert-${level} alert-dismissible fade show py-2 mb-0`;
    txt.textContent = message;
    row.classList.remove('d-none');
    resizeCharts();
    if (level === 'success') {
        setTimeout(hideSnapshotAlert, 5000);
    }
}

function hideSnapshotAlert() {
    document.getElementById('snapshot-alert-row').classList.add('d-none');
    resizeCharts();
}

async function takeSnapshot() {
    const btn = document.getElementById('snapshot-btn');
    const label = document.getElementById('snapshot-btn-label');

    btn.disabled = true;
    label.textContent = 'Running…';

    try {
        const resp = await fetch('/api/run-task', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task: 'metrics' })
        });

        if (resp.status === 409) {
            showSnapshotAlert('A snapshot is already running. Try again in a moment.', 'warning');
        } else if (!resp.ok) {
            showSnapshotAlert(`Snapshot failed (HTTP ${resp.status}).`, 'danger');
        } else {
            const data = await resp.json();
            if (data.status === 'success') {
                showSnapshotAlert(data.message || 'Snapshot written.', 'success');
                await loadTrends(currentDays);
            } else {
                showSnapshotAlert(data.message || 'Snapshot failed.', 'danger');
            }
        }
    } catch (e) {
        showSnapshotAlert('Could not reach the server. Check the logs.', 'danger');
    } finally {
        btn.disabled = false;
        label.textContent = 'Snapshot Now';
    }
}

document.querySelectorAll('.range-btn').forEach(b => {
    b.addEventListener('click', () => loadTrends(parseInt(b.dataset.days, 10)));
});

document.getElementById('snapshot-btn').addEventListener('click', takeSnapshot);

document.addEventListener('DOMContentLoaded', () => loadTrends(1));
