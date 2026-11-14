// Settings page logic: loads config from the data island, 
// handles test connections, and saves the config.

const currentConfig = JSON.parse(document.getElementById('settings-config-data').textContent);
const TIMEOUT_DEFAULTS_MIN = { bt_backup: 5, unmanaged: 15, stalled: 10, extensions: 10, quarantine: 10, arr_health: 5, missing: 0, unmonitor: 0, notify: 2, metrics: 1 };

const MUTE_LABELS = {
    'AllowedHostsCheck': 'Security: Allowed Hosts',
    'IndexerStatusCheck': 'Indexer Down (Short Term)',
    'IndexerLongTermStatusCheck': 'Indexer Down (Long Term)',
    'RemovedMovieCheck': 'Removed from Metadata Provider',
    'RemovedSeriesCheck': 'Removed from Metadata Provider',
    'RemovedArtistCheck': 'Removed from Metadata Provider',
    'NotificationStatusCheck': 'Notification Delivery Failure',
    'UpdateCheck': 'App Update Available',
    'DatabaseCheck': 'Database Error',
    'UnmappedFilesCheck': 'Unmapped Files (Lidarr)'
};

let allWarningSources = [];

// Falsy-safe value accessor: preserves 0 (and any other falsy config
// value) instead of substituting the fallback. Only undefined/null
// trigger the fallback. Use for any numeric config field where 0 is
// meaningful (e.g. 0 = disabled timer, 0 = disabled retention,
// 0 = midnight).
function valOr(v, fallback) {
    return (v === undefined || v === null) ? fallback : v;
}

// Falsy-safe numeric input parser: returns 0 when the user typed 0,
// only falls back when the input is empty or non-numeric. Use when
// saving numeric fields where 0 is meaningful.
function numOr(elId, fallback) {
    const el = document.getElementById(elId);
    if (!el) return fallback;
    const raw = (el.value || '').trim();
    if (raw === '') return fallback;
    const v = parseFloat(raw);
    return isNaN(v) ? fallback : v;
}

function getTimeoutSecs(name) {
    const el = document.getElementById('to-' + name);
    if (!el) return TIMEOUT_DEFAULTS_MIN[name] * 60;
    const raw = (el.value || '').trim();
    if (raw === '') return TIMEOUT_DEFAULTS_MIN[name] * 60;
    const v = parseFloat(raw);
    return isNaN(v) ? TIMEOUT_DEFAULTS_MIN[name] * 60 : Math.round(v * 60);
}

function toggleDigestFreq() {
    const f = document.getElementById('digest-freq').value;
    document.getElementById('digest-dow-container').classList.toggle('d-none', f !== 'weekly');
    document.getElementById('digest-dom-container').classList.toggle('d-none', f !== 'monthly');
}

function toggleQbitAuth() {
    const method = document.getElementById('qbit-auth-method').value;
    document.getElementById('qbit-pass-fields').style.display = method === 'apikey' ? 'none' : 'flex';
    document.getElementById('qbit-key-fields').style.display = method === 'apikey' ? 'block' : 'none';
}

function toggleVisibility(inputId) {
    const input = document.getElementById(inputId);
    const icon = input.nextElementSibling.querySelector('i');
    if (input.type === "password") { input.type = "text"; icon.classList.replace("bi-eye", "bi-eye-slash"); }
    else { input.type = "password"; icon.classList.replace("bi-eye-slash", "bi-eye"); }
}

function renderMutedSources() {
    const container = document.getElementById('muted-sources-container');
    if (!container) return;
    if (!allWarningSources.length) { container.innerHTML = '<div class="form-text text-muted small">No warnings recorded yet.</div>'; return; }
    const muted = new Set((currentConfig.notifications && currentConfig.notifications.muted_sources) || []);
    container.innerHTML = allWarningSources.map(s => {
        const sid = 'src-' + s.source.replace(/[^a-zA-Z0-9_-]/g, '_');
        const label = MUTE_LABELS[s.source] || s.source;
        return `<div class="form-check form-switch"><input class="form-check-input muted-source-toggle" type="checkbox" id="${sid}" data-source="${s.source}" ${!muted.has(s.source) ? 'checked' : ''}><label class="form-check-label text-light small" for="${sid}">${label} <span class="text-muted">— ${s.active_count} active</span></label></div>`;
    }).join('');
}

async function loadWarningSources() {
    try {
        const resp = await fetch('/api/arr-health');
        const data = await resp.json();
        allWarningSources = data.sources || [];
        renderMutedSources();
    } catch (e) { console.error('Failed to load sources', e); }
}

async function testNotify() {
    const btn = event.target;
    const original = btn.innerHTML;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>'; btn.disabled = true;
    try {
        const resp = await fetch('/api/test-notify', { method: 'POST' });
        const data = await resp.json();
        alert(data.message);
    } catch (e) { alert("Network error."); }
    finally { btn.innerHTML = original; btn.disabled = false; }
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('schedules-enabled').checked = currentConfig.schedules_enabled !== false;
    document.getElementById('q-limit-enabled').checked = currentConfig.quarantine_limit_enabled !== false;
    document.getElementById('global-dry-run').checked = currentConfig.global_dry_run === true;
    document.getElementById('log-to-file').checked = currentConfig.log_to_file === true;
    document.getElementById('unmonitor-mode').value = currentConfig.unmonitor_mode || 'items';
    document.getElementById('unmonitor-ignore-specials').checked = currentConfig.unmonitor_ignore_specials !== false;
    document.getElementById('unmonitor-force-refresh').checked = currentConfig.unmonitor_force_refresh !== false;
    document.getElementById('unmonitor-refresh-timeout').value = currentConfig.unmonitor_refresh_timeout_sec !== undefined ? currentConfig.unmonitor_refresh_timeout_sec : 600;

    if (currentConfig.security) {
        document.getElementById('sec-auth-enabled').checked = currentConfig.security.basic_auth_enabled === true;
        document.getElementById('sec-auth-user').value = currentConfig.security.basic_auth_username || 'admin';
        document.getElementById('sec-auth-pass').value = currentConfig.security.basic_auth_password || '';
    }

    if (currentConfig.qbit) {
        document.getElementById('qbit-enabled').checked = currentConfig.qbit.enabled !== false;
        document.getElementById('qbit-url').value = currentConfig.qbit.url || '';
        document.getElementById('qbit-auth-method').value = currentConfig.qbit.auth_method || 'password';
        document.getElementById('qbit-user').value = currentConfig.qbit.username || '';
        document.getElementById('qbit-pass').value = currentConfig.qbit.password || '';
        document.getElementById('qbit-apikey').value = currentConfig.qbit.api_key || '';
        toggleQbitAuth();
    }
    
    if (currentConfig.thresholds) {
        const t = currentConfig.thresholds;
        // Falsy-safe: 0 is a meaningful threshold value.
        document.getElementById('thresh-meta-val').value = valOr(t.meta_time, 2);
        document.getElementById('thresh-meta-unit').value = t.meta_unit || 'hours';
        document.getElementById('thresh-stalled-val').value = valOr(t.stalled_time, 48);
        document.getElementById('thresh-stalled-unit').value = t.stalled_unit || 'hours';
        document.getElementById('thresh-unmanaged-val').value = valOr(t.unmanaged_time, 168);
        document.getElementById('thresh-unmanaged-unit').value = t.unmanaged_unit || 'hours';
        document.getElementById('thresh-speed-val').value = valOr(t.slow_speed_val, 10);
        document.getElementById('thresh-speed-unit').value = t.slow_speed_unit || 'KiB';
        document.getElementById('thresh-max-pct').value = valOr(t.max_percentage, 100);
        document.getElementById('thresh-target-seeds-select').value = t.target_100_seeds ? "true" : "false";
        document.getElementById('thresh-blocked-exts').value = t.blocked_extensions || "exe,scr,bat,cmd,vbs";
        document.getElementById('thresh-approved-exts').value = t.approved_extensions || "mkv,mp4,avi";
        document.getElementById('thresh-missing-polite').checked = t.missing_polite_mode !== false;
        document.getElementById('thresh-missing-batch').value = valOr(t.missing_batch_size, 3);
        document.getElementById('thresh-missing-batch-mode').value = t.missing_batch_mode || 'per_arr';
        document.getElementById('thresh-missing-cooldown').value = valOr(t.missing_cooldown_hours, 24);
        document.getElementById('thresh-missing-retries').value = valOr(t.missing_max_retries, 5);
        // 0 documented as "disabled" — must be preserved.
        document.getElementById('q-retention-val').value = valOr(t.quarantine_retention_days, 7);
    }

    // Load q-limit-val from config (was previously missing — any custom
    // value was lost on reload, resetting to HTML's value="100" default).
    document.getElementById('q-limit-val').value = valOr(currentConfig.quarantine_limit, 100);

    // history-retention: 0 = no retention, must round-trip.
    document.getElementById('history-retention').value = valOr(currentConfig.history_retention, 100);
    document.getElementById('log-level').value = currentConfig.log_level || 'INFO';
    
    if (currentConfig.schedules) {
        const s = currentConfig.schedules;
        // Falsy-safe: 0 disables the schedule, must round-trip.
        document.getElementById('sched-bt-val').value = valOr(s.bt_backup_time, 24);
        document.getElementById('sched-bt-unit').value = s.bt_backup_unit || 'hours';
        
        document.getElementById('sched-stall-val').value = valOr(s.stalled_time, 1);
        document.getElementById('sched-stall-unit').value = s.stalled_unit || 'hours';
        
        document.getElementById('sched-unmanaged-val').value = valOr(s.unmanaged_time, 24);
        document.getElementById('sched-unmanaged-unit').value = s.unmanaged_unit || 'hours';
        
        document.getElementById('sched-exts-val').value = valOr(s.extensions_time, 0.5);
        document.getElementById('sched-exts-unit').value = s.extensions_unit || 'hours';
        
        document.getElementById('sched-missing-val').value = valOr(s.missing_time, 6);
        document.getElementById('sched-missing-unit').value = s.missing_unit || 'hours';
        
        document.getElementById('sched-quarantine-val').value = valOr(s.quarantine_time, 24);
        document.getElementById('sched-quarantine-unit').value = s.quarantine_unit || 'hours';
        
        document.getElementById('sched-unmonitor-val').value = valOr(s.unmonitor_time, 24);
        document.getElementById('sched-unmonitor-unit').value = s.unmonitor_unit || 'hours';
        
        document.getElementById('sched-arr-health-val').value = valOr(s.arr_health_time, 6);
        document.getElementById('sched-arr-health-unit').value = s.arr_health_unit || 'hours';
        
        document.getElementById('sched-notify-val').value = valOr(s.notify_time, 0.25);
        document.getElementById('sched-notify-unit').value = s.notify_unit || 'hours';

        document.getElementById('sched-metrics-val').value = valOr(s.metrics_time, 1);
        document.getElementById('sched-metrics-unit').value = s.metrics_unit || 'hours';
    }

    const ttCfg = currentConfig.task_timeouts || {};
    Object.keys(TIMEOUT_DEFAULTS_MIN).forEach(name => {
        const el = document.getElementById('to-' + name);
        if (el) el.value = ttCfg[name] !== undefined ? (ttCfg[name] === 0 ? 0 : Number((ttCfg[name] / 60).toFixed(2))) : TIMEOUT_DEFAULTS_MIN[name];
    });

    if (currentConfig.notifications) {
        const n = currentConfig.notifications;
        document.getElementById('notif-enabled').checked = n.enabled === true;
        const e = n.email || {};
        document.getElementById('notif-smtp-host').value = e.smtp_host || '';
        document.getElementById('notif-smtp-port').value = e.smtp_port || 25;
        document.getElementById('notif-tls-mode').value = e.tls_mode || 'none';
        document.getElementById('notif-username').value = e.username || '';
        document.getElementById('notif-password').value = e.password || '';
        document.getElementById('notif-from-addr').value = e.from_addr || 'qbit-doctarr@localhost';
        document.getElementById('notif-to-addrs').value = e.to_addrs || '';
        
        const d = n.digest || {};
        document.getElementById('digest-enabled').checked = d.enabled === true;
        document.getElementById('digest-freq').value = d.frequency || 'weekly';
        // hour: 0 = midnight (valid). valOr preserves it.
        document.getElementById('digest-hour').value = valOr(d.hour, 8);
        document.getElementById('digest-dow').value = valOr(d.day_of_week, 0);
        document.getElementById('digest-dom').value = valOr(d.day_of_month, 1);
        const sec = d.sections || {};
        document.getElementById('sec-task').checked = sec.task_activity !== false;
        document.getElementById('sec-health').checked = sec.health_changes !== false;
        document.getElementById('sec-snap').checked = sec.current_snapshot !== false;
        document.getElementById('sec-events').checked = sec.notable_events !== false;
        toggleDigestFreq();
    }

    if (currentConfig.arrs) currentConfig.arrs.forEach(arr => addArrRow(arr));
    loadWarningSources();
});

async function testConnection() {
    const btn = document.getElementById('test-btn');
    const resultDiv = document.getElementById('test-result');
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
    btn.disabled = true;
    resultDiv.style.display = 'none';

    const payload = {
        url: document.getElementById('qbit-url').value.trim(),
        auth_method: document.getElementById('qbit-auth-method').value,
        username: document.getElementById('qbit-user').value.trim(),
        password: document.getElementById('qbit-pass').value,
        api_key: document.getElementById('qbit-apikey').value.trim()
    };

    try {
        const response = await fetch('/api/test-qbit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        const data = await response.json();
        resultDiv.style.display = 'block';
        resultDiv.className = response.ok ? 'mt-2 fw-bold text-success' : 'mt-2 fw-bold text-danger';
        resultDiv.innerHTML = (response.ok ? '<i class="bi bi-check-circle"></i> ' : '<i class="bi bi-x-circle"></i> ') + data.message;
    } catch (error) {
        resultDiv.style.display = 'block';
        resultDiv.className = 'mt-2 fw-bold text-danger';
        resultDiv.innerHTML = '<i class="bi bi-x-circle"></i> Network error.';
    } finally {
        btn.innerHTML = 'Test';
        btn.disabled = false;
    }
}

async function testArr(btn) {
    const row = btn.closest('.arr-row');
    const type = row.querySelector('.arr-type').value;
    const url = row.querySelector('.arr-url').value.trim();
    const api_key = row.querySelector('.arr-key').value.trim();
    const api_version = row.querySelector('.arr-ver').value;
    if (!url || !api_key) { alert("Please fill in the URL and API Key before testing."); return; }
    const originalText = btn.innerHTML;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
    btn.disabled = true;
    try {
        const response = await fetch('/api/test-arr', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ type, url, api_key, api_version }) });
        const data = await response.json();
        alert(data.message);
        btn.innerHTML = response.ok ? '<i class="bi bi-check"></i>' : '<i class="bi bi-x"></i>';
        btn.classList.replace('btn-outline-success', response.ok ? 'btn-success' : 'btn-danger');
        setTimeout(() => {
            btn.innerHTML = originalText;
            btn.classList.replace(response.ok ? 'btn-success' : 'btn-danger', 'btn-outline-success');
            btn.disabled = false;
        }, 2000);
    } catch (error) {
        alert("Network error contacting backend."); btn.innerHTML = originalText; btn.disabled = false;
    }
}

function toggleWhisparrVersion(row) {
    const type = row.querySelector('.arr-type').value;
    const verSelect = row.querySelector('.arr-ver');
    const wspVerSelect = row.querySelector('.arr-wsp-ver');
    const label = row.querySelector('.arr-ver-label');
    if (type === 'whisparr') {
        verSelect.style.display = 'none';
        wspVerSelect.style.display = '';
        label.innerText = 'Lineage';
    } else {
        verSelect.style.display = '';
        wspVerSelect.style.display = 'none';
        label.innerText = 'API Ver';
    }
}

function onArrTypeChange(select) { toggleWhisparrVersion(select.closest('.arr-row')); }

function addArrRow(data = { enabled: true, name: '', type: 'radarr', url: '', api_key: '', category: '', api_version: 'auto', whisparr_version: 'v3', search_missing: true, unmonitor_has_file: false }) {
    const container = document.getElementById('arr-container');
    const row = document.createElement('div');
    row.className = 'row mb-2 align-items-end arr-row';
    row.innerHTML = `
        <div class="col-md-1"><label class="form-label small mb-1">Name</label><input type="text" class="form-control form-control-sm arr-name" value="${data.name}"></div>
        <div class="col-md-1"><label class="form-label small mb-1">Type</label><select class="form-select form-select-sm arr-type" onchange="onArrTypeChange(this)">${['radarr','sonarr','lidarr','readarr','whisparr','chaptarr'].map(t=>`<option value="${t}" ${data.type===t?'selected':''}>${t}</option>`).join('')}</select></div>
        <div class="col-md-1"><label class="form-label small mb-1 arr-ver-label">API Ver</label><select class="form-select form-select-sm arr-ver">${['auto','v3','v1'].map(v=>`<option value="${v}" ${data.api_version===v?'selected':''}>${v}</option>`).join('')}</select><select class="form-select form-select-sm arr-wsp-ver" style="display:none;">${['v3','v2'].map(v=>`<option value="${v}" ${data.whisparr_version===v?'selected':''}>Wsp ${v}</option>`).join('')}</select></div>
        <div class="col-md-1"><label class="form-label small mb-1">Category</label><input type="text" class="form-control form-control-sm arr-cat" value="${data.category||''}"></div>
        <div class="col-md-2"><label class="form-label small mb-1">URL</label><input type="text" class="form-control form-control-sm arr-url" value="${data.url}"></div>
        <div class="col-md-2"><label class="form-label small mb-1">API Key</label><input type="password" class="form-control form-control-sm arr-key" value="${data.api_key}"></div>
        <div class="col-md-1"><label class="form-label small mb-1">Enable</label><select class="form-select form-select-sm arr-enabled"><option value="true" ${data.enabled!==false?'selected':''}>Yes</option><option value="false" ${data.enabled===false?'selected':''}>No</option></select></div>
        <div class="col-md-1"><label class="form-label small mb-1">Search</label><select class="form-select form-select-sm arr-search-missing"><option value="true" ${data.search_missing!==false?'selected':''}>Yes</option><option value="false" ${data.search_missing===false?'selected':''}>No</option></select></div>
        <div class="col-md-1"><label class="form-label small mb-1">Unmonitor</label><select class="form-select form-select-sm arr-unmonitor"><option value="true" ${data.unmonitor_has_file===true?'selected':''}>Yes</option><option value="false" ${data.unmonitor_has_file!==true?'selected':''}>No</option></select></div>
        <div class="col-md-1"><label class="form-label small mb-1">Actions</label><div class="d-flex gap-2"><button type="button" class="btn btn-sm btn-outline-success w-50" onclick="testArr(this)">Test</button><button type="button" class="btn btn-sm btn-outline-danger w-50" onclick="this.closest('.arr-row').remove()"><i class="bi bi-trash"></i></button></div></div>
    `;
    container.appendChild(row); toggleWhisparrVersion(row);
}

document.getElementById('settings-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const arrs = [];
    document.querySelectorAll('.arr-row').forEach(row => {
        const entry = {
            enabled: row.querySelector('.arr-enabled').value === "true",
            search_missing: row.querySelector('.arr-search-missing').value === "true",
            unmonitor_has_file: row.querySelector('.arr-unmonitor').value === "true",
            name: row.querySelector('.arr-name').value.trim(),
            type: row.querySelector('.arr-type').value,
            api_version: row.querySelector('.arr-ver').value,
            category: row.querySelector('.arr-cat').value.trim(),
            url: row.querySelector('.arr-url').value.trim(),
            api_key: row.querySelector('.arr-key').value.trim()
        };
        if (entry.type === 'whisparr') entry.whisparr_version = row.querySelector('.arr-wsp-ver').value;
        if (entry.name && entry.url && entry.api_key) arrs.push(entry);
    });

    const mutedSources = [];
    document.querySelectorAll('.muted-source-toggle').forEach(cb => { if (!cb.checked) mutedSources.push(cb.dataset.source); });

    const sections = {};
    document.querySelectorAll('.digest-sec').forEach(cb => { sections[cb.value] = cb.checked; });

    // Schedule save-path: already uses || 0 (0 is the default), so 0
    // round-trips correctly. numOr not required here.
    const newConfig = {
        schedules_enabled: document.getElementById('schedules-enabled').checked,
        quarantine_limit_enabled: document.getElementById('q-limit-enabled').checked,
        // quarantine_limit: 0 = unlimited; numOr preserves 0.
        quarantine_limit: numOr('q-limit-val', 100),
        global_dry_run: document.getElementById('global-dry-run').checked,
        // history_retention: 0 = no retention; numOr preserves 0.
        history_retention: numOr('history-retention', 100),
        log_level: document.getElementById('log-level').value,
        log_to_file: document.getElementById('log-to-file').checked,
        unmonitor_mode: document.getElementById('unmonitor-mode').value,
        unmonitor_ignore_specials: document.getElementById('unmonitor-ignore-specials').checked,
        unmonitor_force_refresh: document.getElementById('unmonitor-force-refresh').checked,
        unmonitor_refresh_timeout_sec: parseInt(document.getElementById('unmonitor-refresh-timeout').value) || 600,
        security: {
            basic_auth_enabled: document.getElementById('sec-auth-enabled').checked,
            basic_auth_username: document.getElementById('sec-auth-user').value.trim(),
            basic_auth_password: document.getElementById('sec-auth-pass').value
        },
        qbit: { enabled: document.getElementById('qbit-enabled').checked, url: document.getElementById('qbit-url').value.trim(), auth_method: document.getElementById('qbit-auth-method').value, username: document.getElementById('qbit-user').value.trim(), password: document.getElementById('qbit-pass').value, api_key: document.getElementById('qbit-apikey').value.trim() },
        // Thresholds save-path: use numOr so 0 typed by user is preserved
        // instead of reverting to the default.
        thresholds: {
            meta_time: numOr('thresh-meta-val', 2), meta_unit: document.getElementById('thresh-meta-unit').value,
            stalled_time: numOr('thresh-stalled-val', 48), stalled_unit: document.getElementById('thresh-stalled-unit').value,
            unmanaged_time: numOr('thresh-unmanaged-val', 168), unmanaged_unit: document.getElementById('thresh-unmanaged-unit').value,
            slow_speed_val: numOr('thresh-speed-val', 10), slow_speed_unit: document.getElementById('thresh-speed-unit').value,
            max_percentage: numOr('thresh-max-pct', 100),
            target_100_seeds: document.getElementById('thresh-target-seeds-select').value === "true",
            blocked_extensions: document.getElementById('thresh-blocked-exts').value.trim(),
            approved_extensions: document.getElementById('thresh-approved-exts').value.trim(),
            missing_polite_mode: document.getElementById('thresh-missing-polite').checked,
            missing_batch_size: numOr('thresh-missing-batch', 3),
            missing_batch_mode: document.getElementById('thresh-missing-batch-mode').value,
            missing_cooldown_hours: numOr('thresh-missing-cooldown', 24),
            missing_max_retries: numOr('thresh-missing-retries', 5),
            quarantine_retention_days: numOr('q-retention-val', 7)
        },
        schedules: { 
            bt_backup_time: parseFloat(document.getElementById('sched-bt-val').value) || 0, bt_backup_unit: document.getElementById('sched-bt-unit').value, 
            stalled_time: parseFloat(document.getElementById('sched-stall-val').value) || 0, stalled_unit: document.getElementById('sched-stall-unit').value, 
            unmanaged_time: parseFloat(document.getElementById('sched-unmanaged-val').value) || 0, unmanaged_unit: document.getElementById('sched-unmanaged-unit').value, 
            extensions_time: parseFloat(document.getElementById('sched-exts-val').value) || 0, extensions_unit: document.getElementById('sched-exts-unit').value, 
            missing_time: parseFloat(document.getElementById('sched-missing-val').value) || 0, missing_unit: document.getElementById('sched-missing-unit').value, 
            quarantine_time: parseFloat(document.getElementById('sched-quarantine-val').value) || 0, quarantine_unit: document.getElementById('sched-quarantine-unit').value, 
            unmonitor_time: parseFloat(document.getElementById('sched-unmonitor-val').value) || 0, unmonitor_unit: document.getElementById('sched-unmonitor-unit').value, 
            arr_health_time: parseFloat(document.getElementById('sched-arr-health-val').value) || 0, arr_health_unit: document.getElementById('sched-arr-health-unit').value, 
            notify_time: parseFloat(document.getElementById('sched-notify-val').value) || 0, notify_unit: document.getElementById('sched-notify-unit').value,
            metrics_time: parseFloat(document.getElementById('sched-metrics-val').value) || 0, metrics_unit: document.getElementById('sched-metrics-unit').value
        },
        task_timeouts: { bt_backup: getTimeoutSecs('bt_backup'), unmanaged: getTimeoutSecs('unmanaged'), stalled: getTimeoutSecs('stalled'), extensions: getTimeoutSecs('extensions'), quarantine: getTimeoutSecs('quarantine'), arr_health: getTimeoutSecs('arr_health'), missing: getTimeoutSecs('missing'), unmonitor: getTimeoutSecs('unmonitor'), notify: getTimeoutSecs('notify'), metrics: getTimeoutSecs('metrics') },
        notifications: {
            enabled: document.getElementById('notif-enabled').checked,
            muted_sources: mutedSources,
            email: { smtp_host: document.getElementById('notif-smtp-host').value.trim(), smtp_port: parseInt(document.getElementById('notif-smtp-port').value) || 25, tls_mode: document.getElementById('notif-tls-mode').value, username: document.getElementById('notif-username').value.trim(), password: document.getElementById('notif-password').value, from_addr: document.getElementById('notif-from-addr').value.trim(), to_addrs: document.getElementById('notif-to-addrs').value.trim() },
            digest: { enabled: document.getElementById('digest-enabled').checked, frequency: document.getElementById('digest-freq').value, hour: numOr('digest-hour', 8), day_of_week: parseInt(document.getElementById('digest-dow').value) || 0, day_of_month: parseInt(document.getElementById('digest-dom').value) || 1, sections: sections }
        },
        paths: { external_torrent_dirs: [] },
        arrs: arrs
    };

    const btn = e.target.querySelector('button[type="submit"]');
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Saving...'; btn.disabled = true;
    try {
        const response = await fetch('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(newConfig) });
        if (response.ok) {
            const data = await response.json();
            btn.innerHTML = `<i class="bi bi-check-circle"></i> Saved!` + (data.suppressed > 0 ? ` Silenced ${data.suppressed} warnings.` : '');
            btn.classList.replace('btn-primary', 'btn-success');
            setTimeout(() => { btn.innerHTML = 'Save Settings'; btn.classList.replace('btn-success', 'btn-primary'); btn.disabled = false; }, 3000);
        } else { alert("Failed to save config."); }
    } catch (error) { console.error(error); alert("Error saving config."); }
});
