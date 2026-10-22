/**
 * Admin Panel Client-Side Controller.
 * Comprehensive management for:
 * 1. Incidents Ledger (Search, priority filter, status updates, idempotent Telegram PV retries)
 * 2. Employees (Add, edit, 1-click active/inactive toggle, soft/hard delete, Telegram link status)
 * 3. Units & Sections (Add, edit, 1-click toggle, safe delete with report audit protection, manager assignments)
 * 4. Issue Categories / Presets (Add, edit, 1-click toggle, unit scoping, sort order)
 * 5. Telegram Configuration (Bot token, Admin numeric PV ID, live connection testing)
 */

document.addEventListener('DOMContentLoaded', async () => {
    // 1. Detect page refresh / reload
    const navEntries = window.performance.getEntriesByType('navigation');
    const isReload = (navEntries.length > 0 && navEntries[0].type === 'reload')
                     || (window.performance.navigation && window.performance.navigation.type === 1);

    if (isReload) {
        // Enforce re-authentication on refresh/reload
        sessionStorage.removeItem('incident_admin_token');
        localStorage.removeItem('incident_admin_token');
        fetch('/api/admin/logout', { method: 'POST' }).catch(() => {});
        window.location.replace('/?open_admin=1');
        return;
    }

    // 2. Prevent Back/Forward cache retention
    window.addEventListener('pageshow', (event) => {
        if (event.persisted) {
            sessionStorage.removeItem('incident_admin_token');
            localStorage.removeItem('incident_admin_token');
            window.location.replace('/?open_admin=1');
        }
    });

    // 3. In-session token check
    let adminToken = sessionStorage.getItem('incident_admin_token') || null;
    if (!adminToken) {
        window.location.replace('/?open_admin=1');
        return;
    }

    let unitsData = [];
    let sectionsData = [];
    let usersData = [];
    let categoriesData = [];
    let selectedReportIds = new Set();
    let selectedUserIds = new Set();
    let selectedUnitIds = new Set();
    let selectedSectionIds = new Set();
    let selectedCategoryIds = new Set();

    const workspaceView = document.getElementById('admin-workspace-view');
    const btnLogout = document.getElementById('btn-admin-logout');

    function refreshIcons() {
        if (window.lucide && window.lucide.createIcons) {
            window.lucide.createIcons();
        }
    }

    async function apiAdminRequest(endpoint, options = {}) {
        options.headers = options.headers || {};
        options.headers['X-Admin-Token'] = adminToken;
        if (options.body && typeof options.body === 'object') {
            options.headers['Content-Type'] = 'application/json';
            options.body = JSON.stringify(options.body);
        }

        const res = await fetch(endpoint, options);
        if (res.status === 401) {
            adminToken = null;
            sessionStorage.removeItem('incident_admin_token');
            localStorage.removeItem('incident_admin_token');
            window.location.replace('/?open_admin=1');
            throw new Error("Session expired");
        }
        return res;
    }

    async function checkAuth() {
        if (!adminToken) {
            window.location.replace('/?open_admin=1');
            return;
        }
        try {
            const res = await fetch('/api/admin/verify-session', {
                headers: { 'X-Admin-Token': adminToken }
            });
            if (!res.ok) {
                adminToken = null;
                sessionStorage.removeItem('incident_admin_token');
                localStorage.removeItem('incident_admin_token');
                window.location.replace('/?open_admin=1');
                return;
            }
            if (workspaceView) workspaceView.style.display = 'block';
            if (btnLogout) btnLogout.style.display = 'inline-flex';
            loadActiveTab('tab-reports');
            refreshIcons();
        } catch (e) {
            window.location.replace('/?open_admin=1');
        }
    }

    if (btnLogout) {
        btnLogout.addEventListener('click', async () => {
            try {
                await fetch('/api/admin/logout', {
                    method: 'POST',
                    headers: { 'X-Admin-Token': adminToken || '' }
                });
            } catch (err) {
                console.error("Logout request error:", err);
            }
            adminToken = null;
            sessionStorage.removeItem('incident_admin_token');
            localStorage.removeItem('incident_admin_token');
            window.location.replace('/');
        });
    }

    // Verify authentication status immediately
    await checkAuth();

    // Tab Navigation
    document.querySelectorAll('.admin-tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const tabId = btn.getAttribute('data-tab');
            document.querySelectorAll('.admin-tab-btn').forEach(b => {
                b.classList.remove('btn-primary', 'active');
                b.classList.add('btn-secondary');
            });
            btn.classList.add('btn-primary', 'active');
            btn.classList.remove('btn-secondary');

            document.querySelectorAll('.admin-tab-pane').forEach(p => p.style.display = 'none');
            const targetPane = document.getElementById(tabId);
            if (targetPane) targetPane.style.display = 'block';

            loadActiveTab(tabId);
            refreshIcons();
        });
    });

    function loadActiveTab(tabId) {
        if (tabId === 'tab-reports') loadReports();
        if (tabId === 'tab-users') loadUsers();
        if (tabId === 'tab-units') loadHierarchy();
        if (tabId === 'tab-categories') loadCategories();
        if (tabId === 'tab-telegram') loadTelegramSettings();
    }

    // ==========================================
    // --- TAB 1: INCIDENTS MANAGEMENT ---
    // ==========================================
    async function loadReports() {
        const container = document.getElementById('admin-reports-table-container');
        if (!container) return;
        container.innerHTML = '<div style="padding: 24px; text-align: center; color: var(--text-muted);">Loading incidents...</div>';

        const search = document.getElementById('report-search-input')?.value.trim() || '';
        const status = document.getElementById('report-status-filter')?.value || '';
        const priorityFilter = document.getElementById('report-priority-filter')?.value || '';

        let url = '/api/admin/reports?';
        if (search) url += `search=${encodeURIComponent(search)}&`;
        if (status) url += `status_filter=${encodeURIComponent(status)}&`;
        if (priorityFilter) url += `priority_filter=${encodeURIComponent(priorityFilter)}&`;

        try {
            const res = await apiAdminRequest(url);
            const reports = await res.json();

            if (reports.length === 0) {
                container.innerHTML = `<div style="padding: 32px; text-align: center; background: var(--bg-secondary); border-radius: var(--radius-md); border: 1px solid var(--border-color); color: var(--text-muted);">No reports match current filters.</div>`;
                return;
            }

            function updateReportsBulkToolbar() {
                const bar = document.getElementById('reports-bulk-bar');
                const countSpan = document.getElementById('reports-selected-count');
                if (!bar || !countSpan) return;
                countSpan.textContent = selectedReportIds.size;
                if (selectedReportIds.size > 0) {
                    bar.classList.add('active');
                } else {
                    bar.classList.remove('active');
                }
            }

            container.innerHTML = reports.map(r => {
                const time = r.created_at.slice(0, 16).replace('T', ' ');
                const total = r.dispatch_total || 0;
                const sent = r.dispatch_sent || 0;
                const failed = r.dispatch_failed || 0;

                let dispatchBadge = '';
                if (r.telegram_dispatch_status === 'SENT') {
                    dispatchBadge = `<span class="badge badge-sent" title="All recipients received private alert"><i data-lucide="check"></i> PV Sent (${sent}/${total})</span>`;
                } else if (r.telegram_dispatch_status === 'PARTIAL') {
                    dispatchBadge = `<span class="badge" style="background: rgba(245, 158, 11, 0.2); color: var(--amber);" title="${sent} sent, ${failed} failed"><i data-lucide="alert-circle"></i> Partial PV (${sent}/${total})</span>`;
                } else if (r.telegram_dispatch_status === 'FAILED') {
                    dispatchBadge = `<span class="badge badge-failed" title="Delivery failed"><i data-lucide="alert-triangle"></i> PV Failed (${failed}/${total || 1})</span>`;
                } else {
                    dispatchBadge = `<span class="badge" style="background: rgba(148, 163, 184, 0.2); color: var(--text-muted);"><i data-lucide="clock"></i> PV Pending</span>`;
                }

                const isCrit = (r.priority || '').toUpperCase() === 'CRITICAL';
                const prioBadge = isCrit
                    ? `<span class="badge badge-priority-critical">🔴 Critical</span>`
                    : `<span class="badge badge-priority-normal">🟡 Normal</span>`;

                const isTg = (r.source || '').toLowerCase() === 'telegram';
                const sourceBadge = isTg
                    ? `<span class="badge" style="background: rgba(14, 165, 233, 0.15); color: #0284c7; font-weight: 600;" title="ثبت شده از طریق ربات تلگرام"><i data-lucide="bot"></i> Telegram</span>`
                    : `<span class="badge" style="background: rgba(16, 185, 129, 0.15); color: #059669; font-weight: 600;" title="ثبت شده از طریق سامانه وب"><i data-lucide="globe"></i> Web</span>`;

                return `
                    <div class="incident-card">
                        <div class="incident-card-header">
                            <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
                                <input type="checkbox" class="report-select-cb" data-id="${r.id}" ${selectedReportIds.has(r.id) ? 'checked' : ''} style="cursor: pointer; width: 16px; height: 16px; accent-color: var(--primary);" title="Select for bulk delete">
                                <a href="/reports/${r.id}" target="_blank" style="font-size: 1.1rem; font-weight: 700; color: var(--primary); text-decoration: none;">#${r.tracking_code}</a>
                                <span style="font-weight: 600; color: var(--text-primary);">${r.section_name && r.section_name !== r.unit_name ? `${r.unit_name} / ${r.section_name}` : r.unit_name}</span>
                                ${prioBadge}
                                ${sourceBadge}
                                ${r.preset_tag ? `<span class="badge" style="background: rgba(99, 102, 241, 0.15); color: var(--primary);">${r.preset_tag}</span>` : ''}
                            </div>
                            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                                ${dispatchBadge}
                                <span style="font-size: 0.8rem; color: var(--text-muted);">${time}</span>
                            </div>
                        </div>

                        <div class="incident-card-body">
                            ${r.description}
                        </div>

                        <div class="incident-card-footer">
                            <div style="font-size: 0.85rem; color: var(--text-muted);">
                                Reported by: <strong style="color: var(--text-primary);">${r.reporter_name}</strong>
                            </div>
                            <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
                                <select class="form-control select-status-changer" data-id="${r.id}" style="font-size: 0.8rem; padding: 5px 10px; width: auto; min-width: 110px;">
                                    <option value="Pending" ${r.status === 'Pending' ? 'selected' : ''}>Pending</option>
                                    <option value="In Progress" ${r.status === 'In Progress' ? 'selected' : ''}>In Progress</option>
                                    <option value="Resolved" ${r.status === 'Resolved' ? 'selected' : ''}>Resolved</option>
                                    <option value="Closed" ${r.status === 'Closed' ? 'selected' : ''}>Closed</option>
                                </select>
                                <button class="btn btn-secondary btn-xs btn-retry-dispatch" data-id="${r.id}" title="Re-dispatch PV notification for pending or failed recipients">
                                    <i data-lucide="send" style="width: 12px; height: 12px;"></i>
                                    <span>Retry PV</span>
                                </button>
                                <a href="/reports/${r.id}" target="_blank" class="btn btn-secondary btn-xs" style="text-decoration: none;">
                                    <i data-lucide="external-link" style="width: 12px; height: 12px;"></i> Details
                                </a>
                                <button class="btn btn-secondary btn-xs btn-delete-report" data-id="${r.id}" data-code="${r.tracking_code}" style="color: var(--rose);" title="Permanently delete incident report">
                                    <i data-lucide="trash-2" style="width: 12px; height: 12px;"></i>
                                    <span>Delete</span>
                                </button>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');

            container.querySelectorAll('.report-select-cb').forEach(cb => {
                cb.addEventListener('change', (e) => {
                    const id = parseInt(e.target.getAttribute('data-id'));
                    if (e.target.checked) {
                        selectedReportIds.add(id);
                    } else {
                        selectedReportIds.delete(id);
                    }
                    updateReportsBulkToolbar();
                });
            });

            container.querySelectorAll('.btn-delete-report').forEach(btn => {
                btn.addEventListener('click', async () => {
                    const id = parseInt(btn.getAttribute('data-id'));
                    const code = btn.getAttribute('data-code') || id;
                    if (!confirm(`Are you sure you want to permanently delete report #${code}?`)) return;
                    btn.disabled = true;
                    try {
                        const res = await apiAdminRequest(`/api/admin/reports/${id}`, { method: 'DELETE' });
                        const resData = await res.json();
                        alert(resData.message || "Report deleted.");
                        selectedReportIds.delete(id);
                        loadReports();
                    } catch(err) {
                        alert("Failed to delete report.");
                        loadReports();
                    }
                });
            });

            container.querySelectorAll('.select-status-changer').forEach(sel => {
                sel.addEventListener('change', async (e) => {
                    const id = e.target.getAttribute('data-id');
                    const newStatus = e.target.value;
                    await apiAdminRequest(`/api/admin/reports/${id}/status`, {
                        method: 'PATCH',
                        body: { status: newStatus }
                    });
                    loadReports();
                });
            });

            container.querySelectorAll('.btn-retry-dispatch').forEach(btn => {
                btn.addEventListener('click', async () => {
                    const id = btn.getAttribute('data-id');
                    btn.disabled = true;
                    const res = await apiAdminRequest(`/api/admin/reports/${id}/retry-dispatch`, { method: 'POST' });
                    const resData = await res.json();
                    alert(resData.message || "Telegram private dispatch re-enqueued.");
                    loadReports();
                });
            });

            updateReportsBulkToolbar();

        } catch (e) {
            container.innerHTML = '<div style="color: var(--rose); padding: 20px;">Error loading reports.</div>';
        }
        refreshIcons();
    }

    document.getElementById('report-search-input')?.addEventListener('input', () => loadReports());
    document.getElementById('report-status-filter')?.addEventListener('change', () => loadReports());
    document.getElementById('report-priority-filter')?.addEventListener('change', () => loadReports());
    document.getElementById('btn-refresh-reports')?.addEventListener('click', () => loadReports());

    document.getElementById('btn-reports-select-all')?.addEventListener('click', () => {
        document.querySelectorAll('.report-select-cb').forEach(cb => {
            cb.checked = true;
            selectedReportIds.add(parseInt(cb.getAttribute('data-id')));
        });
        const bar = document.getElementById('reports-bulk-bar');
        const countSpan = document.getElementById('reports-selected-count');
        if (countSpan) countSpan.textContent = selectedReportIds.size;
        if (bar && selectedReportIds.size > 0) bar.classList.add('active');
    });

    document.getElementById('btn-reports-clear-select')?.addEventListener('click', () => {
        selectedReportIds.clear();
        document.querySelectorAll('.report-select-cb').forEach(cb => { cb.checked = false; });
        const bar = document.getElementById('reports-bulk-bar');
        const countSpan = document.getElementById('reports-selected-count');
        if (countSpan) countSpan.textContent = 0;
        if (bar) bar.classList.remove('active');
    });

    document.getElementById('btn-reports-bulk-delete')?.addEventListener('click', async () => {
        if (selectedReportIds.size === 0) return;
        if (!confirm(`Are you sure you want to permanently delete ${selectedReportIds.size} selected report(s)? This action cannot be undone.`)) return;
        const ids = Array.from(selectedReportIds);
        try {
            const res = await apiAdminRequest('/api/admin/reports/bulk-delete', {
                method: 'POST',
                body: { ids: ids }
            });
            const resData = await res.json();
            alert(resData.message || "Reports deleted successfully.");
            selectedReportIds.clear();
            loadReports();
        } catch(err) {
            alert("Failed to delete selected reports.");
        }
    });


    // ==========================================
    // --- TAB 2: EMPLOYEES MANAGEMENT ---
    // ==========================================
    const userModal = document.getElementById('user-modal');

    async function loadUsers() {
        const container = document.getElementById('users-table-container');
        if (!container) return;
        container.innerHTML = '<div style="padding: 16px; color: var(--text-muted); text-align: center;">Loading staff directory...</div>';

        const filter = document.getElementById('users-status-filter')?.value || 'all';

        try {
            const res = await apiAdminRequest(`/api/admin/users?status_filter=${filter}`);
            usersData = await res.json();

            if (usersData.length === 0) {
                container.innerHTML = '<div style="padding: 24px; text-align: center; color: var(--text-muted); background: var(--bg-secondary); border-radius: var(--radius-md); border: 1px solid var(--border-color);">No employees match filter.</div>';
                return;
            }

            function updateUsersBulkToolbar() {
                const bar = document.getElementById('users-bulk-bar');
                const countSpan = document.getElementById('users-selected-count');
                if (!bar || !countSpan) return;
                countSpan.textContent = selectedUserIds.size;
                if (selectedUserIds.size > 0) {
                    bar.classList.add('active');
                } else {
                    bar.classList.remove('active');
                }
                const headerCb = document.getElementById('users-select-all-cb');
                if (headerCb) {
                    const selectableCount = usersData.filter(u => u.role !== 'Admin').length;
                    headerCb.checked = selectableCount > 0 && selectedUserIds.size === selectableCount;
                }
            }

            container.innerHTML = `
                <div class="table-responsive">
                    <table class="data-table table-responsive-cards">
                        <thead>
                            <tr>
                                <th style="width: 36px;">
                                    <input type="checkbox" id="users-select-all-cb" style="cursor: pointer; width: 16px; height: 16px; accent-color: var(--primary);" title="Select all employees">
                                </th>
                                <th>Employee</th>
                                <th>Telegram User ID</th>
                                <th>Status</th>
                                <th style="text-align: right;">Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${usersData.map(u => {
                                const isAdmin = (u.role === 'Admin');

                                const tgBadge = u.telegram_id
                                    ? `<span class="badge" style="background: rgba(16, 185, 129, 0.15); color: var(--emerald); font-weight: 600;">🟢 <code>${u.telegram_id}</code></span>`
                                    : `<span class="badge" style="background: rgba(245, 158, 11, 0.15); color: var(--amber); font-weight: 600;" title="Telegram User ID is missing. Click Edit to enter numeric Telegram ID.">⚠️ Incomplete Info (Needs Telegram ID)</span>`;

                                const activeBadge = u.is_active
                                    ? `<span class="badge badge-sent">Active</span>`
                                    : `<span class="badge" style="background: rgba(239, 68, 68, 0.15); color: var(--rose);">Inactive</span>`;

                                return `
                                    <tr>
                                        <td class="td-checkbox">
                                            <input type="checkbox" class="user-select-cb" data-id="${u.id}" ${selectedUserIds.has(u.id) ? 'checked' : ''} ${isAdmin ? 'disabled title="Master admin cannot be deleted"' : 'style="cursor: pointer; width: 16px; height: 16px; accent-color: var(--primary);" title="Select employee"'}>
                                        </td>
                                        <td data-label="Employee">
                                            <div style="font-weight: 600; color: var(--text-primary); font-size: 0.95rem; display: flex; align-items: center; gap: 8px;">
                                                <span>${u.name}</span>
                                                ${isAdmin ? `<span class="badge" style="background: rgba(239, 68, 68, 0.15); color: var(--rose); font-weight: 700;">Admin</span>` : ''}
                                            </div>
                                        </td>
                                        <td data-label="Telegram PV">
                                            ${tgBadge}
                                        </td>
                                        <td data-label="Status">${activeBadge}</td>
                                        <td class="td-actions" data-label="Actions">
                                            <div style="display: inline-flex; gap: 6px; flex-wrap: wrap;">
                                                <button class="btn btn-secondary btn-xs btn-edit-user" data-id="${u.id}">Edit</button>
                                                <button class="btn btn-secondary btn-xs btn-toggle-user" data-id="${u.id}">
                                                    ${u.is_active ? 'Deactivate' : 'Activate'}
                                                </button>
                                                <button class="btn btn-secondary btn-xs btn-delete-user" data-id="${u.id}" style="color: var(--rose);" ${isAdmin ? 'disabled title="Cannot delete master admin"' : ''}>Delete</button>
                                            </div>
                                        </td>
                                    </tr>
                                `;
                            }).join('')}
                        </tbody>
                    </table>
                </div>
            `;

            // Row Checkboxes
            container.querySelectorAll('.user-select-cb').forEach(cb => {
                cb.addEventListener('change', (e) => {
                    const uid = parseInt(e.target.getAttribute('data-id'));
                    if (e.target.checked) selectedUserIds.add(uid);
                    else selectedUserIds.delete(uid);
                    updateUsersBulkToolbar();
                });
            });

            // Header Checkbox
            document.getElementById('users-select-all-cb')?.addEventListener('change', (e) => {
                const isChecked = e.target.checked;
                container.querySelectorAll('.user-select-cb:not(:disabled)').forEach(cb => {
                    cb.checked = isChecked;
                    const uid = parseInt(cb.getAttribute('data-id'));
                    if (isChecked) selectedUserIds.add(uid);
                    else selectedUserIds.delete(uid);
                });
                updateUsersBulkToolbar();
            });

            updateUsersBulkToolbar();

            // Action Listeners
            container.querySelectorAll('.btn-edit-user').forEach(b => {
                b.addEventListener('click', () => {
                    const uid = parseInt(b.getAttribute('data-id'));
                    const u = usersData.find(x => x.id === uid);
                    if (!u) return;

                    document.getElementById('user-modal-title').innerText = `Edit Employee: ${u.name}`;
                    document.getElementById('crud-user-id').value = u.id;
                    document.getElementById('crud-user-name').value = u.name;
                    document.getElementById('crud-user-tg-id').value = u.telegram_id || '';
                    document.getElementById('crud-user-tg-id').required = false;
                    const reqMark = document.getElementById('crud-tg-id-required-mark');
                    if (reqMark) reqMark.style.display = u.telegram_id ? 'inline' : 'none';
                    document.getElementById('crud-user-active').checked = Boolean(u.is_active);
                    document.getElementById('btn-save-user-submit').innerText = 'Update Employee';

                    userModal.classList.add('active');
                });
            });

            container.querySelectorAll('.btn-toggle-user').forEach(b => {
                b.addEventListener('click', async () => {
                    const uid = b.getAttribute('data-id');
                    b.disabled = true;
                    await apiAdminRequest(`/api/admin/users/${uid}/toggle-active`, { method: 'PATCH' });
                    loadUsers();
                });
            });

            container.querySelectorAll('.btn-delete-user').forEach(b => {
                b.addEventListener('click', async () => {
                    const uid = b.getAttribute('data-id');
                    const u = usersData.find(x => x.id === parseInt(uid));
                    if (!confirm(`Are you sure you want to remove '${u ? u.name : 'this user'}'? If they have historical reports, they will be safely deactivated.`)) return;

                    b.disabled = true;
                    const res = await apiAdminRequest(`/api/admin/users/${uid}`, { method: 'DELETE' });
                    const resData = await res.json();
                    alert(resData.message || "User operation complete.");
                    selectedUserIds.delete(parseInt(uid));
                    loadUsers();
                });
            });

        } catch (e) {
            container.innerHTML = '<div style="color: var(--rose); padding: 16px;">Failed to load employees list.</div>';
        }
        refreshIcons();
    }

    document.getElementById('users-status-filter')?.addEventListener('change', () => loadUsers());

    document.getElementById('btn-users-select-all')?.addEventListener('click', () => {
        document.querySelectorAll('.user-select-cb:not(:disabled)').forEach(cb => {
            cb.checked = true;
            selectedUserIds.add(parseInt(cb.getAttribute('data-id')));
        });
        const headerCb = document.getElementById('users-select-all-cb');
        if (headerCb) headerCb.checked = true;
        const bar = document.getElementById('users-bulk-bar');
        const countSpan = document.getElementById('users-selected-count');
        if (countSpan) countSpan.textContent = selectedUserIds.size;
        if (bar && selectedUserIds.size > 0) bar.classList.add('active');
    });

    document.getElementById('btn-users-clear-select')?.addEventListener('click', () => {
        selectedUserIds.clear();
        document.querySelectorAll('.user-select-cb').forEach(cb => { cb.checked = false; });
        const headerCb = document.getElementById('users-select-all-cb');
        if (headerCb) headerCb.checked = false;
        const bar = document.getElementById('users-bulk-bar');
        const countSpan = document.getElementById('users-selected-count');
        if (countSpan) countSpan.textContent = 0;
        if (bar) bar.classList.remove('active');
    });

    document.getElementById('btn-users-bulk-delete')?.addEventListener('click', async () => {
        if (selectedUserIds.size === 0) return;
        if (!confirm(`Are you sure you want to remove ${selectedUserIds.size} selected employee(s)? Employees with historical reports will be deactivated to preserve history.`)) return;
        const ids = Array.from(selectedUserIds);
        try {
            const res = await apiAdminRequest('/api/admin/users/bulk-delete', {
                method: 'POST',
                body: { ids: ids }
            });
            const resData = await res.json();
            alert(resData.message || "Staff members processed successfully.");
            selectedUserIds.clear();
            loadUsers();
        } catch(err) {
            alert("Failed to delete selected employees.");
        }
    });

    document.getElementById('btn-add-user')?.addEventListener('click', () => {
        document.getElementById('user-modal-title').innerText = 'Add New Employee';
        document.getElementById('user-crud-form').reset();
        document.getElementById('crud-user-id').value = '';
        document.getElementById('crud-user-name').value = '';
        document.getElementById('crud-user-tg-id').value = '';
        document.getElementById('crud-user-tg-id').required = true;
        const reqMark = document.getElementById('crud-tg-id-required-mark');
        if (reqMark) reqMark.style.display = 'inline';
        document.getElementById('crud-user-active').checked = true;
        document.getElementById('btn-save-user-submit').innerText = 'Save Staff Member';
        userModal.classList.add('active');
    });

    document.getElementById('btn-cancel-user-modal')?.addEventListener('click', () => {
        userModal.classList.remove('active');
    });

    document.getElementById('user-crud-form')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const uid = document.getElementById('crud-user-id').value;
        const isEdit = Boolean(uid);
        const name = document.getElementById('crud-user-name').value.trim();
        const rawTgId = document.getElementById('crud-user-tg-id').value.trim();

        if (!name) {
            alert("Employee Name is required.");
            document.getElementById('crud-user-name').focus();
            return;
        }

        if (!isEdit && !rawTgId) {
            alert("Telegram User ID is required when adding a new employee.");
            document.getElementById('crud-user-tg-id').focus();
            return;
        }

        if (rawTgId) {
            if (rawTgId.startsWith('@')) {
                alert("Invalid Telegram User ID: You entered a username ('@...'). Telegram User ID must be a numeric account ID (digits only, e.g. 123456789). Usernames like @name are not allowed.");
                document.getElementById('crud-user-tg-id').focus();
                return;
            }
            if (!/^\d+$/.test(rawTgId)) {
                alert("Invalid Telegram User ID: Must contain digits only (e.g. 123456789). Letters, symbols, and usernames are not allowed.");
                document.getElementById('crud-user-tg-id').focus();
                return;
            }
            if (rawTgId.length < 5 || rawTgId.length > 20) {
                alert("Invalid Telegram User ID: Telegram account IDs typically contain between 5 and 20 digits.");
                document.getElementById('crud-user-tg-id').focus();
                return;
            }
        }

        let existingUser = null;
        if (isEdit) {
            existingUser = usersData.find(x => x.id === parseInt(uid));
        }

        const payload = {
            name: name,
            telegram_id: rawTgId || null,
            role: existingUser ? existingUser.role : 'Employee',
            position: existingUser ? existingUser.position : null,
            unit: existingUser ? existingUser.unit : null,
            work_hours: existingUser ? existingUser.work_hours : null,
            work_location: existingUser ? existingUser.work_location : null,
            special_conditions: existingUser ? existingUser.special_conditions : [],
            managed_units: existingUser ? existingUser.managed_units : null,
            is_active: document.getElementById('crud-user-active').checked
        };

        const url = isEdit ? `/api/admin/users/${uid}` : '/api/admin/users';
        const method = isEdit ? 'PUT' : 'POST';

        const res = await apiAdminRequest(url, { method: method, body: payload });
        if (res.ok) {
            userModal.classList.remove('active');
            loadUsers();
        } else {
            const err = await res.json();
            alert("Error: " + (err.detail || "Failed to save employee."));
        }
    });


    // ==========================================
    // --- TAB 3: UNITS & SECTIONS MANAGEMENT ---
    // ==========================================
    const unitModal = document.getElementById('unit-modal');
    const sectionModal = document.getElementById('section-modal');

    async function loadHierarchy() {
        const tree = document.getElementById('units-hierarchy-tree');
        if (!tree) return;
        tree.innerHTML = '<div style="color: var(--text-muted); padding: 16px; text-align: center;">Loading units & sections...</div>';

        try {
            const res = await apiAdminRequest('/api/admin/units-sections');
            const data = await res.json();
            unitsData = data.units || [];
            sectionsData = data.sections || [];

            if (unitsData.length === 0) {
                tree.innerHTML = '<div style="padding: 24px; text-align: center; color: var(--text-muted); background: var(--bg-secondary); border-radius: var(--radius-md); border: 1px solid var(--border-color);">No units configured yet. Click "+ Add Unit" to create one.</div>';
                return;
            }

            function updateUnitsBulkToolbar() {
                const bar = document.getElementById('units-bulk-bar');
                const countSpan = document.getElementById('units-selected-count');
                if (!bar || !countSpan) return;
                const total = selectedUnitIds.size + selectedSectionIds.size;
                countSpan.textContent = total;
                if (total > 0) {
                    bar.classList.add('active');
                } else {
                    bar.classList.remove('active');
                }
            }

            tree.innerHTML = unitsData.map(u => {
                const unitSecs = sectionsData.filter(s => s.unit_id === u.id);
                const activeBadge = u.is_active
                    ? `<span class="badge badge-sent">Active Unit</span>`
                    : `<span class="badge" style="background: rgba(239, 68, 68, 0.15); color: var(--rose);">Inactive Unit</span>`;

                return `
                    <div style="background: var(--bg-secondary); border: 1px solid var(--border-color); border-radius: var(--radius-md); padding: 20px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; flex-wrap: wrap; gap: 8px;">
                            <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
                                <input type="checkbox" class="unit-select-cb" data-unit-id="${u.id}" ${selectedUnitIds.has(u.id) ? 'checked' : ''} style="cursor: pointer; width: 16px; height: 16px; accent-color: var(--primary);" title="Select unit for bulk delete">
                                <strong style="font-size: 1.2rem; color: var(--primary);">${u.name}</strong>
                                ${activeBadge}
                                <span style="font-size: 0.8rem; color: var(--text-muted);">${unitSecs.length} sections</span>
                                <span style="font-size: 0.8rem; color: var(--text-secondary);">(${u.report_count || 0} historical reports)</span>
                            </div>
                            <div style="display: flex; gap: 6px; flex-wrap: wrap;">
                                <button class="btn btn-secondary btn-xs btn-add-sec-to-unit" data-unit-id="${u.id}">+ Add Section</button>
                                <button class="btn btn-secondary btn-xs btn-edit-unit" data-unit-id="${u.id}">Edit</button>
                                <button class="btn btn-secondary btn-xs btn-toggle-unit" data-unit-id="${u.id}">
                                    ${u.is_active ? 'Deactivate' : 'Activate'}
                                </button>
                                <button class="btn btn-secondary btn-xs btn-delete-unit" data-unit-id="${u.id}" style="color: var(--rose);">Delete</button>
                            </div>
                        </div>

                        ${u.description ? `<p style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 14px;">${u.description}</p>` : ''}

                        <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 260px), 1fr)); gap: 10px;">
                            ${unitSecs.map(s => {
                                const secActiveBadge = s.is_active
                                    ? `<span style="font-size: 0.7rem; color: var(--emerald);">● Active</span>`
                                    : `<span style="font-size: 0.7rem; color: var(--rose);">● Inactive</span>`;

                                return `
                                    <div style="background: rgba(255,255,255,0.02); border: 1px solid var(--border-color); border-radius: var(--radius-sm); padding: 12px; display: flex; flex-direction: column; justify-content: space-between;">
                                        <div>
                                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                                                <div style="display: flex; align-items: center; gap: 8px;">
                                                    <input type="checkbox" class="section-select-cb" data-sec-id="${s.id}" ${selectedSectionIds.has(s.id) ? 'checked' : ''} style="cursor: pointer; width: 14px; height: 14px; accent-color: var(--primary);" title="Select section for bulk delete">
                                                    <strong style="font-size: 0.95rem; color: var(--text-primary);">${s.name}</strong>
                                                </div>
                                                ${secActiveBadge}
                                            </div>
                                            <div style="font-size: 0.78rem; color: var(--text-muted); margin-bottom: 8px;">${s.description || 'General section scope'}</div>
                                            <div style="font-size: 0.75rem; color: var(--primary);">
                                                🔔 ${s.manager_ids.length} Designated Managers
                                            </div>
                                        </div>
                                        <div style="display: flex; justify-content: flex-end; gap: 6px; flex-wrap: wrap; margin-top: 10px; border-top: 1px solid rgba(255,255,255,0.04); padding-top: 8px;">
                                            <button class="btn btn-secondary btn-xs btn-edit-sec" data-sec-id="${s.id}">Edit</button>
                                            <button class="btn btn-secondary btn-xs btn-toggle-sec" data-sec-id="${s.id}">
                                                ${s.is_active ? 'Deactivate' : 'Activate'}
                                            </button>
                                            <button class="btn btn-secondary btn-xs btn-delete-sec" data-sec-id="${s.id}" style="color: var(--rose);">Delete</button>
                                        </div>
                                    </div>
                                `;
                            }).join('')}
                        </div>
                    </div>
                `;
            }).join('');

            // Unit Checkbox Listeners
            tree.querySelectorAll('.unit-select-cb').forEach(cb => {
                cb.addEventListener('change', (e) => {
                    const uid = parseInt(e.target.getAttribute('data-unit-id'));
                    if (e.target.checked) selectedUnitIds.add(uid);
                    else selectedUnitIds.delete(uid);
                    updateUnitsBulkToolbar();
                });
            });

            // Section Checkbox Listeners
            tree.querySelectorAll('.section-select-cb').forEach(cb => {
                cb.addEventListener('change', (e) => {
                    const sid = parseInt(e.target.getAttribute('data-sec-id'));
                    if (e.target.checked) selectedSectionIds.add(sid);
                    else selectedSectionIds.delete(sid);
                    updateUnitsBulkToolbar();
                });
            });

            updateUnitsBulkToolbar();

            // Unit Action Handlers
            tree.querySelectorAll('.btn-edit-unit').forEach(b => {
                b.addEventListener('click', () => {
                    const uid = parseInt(b.getAttribute('data-unit-id'));
                    const u = unitsData.find(x => x.id === uid);
                    if (!u) return;

                    document.getElementById('unit-modal-title').innerText = `Edit Unit: ${u.name}`;
                    document.getElementById('crud-unit-id').value = u.id;
                    document.getElementById('crud-unit-name').value = u.name;
                    document.getElementById('crud-unit-icon').value = u.icon || 'layers';
                    document.getElementById('crud-unit-desc').value = u.description || '';
                    document.getElementById('crud-unit-sort').value = u.sort_order || 0;
                    document.getElementById('crud-unit-active').checked = Boolean(u.is_active);
                    document.getElementById('btn-save-unit-submit').innerText = 'Update Unit';

                    unitModal.classList.add('active');
                });
            });

            tree.querySelectorAll('.btn-toggle-unit').forEach(b => {
                b.addEventListener('click', async () => {
                    const uid = b.getAttribute('data-unit-id');
                    b.disabled = true;
                    await apiAdminRequest(`/api/admin/units/${uid}/toggle-active`, { method: 'PATCH' });
                    loadHierarchy();
                });
            });

            tree.querySelectorAll('.btn-delete-unit').forEach(b => {
                b.addEventListener('click', async () => {
                    const uid = b.getAttribute('data-unit-id');
                    const u = unitsData.find(x => x.id === parseInt(uid));
                    if (!confirm(`Are you sure you want to remove unit '${u ? u.name : ''}'? If it has historical reports, it will be safely deactivated.`)) return;

                    b.disabled = true;
                    const res = await apiAdminRequest(`/api/admin/units/${uid}`, { method: 'DELETE' });
                    const resData = await res.json();
                    alert(resData.message || "Unit operation complete.");
                    selectedUnitIds.delete(parseInt(uid));
                    loadHierarchy();
                });
            });

            tree.querySelectorAll('.btn-add-sec-to-unit').forEach(b => {
                b.addEventListener('click', async () => {
                    const uid = parseInt(b.getAttribute('data-unit-id'));
                    openSectionModal(null, uid);
                });
            });

            // Section Action Handlers
            tree.querySelectorAll('.btn-edit-sec').forEach(b => {
                b.addEventListener('click', () => {
                    const sid = parseInt(b.getAttribute('data-sec-id'));
                    openSectionModal(sid);
                });
            });

            tree.querySelectorAll('.btn-toggle-sec').forEach(b => {
                b.addEventListener('click', async () => {
                    const sid = b.getAttribute('data-sec-id');
                    b.disabled = true;
                    await apiAdminRequest(`/api/admin/sections/${sid}/toggle-active`, { method: 'PATCH' });
                    loadHierarchy();
                });
            });

            tree.querySelectorAll('.btn-delete-sec').forEach(b => {
                b.addEventListener('click', async () => {
                    const sid = b.getAttribute('data-sec-id');
                    const s = sectionsData.find(x => x.id === parseInt(sid));
                    if (!confirm(`Are you sure you want to remove section '${s ? s.name : ''}'?`)) return;

                    b.disabled = true;
                    const res = await apiAdminRequest(`/api/admin/sections/${sid}`, { method: 'DELETE' });
                    const resData = await res.json();
                    alert(resData.message || "Section operation complete.");
                    selectedSectionIds.delete(parseInt(sid));
                    loadHierarchy();
                });
            });

        } catch (e) {
            tree.innerHTML = '<div style="color: var(--rose); padding: 16px;">Failed to load hierarchy.</div>';
        }
        refreshIcons();
    }

    document.getElementById('btn-units-clear-select')?.addEventListener('click', () => {
        selectedUnitIds.clear();
        selectedSectionIds.clear();
        document.querySelectorAll('.unit-select-cb, .section-select-cb').forEach(cb => { cb.checked = false; });
        const bar = document.getElementById('units-bulk-bar');
        const countSpan = document.getElementById('units-selected-count');
        if (countSpan) countSpan.textContent = 0;
        if (bar) bar.classList.remove('active');
    });

    document.getElementById('btn-units-bulk-delete')?.addEventListener('click', async () => {
        const total = selectedUnitIds.size + selectedSectionIds.size;
        if (total === 0) return;
        if (!confirm(`Are you sure you want to remove ${selectedUnitIds.size} unit(s) and ${selectedSectionIds.size} section(s)? Entities with historical reports will be safely deactivated.`)) return;
        
        let messages = [];
        try {
            if (selectedSectionIds.size > 0) {
                const res = await apiAdminRequest('/api/admin/sections/bulk-delete', {
                    method: 'POST',
                    body: { ids: Array.from(selectedSectionIds) }
                });
                const resData = await res.json();
                messages.push(resData.message || "Sections processed.");
                selectedSectionIds.clear();
            }
            if (selectedUnitIds.size > 0) {
                const res = await apiAdminRequest('/api/admin/units/bulk-delete', {
                    method: 'POST',
                    body: { ids: Array.from(selectedUnitIds) }
                });
                const resData = await res.json();
                messages.push(resData.message || "Units processed.");
                selectedUnitIds.clear();
            }
            alert(messages.join("\n"));
            loadHierarchy();
        } catch(err) {
            alert("Failed to delete selected units/sections.");
        }
    });

    // Modal: Unit Add / Edit
    document.getElementById('btn-add-unit')?.addEventListener('click', () => {
        document.getElementById('unit-modal-title').innerText = 'Add New Unit';
        document.getElementById('unit-crud-form').reset();
        document.getElementById('crud-unit-id').value = '';
        document.getElementById('crud-unit-sort').value = (unitsData.length + 1) * 10;
        document.getElementById('crud-unit-active').checked = true;
        document.getElementById('btn-save-unit-submit').innerText = 'Create Unit';
        unitModal.classList.add('active');
    });

    document.getElementById('btn-cancel-unit-modal')?.addEventListener('click', () => {
        unitModal.classList.remove('active');
    });

    document.getElementById('unit-crud-form')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const uid = document.getElementById('crud-unit-id').value;
        const payload = {
            name: document.getElementById('crud-unit-name').value.trim(),
            icon: document.getElementById('crud-unit-icon').value.trim() || 'layers',
            description: document.getElementById('crud-unit-desc').value.trim(),
            sort_order: parseInt(document.getElementById('crud-unit-sort').value) || 0,
            is_active: document.getElementById('crud-unit-active').checked
        };

        const isEdit = Boolean(uid);
        const url = isEdit ? `/api/admin/units/${uid}` : '/api/admin/units';
        const method = isEdit ? 'PUT' : 'POST';

        const res = await apiAdminRequest(url, { method: method, body: payload });
        if (res.ok) {
            unitModal.classList.remove('active');
            loadHierarchy();
        } else {
            const err = await res.json();
            alert("Error: " + (err.detail || "Failed to save unit."));
        }
    });

    // Modal: Section Add / Edit
    async function openSectionModal(sectionId = null, preselectedUnitId = null) {
        const unitSelect = document.getElementById('crud-sec-unit');
        const mgrSelect = document.getElementById('crud-sec-managers');

        // Populate unit dropdown
        unitSelect.innerHTML = unitsData.map(u => `<option value="${u.id}">${u.name}</option>`).join('');

        // Populate staff for managers
        const uRes = await apiAdminRequest('/api/admin/users?status_filter=active');
        const activeUsers = await uRes.json();
        mgrSelect.innerHTML = activeUsers.map(u => `<option value="${u.id}">${u.name}</option>`).join('');

        if (sectionId) {
            const s = sectionsData.find(x => x.id === sectionId);
            if (!s) return;
            document.getElementById('section-modal-title').innerText = `Edit Section: ${s.name}`;
            document.getElementById('crud-sec-id').value = s.id;
            unitSelect.value = s.unit_id;
            document.getElementById('crud-sec-name').value = s.name;
            document.getElementById('crud-sec-desc').value = s.description || '';
            document.getElementById('crud-sec-sort').value = s.sort_order || 0;
            document.getElementById('crud-sec-active').checked = Boolean(s.is_active);

            // Select managers
            const mgrIds = s.manager_ids || [];
            Array.from(mgrSelect.options).forEach(opt => {
                opt.selected = mgrIds.includes(parseInt(opt.value));
            });
            document.getElementById('btn-save-sec-submit').innerText = 'Update Section';
        } else {
            document.getElementById('section-modal-title').innerText = 'Add Section to Unit';
            document.getElementById('section-crud-form').reset();
            document.getElementById('crud-sec-id').value = '';
            if (preselectedUnitId) unitSelect.value = preselectedUnitId;
            document.getElementById('crud-sec-active').checked = true;
            document.getElementById('btn-save-sec-submit').innerText = 'Create Section';
        }

        sectionModal.classList.add('active');
    }

    document.getElementById('btn-add-section')?.addEventListener('click', () => openSectionModal());
    document.getElementById('btn-cancel-sec-modal')?.addEventListener('click', () => sectionModal.classList.remove('active'));

    document.getElementById('section-crud-form')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const sid = document.getElementById('crud-sec-id').value;
        const mgrIds = Array.from(document.getElementById('crud-sec-managers').selectedOptions).map(o => parseInt(o.value));
        const payload = {
            unit_id: parseInt(document.getElementById('crud-sec-unit').value),
            name: document.getElementById('crud-sec-name').value.trim(),
            description: document.getElementById('crud-sec-desc').value.trim(),
            sort_order: parseInt(document.getElementById('crud-sec-sort').value) || 0,
            is_active: document.getElementById('crud-sec-active').checked,
            manager_ids: mgrIds
        };

        const isEdit = Boolean(sid);
        const url = isEdit ? `/api/admin/sections/${sid}` : '/api/admin/sections';
        const method = isEdit ? 'PUT' : 'POST';

        const res = await apiAdminRequest(url, { method: method, body: payload });
        if (res.ok) {
            sectionModal.classList.remove('active');
            loadHierarchy();
        } else {
            const err = await res.json();
            alert("Error: " + (err.detail || "Failed to save section."));
        }
    });


    // ==========================================
    // --- TAB 4: ISSUE CATEGORIES MANAGEMENT ---
    // ==========================================
    const categoryModal = document.getElementById('category-modal');

    async function loadCategories() {
        const container = document.getElementById('categories-table-container');
        if (!container) return;
        container.innerHTML = '<div style="padding: 16px; color: var(--text-muted); text-align: center;">Loading issue categories...</div>';

        const filter = document.getElementById('categories-status-filter')?.value || 'all';

        try {
            const res = await apiAdminRequest(`/api/admin/issue-categories?status_filter=${filter}`);
            categoriesData = await res.json();

            if (categoriesData.length === 0) {
                container.innerHTML = '<div style="padding: 24px; text-align: center; color: var(--text-muted); background: var(--bg-secondary); border-radius: var(--radius-md); border: 1px solid var(--border-color);">No issue categories match filter. Click "+ Add Issue Option" to create one.</div>';
                return;
            }

            function updateCategoriesBulkToolbar() {
                const bar = document.getElementById('categories-bulk-bar');
                const countSpan = document.getElementById('categories-selected-count');
                if (!bar || !countSpan) return;
                countSpan.textContent = selectedCategoryIds.size;
                if (selectedCategoryIds.size > 0) {
                    bar.classList.add('active');
                } else {
                    bar.classList.remove('active');
                }
                const headerCb = document.getElementById('categories-select-all-cb');
                if (headerCb) {
                    headerCb.checked = categoriesData.length > 0 && selectedCategoryIds.size === categoriesData.length;
                }
            }

            container.innerHTML = `
                <div class="table-responsive">
                    <table class="data-table table-responsive-cards">
                        <thead>
                            <tr>
                                <th style="width: 36px;">
                                    <input type="checkbox" id="categories-select-all-cb" style="cursor: pointer; width: 16px; height: 16px; accent-color: var(--primary);" title="Select all categories">
                                </th>
                                <th style="width: 60px;">Sort</th>
                                <th>Issue Option Name</th>
                                <th>Applicable Scope</th>
                                <th>Status</th>
                                <th>Historical Usage</th>
                                <th style="text-align: right;">Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${categoriesData.map(c => {
                                const scopeBadge = c.unit_name
                                    ? `<span class="badge" style="background: rgba(99, 102, 241, 0.15); color: var(--primary);">🏢 ${c.unit_name}</span>`
                                    : `<span class="badge" style="background: rgba(148, 163, 184, 0.15); color: var(--text-secondary);">🌐 Global (All Units)</span>`;

                                const activeBadge = c.is_active
                                    ? `<span class="badge badge-sent">Active</span>`
                                    : `<span class="badge" style="background: rgba(239, 68, 68, 0.15); color: var(--rose);">Inactive</span>`;

                                return `
                                    <tr>
                                        <td class="td-checkbox">
                                            <input type="checkbox" class="category-select-cb" data-id="${c.id}" ${selectedCategoryIds.has(c.id) ? 'checked' : ''} style="cursor: pointer; width: 16px; height: 16px; accent-color: var(--primary);" title="Select option">
                                        </td>
                                        <td data-label="Sort" style="color: var(--text-muted); font-family: monospace;">#${c.sort_order}</td>
                                        <td data-label="Option Name" style="font-weight: 600; color: var(--text-primary);">${c.name}</td>
                                        <td data-label="Scope">${scopeBadge}</td>
                                        <td data-label="Status">${activeBadge}</td>
                                        <td data-label="Usage" style="color: var(--text-muted);">${c.report_count || 0} reports</td>
                                        <td class="td-actions" data-label="Actions">
                                            <div style="display: inline-flex; gap: 6px; flex-wrap: wrap;">
                                                <button class="btn btn-secondary btn-xs btn-edit-cat" data-id="${c.id}">Edit</button>
                                                <button class="btn btn-secondary btn-xs btn-toggle-cat" data-id="${c.id}">
                                                    ${c.is_active ? 'Deactivate' : 'Activate'}
                                                </button>
                                                <button class="btn btn-secondary btn-xs btn-delete-cat" data-id="${c.id}" style="color: var(--rose);">Delete</button>
                                            </div>
                                        </td>
                                    </tr>
                                `;
                            }).join('')}
                        </tbody>
                    </table>
                </div>
            `;

            // Row Checkboxes
            container.querySelectorAll('.category-select-cb').forEach(cb => {
                cb.addEventListener('change', (e) => {
                    const cid = parseInt(e.target.getAttribute('data-id'));
                    if (e.target.checked) selectedCategoryIds.add(cid);
                    else selectedCategoryIds.delete(cid);
                    updateCategoriesBulkToolbar();
                });
            });

            // Header Checkbox
            document.getElementById('categories-select-all-cb')?.addEventListener('change', (e) => {
                const isChecked = e.target.checked;
                container.querySelectorAll('.category-select-cb').forEach(cb => {
                    cb.checked = isChecked;
                    const cid = parseInt(cb.getAttribute('data-id'));
                    if (isChecked) selectedCategoryIds.add(cid);
                    else selectedCategoryIds.delete(cid);
                });
                updateCategoriesBulkToolbar();
            });

            updateCategoriesBulkToolbar();

            // Category Action Listeners
            container.querySelectorAll('.btn-edit-cat').forEach(b => {
                b.addEventListener('click', () => {
                    const cid = parseInt(b.getAttribute('data-id'));
                    const c = categoriesData.find(x => x.id === cid);
                    if (!c) return;

                    openCategoryModal(c);
                });
            });

            container.querySelectorAll('.btn-toggle-cat').forEach(b => {
                b.addEventListener('click', async () => {
                    const cid = b.getAttribute('data-id');
                    b.disabled = true;
                    await apiAdminRequest(`/api/admin/issue-categories/${cid}/toggle-active`, { method: 'PATCH' });
                    loadCategories();
                });
            });

            container.querySelectorAll('.btn-delete-cat').forEach(b => {
                b.addEventListener('click', async () => {
                    const cid = b.getAttribute('data-id');
                    const c = categoriesData.find(x => x.id === parseInt(cid));
                    if (!confirm(`Are you sure you want to remove issue option '${c ? c.name : ''}'?`)) return;

                    b.disabled = true;
                    const res = await apiAdminRequest(`/api/admin/issue-categories/${cid}`, { method: 'DELETE' });
                    const resData = await res.json();
                    alert(resData.message || "Operation complete.");
                    selectedCategoryIds.delete(parseInt(cid));
                    loadCategories();
                });
            });

        } catch (e) {
            container.innerHTML = '<div style="color: var(--rose); padding: 16px;">Failed to load issue categories.</div>';
        }
        refreshIcons();
    }

    document.getElementById('categories-status-filter')?.addEventListener('change', () => loadCategories());

    document.getElementById('btn-categories-select-all')?.addEventListener('click', () => {
        document.querySelectorAll('.category-select-cb').forEach(cb => {
            cb.checked = true;
            selectedCategoryIds.add(parseInt(cb.getAttribute('data-id')));
        });
        const headerCb = document.getElementById('categories-select-all-cb');
        if (headerCb) headerCb.checked = true;
        const bar = document.getElementById('categories-bulk-bar');
        const countSpan = document.getElementById('categories-selected-count');
        if (countSpan) countSpan.textContent = selectedCategoryIds.size;
        if (bar && selectedCategoryIds.size > 0) bar.classList.add('active');
    });

    document.getElementById('btn-categories-clear-select')?.addEventListener('click', () => {
        selectedCategoryIds.clear();
        document.querySelectorAll('.category-select-cb').forEach(cb => { cb.checked = false; });
        const headerCb = document.getElementById('categories-select-all-cb');
        if (headerCb) headerCb.checked = false;
        const bar = document.getElementById('categories-bulk-bar');
        const countSpan = document.getElementById('categories-selected-count');
        if (countSpan) countSpan.textContent = 0;
        if (bar) bar.classList.remove('active');
    });

    document.getElementById('btn-categories-bulk-delete')?.addEventListener('click', async () => {
        if (selectedCategoryIds.size === 0) return;
        if (!confirm(`Are you sure you want to remove ${selectedCategoryIds.size} selected issue option(s)? Referenced options will be deactivated to preserve history.`)) return;
        const ids = Array.from(selectedCategoryIds);
        try {
            const res = await apiAdminRequest('/api/admin/issue-categories/bulk-delete', {
                method: 'POST',
                body: { ids: ids }
            });
            const resData = await res.json();
            alert(resData.message || "Categories processed successfully.");
            selectedCategoryIds.clear();
            loadCategories();
        } catch(err) {
            alert("Failed to delete selected categories.");
        }
    });

    async function openCategoryModal(categoryObj = null) {
        const unitScopeSelect = document.getElementById('crud-cat-unit');

        // Populate units in scope dropdown
        if (unitsData.length === 0) {
            const uRes = await apiAdminRequest('/api/admin/units-sections');
            const data = await uRes.json();
            unitsData = data.units || [];
        }

        unitScopeSelect.innerHTML = `
            <option value="">Global (Applicable to All Units)</option>
            ${unitsData.map(u => `<option value="${u.id}">${u.name}</option>`).join('')}
        `;

        if (categoryObj) {
            document.getElementById('category-modal-title').innerText = `Edit Issue Option: ${categoryObj.name}`;
            document.getElementById('crud-cat-id').value = categoryObj.id;
            document.getElementById('crud-cat-name').value = categoryObj.name;
            unitScopeSelect.value = categoryObj.unit_id || '';
            document.getElementById('crud-cat-sort').value = categoryObj.sort_order || 0;
            document.getElementById('crud-cat-active').checked = Boolean(categoryObj.is_active);
            document.getElementById('btn-save-cat-submit').innerText = 'Update Option';
        } else {
            document.getElementById('category-modal-title').innerText = 'Add Issue Option';
            document.getElementById('category-crud-form').reset();
            document.getElementById('crud-cat-id').value = '';
            document.getElementById('crud-cat-sort').value = (categoriesData.length + 1) * 5;
            document.getElementById('crud-cat-active').checked = true;
            document.getElementById('btn-save-cat-submit').innerText = 'Create Option';
        }

        categoryModal.classList.add('active');
    }

    document.getElementById('btn-add-category')?.addEventListener('click', () => openCategoryModal());
    document.getElementById('btn-cancel-cat-modal')?.addEventListener('click', () => categoryModal.classList.remove('active'));

    document.getElementById('category-crud-form')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const cid = document.getElementById('crud-cat-id').value;
        const unitVal = document.getElementById('crud-cat-unit').value;
        const payload = {
            name: document.getElementById('crud-cat-name').value.trim(),
            unit_id: unitVal ? parseInt(unitVal) : null,
            sort_order: parseInt(document.getElementById('crud-cat-sort').value) || 0,
            is_active: document.getElementById('crud-cat-active').checked
        };

        const isEdit = Boolean(cid);
        const url = isEdit ? `/api/admin/issue-categories/${cid}` : '/api/admin/issue-categories';
        const method = isEdit ? 'PUT' : 'POST';

        const res = await apiAdminRequest(url, { method: method, body: payload });
        if (res.ok) {
            categoryModal.classList.remove('active');
            loadCategories();
        } else {
            const err = await res.json();
            alert("Error: " + (err.detail || "Failed to save category."));
        }
    });


    // ==========================================
    // --- TAB 5: TELEGRAM SETTINGS & LIVE TEST -
    // ==========================================
    async function loadTelegramSettings() {
        try {
            const res = await apiAdminRequest('/api/admin/telegram');
            const data = await res.json();
            document.getElementById('tg-bot-token').value = data.bot_token || '';
            document.getElementById('tg-chat-id').value = data.admin_telegram_id || data.chat_id || '';
        } catch (e) {}
    }

    document.getElementById('telegram-settings-form')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const token = document.getElementById('tg-bot-token').value.trim();
        const chatId = document.getElementById('tg-chat-id').value.trim();

        const res = await apiAdminRequest('/api/admin/telegram', {
            method: 'POST',
            body: { bot_token: token, admin_telegram_id: chatId, chat_id: chatId }
        });

        if (res.ok) {
            alert("Telegram settings saved successfully.");
        } else {
            alert("Failed to save Telegram settings.");
        }
    });

    document.getElementById('btn-test-telegram')?.addEventListener('click', async () => {
        const resultDiv = document.getElementById('tg-test-result');
        resultDiv.innerHTML = '<span style="color: var(--text-muted);">Sending test alert to configured Telegram chat...</span>';

        try {
            const res = await apiAdminRequest('/api/admin/telegram/test', { method: 'POST' });
            const data = await res.json();
            if (res.ok && data.success) {
                resultDiv.innerHTML = `<span style="color: var(--emerald);">✅ ${data.message}</span>`;
            } else {
                resultDiv.innerHTML = `<span style="color: var(--rose);">❌ ${data.detail || "Test failed."}</span>`;
            }
        } catch (e) {
            resultDiv.innerHTML = `<span style="color: var(--rose);">❌ Connection error.</span>`;
        }
    });

    // Initial check
    checkAuth();
});
