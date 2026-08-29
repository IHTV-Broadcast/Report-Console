document.addEventListener('DOMContentLoaded', () => {
    // Current State
    let activeTab = 'dashboard';
    let statsData = null;
    let reportsList = [];
    let pendingList = [];
    let employeesData = null;
    let configOptions = null;
    let configUnits = ["Broadcast", "Social", "Conductor", "Archive"];
    let configRoles = ["Live", "Playlist", "Helpdesk", "Social", "Conductor", "R&D", "Leader"];
    let configConditions = ["Night Shift", "Remote Work", "Multi Task", "Condition Hardship", "Illness", "Discrete Working Hours", "General Requirements"];
    
    // Chart References (for destruction on reload)
    let timelineChartRef = null; // kept to avoid destroy() errors on re-render
    let moodChartRef = null;
    let categoriesChartRef = null;
    let serverChartRef = null;
    let missingReportsChartRef = null;

    // Helper to format date safely and prevent RangeError on invalid dates
    function safeFormatDate(dateStr, options) {
        if (!dateStr) return 'N/A';
        try {
            const d = new Date(dateStr);
            if (isNaN(d.getTime())) return 'N/A';
            return d.toLocaleString('en-US', options);
        } catch (e) {
            return 'N/A';
        }
    }

    // Elements
    const navItems = document.querySelectorAll('.nav-item');
    const tabContents = document.querySelectorAll('.tab-content');
    const viewTitle = document.getElementById('view-title');
    const viewSubtitle = document.getElementById('view-subtitle');
    const btnRefresh = document.getElementById('btn-refresh');
    
    // Initialize Lucide Icons
    lucide.createIcons();

    // ----------------- TAB SWITCHING -----------------
    function switchTab(tabName) {
        const role = userRole || detectUserRole(currentUser);
        if (role === 'Employee' && tabName !== 'submit-report') {
            tabName = 'submit-report';
        } else if (role === 'Leader' && ['dashboard', 'employees', 'config', 'pending-leader'].includes(tabName)) {
            tabName = 'pending-personal';
        }

        activeTab = tabName;
        
        // Update nav items
        navItems.forEach(item => {
            if (item.getAttribute('data-tab') === tabName) {
                item.classList.add('active');
            } else {
                item.classList.remove('active');
            }
        });

        // Update tab content displays
        tabContents.forEach(content => {
            if (content.id === `tab-${tabName}`) {
                content.classList.add('active');
            } else {
                content.classList.remove('active');
            }
        });

        // Update Title & Subtitle
        switch(tabName) {
            case 'dashboard':
                viewTitle.innerText = "Dashboard";
                viewSubtitle.innerText = "Overview of daily reports and bot telemetry";
                loadDashboardData();
                break;
            case 'submit-report':
                viewTitle.innerText = "Submit Daily Report";
                viewSubtitle.innerText = "Submit daily operational metrics to team supervisor";
                break;
            case 'reports':
                viewTitle.innerText = "Reports Database";
                viewSubtitle.innerText = "Browse and filter employee submissions";
                loadReportsData();
                break;
            case 'pending-leader':
                viewTitle.innerText = "Pending Leader Reviews";
                viewSubtitle.innerText = "Administrator review queue for team leader submissions";
                loadPendingLeaderQueue();
                break;
            case 'pending-personal':
                viewTitle.innerText = "Pending Personal Reviews";
                viewSubtitle.innerText = "Review and approve employee shift reports";
                loadPendingPersonalQueue();
                break;
            case 'employees':
                viewTitle.innerText = "Employees Directory";
                viewSubtitle.innerText = "Manage employees and their metadata";
                loadEmployeesData();
                break;
            case 'config':
                viewTitle.innerText = "Configs & Weights";
                viewSubtitle.innerText = "Adjust error penalties and threshold limits";
                loadConfigData();
                break;
        }
        
        lucide.createIcons();
    }

    // ----------------- AUTHENTICATION & SESSION MANAGEMENT -----------------
    let sessionToken = localStorage.getItem('sessionToken') || null;
    let currentUser = localStorage.getItem('activeUser') || null;
    let userRole = localStorage.getItem('userRole') || null;
    let userName = localStorage.getItem('userName') || null;

    const loginPage = document.getElementById('login-page');
    const appContainer = document.getElementById('app-container');
    const loginForm = document.getElementById('login-form');
    const usernameInput = document.getElementById('login-username');
    const loginErrorBox = document.getElementById('login-error');
    const loginErrorText = document.getElementById('login-error-text');
    const activeUserNameEl = document.getElementById('active-user-name');
    const activeUserBadgeEl = document.getElementById('active-user-badge');

    function showLoginError(msg) {
        if (loginErrorBox && loginErrorText) {
            loginErrorText.innerText = msg;
            loginErrorBox.style.display = 'flex';
        }
    }

    function hideLoginError() {
        if (loginErrorBox) {
            loginErrorBox.style.display = 'none';
        }
    }

    function updateActiveUserProfileUI(name, role) {
        if (activeUserNameEl) activeUserNameEl.innerText = name || 'User';
        if (activeUserBadgeEl) {
            activeUserBadgeEl.innerText = role || 'Role';
            activeUserBadgeEl.className = (role === 'Admin' || role === 'Leader') ? 'badge badge-leader' : 'badge badge-secondary';
        }
    }

    function showAppContainer() {
        if (loginPage) loginPage.style.display = 'none';
        if (appContainer) appContainer.style.display = 'flex';
        lucide.createIcons();
    }

    function performLogout() {
        sessionToken = null;
        currentUser = null;
        userRole = null;
        userName = null;

        localStorage.removeItem('sessionToken');
        localStorage.removeItem('activeUser');
        localStorage.removeItem('userRole');
        localStorage.removeItem('userName');

        if (appContainer) appContainer.style.display = 'none';
        if (loginPage) loginPage.style.display = 'flex';
        if (usernameInput) {
            usernameInput.value = '';
            usernameInput.focus();
        }
        hideLoginError();
    }

    const loginPinGroup = document.getElementById('login-pin-group');
    const loginPinInput = document.getElementById('login-pin');

    usernameInput?.addEventListener('input', () => {
        const val = usernameInput.value.trim().toLowerCase();
        if (val === 'ral') {
            if (loginPinGroup) loginPinGroup.style.display = 'block';
        } else {
            if (loginPinGroup) loginPinGroup.style.display = 'none';
            if (loginPinInput) loginPinInput.value = '';
        }
    });

    loginForm?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const rawUser = usernameInput.value.trim();
        if (!rawUser) {
            showLoginError("Please enter a username.");
            return;
        }

        hideLoginError();

        const payload = { username: rawUser };
        if (rawUser.toLowerCase() === 'ral' && loginPinInput) {
            payload.pin = loginPinInput.value.trim();
        }

        try {
            const res = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (!res.ok) {
                const errData = await res.json().catch(() => ({}));
                const errDetail = errData.detail;
                if (errDetail === 'PIN_REQUIRED') {
                    if (loginPinGroup) loginPinGroup.style.display = 'block';
                    if (loginPinInput) loginPinInput.focus();
                    showLoginError("Admin PIN is required.");
                } else if (errDetail === 'INCORRECT_PIN') {
                    if (loginPinInput) {
                        loginPinInput.value = '';
                        loginPinInput.focus();
                    }
                    showLoginError("Incorrect Admin PIN.");
                } else {
                    showLoginError(errDetail || "Username not found.");
                }
                return;
            }

            const data = await res.json();
            sessionToken = data.token;
            currentUser = data.username;
            userRole = data.role;
            userName = data.name;

            localStorage.setItem('sessionToken', sessionToken);
            localStorage.setItem('activeUser', currentUser);
            localStorage.setItem('userRole', userRole);
            localStorage.setItem('userName', userName);

            updateActiveUserProfileUI(userName, userRole);
            applyRolePermissions();
            showAppContainer();
            await loadEmployeesData();
        } catch (err) {
            showLoginError("Unable to connect to authentication server.");
        }
    });

    document.querySelectorAll('.btn-logout').forEach(btn => {
        btn.addEventListener('click', async () => {
            if (sessionToken) {
                fetch('/api/auth/logout', {
                    method: 'POST',
                    headers: { 'X-Session-Token': sessionToken }
                }).catch(() => {});
            }
            performLogout();
        });
    });

    function detectUserRole(userVal) {
        if (userRole) return userRole;
        if (!userVal || userVal.toUpperCase() === 'RAL') return 'Admin';
        if (employeesData && employeesData.employees) {
            const emp = employeesData.employees.find(e => (e.name || '').toLowerCase() === userVal.toLowerCase());
            if (emp && Array.isArray(emp.roles) && emp.roles.includes('Leader')) {
                return 'Leader';
            }
        }
        return 'Employee';
    }

    function applyRolePermissions() {
        const role = userRole || detectUserRole(currentUser);
        const submitTabBtn = document.querySelector('.nav-item[data-tab="submit-report"]');
        const dashboardTabBtn = document.querySelector('.nav-item[data-tab="dashboard"]');
        const reportsTabBtn = document.querySelector('.nav-item[data-tab="reports"]');
        const pendingLeaderTabBtn = document.querySelector('.nav-item[data-tab="pending-leader"]');
        const pendingPersonalTabBtn = document.querySelector('.nav-item[data-tab="pending-personal"]');
        const employeesTabBtn = document.querySelector('.nav-item[data-tab="employees"]');
        const configTabBtn = document.querySelector('.nav-item[data-tab="config"]');
        const btnLeaderReport = document.getElementById('btn-trigger-leader-report');

        if (role === 'Admin') {
            if (submitTabBtn) submitTabBtn.style.display = 'none';
            if (dashboardTabBtn) dashboardTabBtn.style.display = 'flex';
            if (reportsTabBtn) reportsTabBtn.style.display = 'flex';
            if (pendingLeaderTabBtn) pendingLeaderTabBtn.style.display = 'flex';
            if (pendingPersonalTabBtn) pendingPersonalTabBtn.style.display = 'flex';
            if (employeesTabBtn) employeesTabBtn.style.display = 'flex';
            if (configTabBtn) configTabBtn.style.display = 'flex';
            if (btnLeaderReport) btnLeaderReport.style.display = 'inline-flex';

            if (activeTab === 'submit-report' || !activeTab) {
                switchTab('dashboard');
            }
        } else if (role === 'Leader') {
            if (submitTabBtn) submitTabBtn.style.display = 'flex';
            if (dashboardTabBtn) dashboardTabBtn.style.display = 'none';
            if (reportsTabBtn) reportsTabBtn.style.display = 'flex';
            if (pendingLeaderTabBtn) pendingLeaderTabBtn.style.display = 'none'; // NEVER visible to Leaders!
            if (pendingPersonalTabBtn) pendingPersonalTabBtn.style.display = 'flex';
            if (employeesTabBtn) employeesTabBtn.style.display = 'none';
            if (configTabBtn) configTabBtn.style.display = 'none';
            if (btnLeaderReport) btnLeaderReport.style.display = 'inline-flex';

            if (['dashboard', 'employees', 'config', 'pending-leader'].includes(activeTab)) {
                switchTab('pending-personal');
            }
        } else {
            // Employee Tier
            if (submitTabBtn) submitTabBtn.style.display = 'flex';
            if (dashboardTabBtn) dashboardTabBtn.style.display = 'none';
            if (reportsTabBtn) reportsTabBtn.style.display = 'none';
            if (pendingLeaderTabBtn) pendingLeaderTabBtn.style.display = 'none'; // NEVER visible to Employees!
            if (pendingPersonalTabBtn) pendingPersonalTabBtn.style.display = 'none'; // NEVER visible to Employees!
            if (employeesTabBtn) employeesTabBtn.style.display = 'none';
            if (configTabBtn) configTabBtn.style.display = 'none';
            if (btnLeaderReport) btnLeaderReport.style.display = 'none';

            switchTab('submit-report');
        }
    }

    navItems.forEach(item => {
        item.addEventListener('click', () => {
            const tab = item.getAttribute('data-tab');
            switchTab(tab);
        });
    });

    btnRefresh.addEventListener('click', () => {
        const rotateIcon = btnRefresh.querySelector('i');
        rotateIcon.style.transform = 'rotate(360deg)';
        rotateIcon.style.transition = 'transform 0.6s ease';
        
        setTimeout(() => {
            rotateIcon.style.transform = 'none';
            rotateIcon.style.transition = 'none';
        }, 600);
        
        switchTab(activeTab);
    });

    // ----------------- CUSTOM APPLICATION MODALS (PROMPT, CONFIRM, ALERT) -----------------
    function showCustomPrompt(options = {}) {
        return new Promise((resolve) => {
            const modal = document.getElementById('custom-prompt-modal');
            const titleEl = document.getElementById('custom-prompt-title');
            const descEl = document.getElementById('custom-prompt-description');
            const inputEl = document.getElementById('custom-prompt-input');
            const errorEl = document.getElementById('custom-prompt-error');
            const formEl = document.getElementById('custom-prompt-form');
            const cancelBtn = document.getElementById('custom-prompt-cancel');
            const submitBtn = document.getElementById('custom-prompt-submit');
            const closeBtn = document.getElementById('custom-prompt-close');

            const prevFocused = document.activeElement;

            titleEl.textContent = options.title || "Input Required";
            if (options.description) {
                descEl.textContent = options.description;
                descEl.style.display = "block";
            } else {
                descEl.style.display = "none";
            }

            inputEl.value = options.defaultValue || "";
            inputEl.placeholder = options.placeholder || "Enter name...";
            submitBtn.textContent = options.submitText || "Save";

            errorEl.style.display = "none";
            errorEl.textContent = "";

            function validate() {
                const val = inputEl.value.trim();
                if (val === "") {
                    submitBtn.disabled = true;
                    errorEl.style.display = "none";
                    return false;
                }

                if (options.existingItems && Array.isArray(options.existingItems)) {
                    const isDup = options.existingItems.some(item =>
                        item.toLowerCase() === val.toLowerCase() &&
                        item.toLowerCase() !== (options.currentItem || "").toLowerCase()
                    );
                    if (isDup) {
                        submitBtn.disabled = true;
                        errorEl.textContent = `A ${options.itemType || 'item'} with this name already exists.`;
                        errorEl.style.display = "block";
                        return false;
                    }
                }

                submitBtn.disabled = false;
                errorEl.style.display = "none";
                return true;
            }

            validate();

            modal.classList.add('active');
            setTimeout(() => {
                inputEl.focus();
                inputEl.select();
            }, 50);

            function cleanup() {
                modal.classList.remove('active');
                formEl.removeEventListener('submit', onSubmit);
                cancelBtn.removeEventListener('click', onCancel);
                closeBtn.removeEventListener('click', onCancel);
                modal.removeEventListener('click', onBackdropClick);
                document.removeEventListener('keydown', onKeyDown);
                inputEl.removeEventListener('input', onInput);
                if (prevFocused && typeof prevFocused.focus === 'function') {
                    prevFocused.focus();
                }
            }

            function onSubmit(e) {
                e.preventDefault();
                if (!validate()) return;
                const result = inputEl.value.trim();
                cleanup();
                resolve(result);
            }

            function onCancel() {
                cleanup();
                resolve(null);
            }

            function onBackdropClick(e) {
                if (e.target === modal) onCancel();
            }

            function onKeyDown(e) {
                if (e.key === 'Escape') {
                    onCancel();
                }
            }

            function onInput() {
                validate();
            }

            formEl.addEventListener('submit', onSubmit);
            cancelBtn.addEventListener('click', onCancel);
            closeBtn.addEventListener('click', onCancel);
            modal.addEventListener('click', onBackdropClick);
            document.addEventListener('keydown', onKeyDown);
            inputEl.addEventListener('input', onInput);
        });
    }

    function showCustomConfirm(options = {}) {
        return new Promise((resolve) => {
            const modal = document.getElementById('custom-confirm-modal');
            const titleEl = document.getElementById('custom-confirm-title');
            const msgEl = document.getElementById('custom-confirm-message');
            const warnEl = document.getElementById('custom-confirm-warning');
            const cancelBtn = document.getElementById('custom-confirm-cancel');
            const submitBtn = document.getElementById('custom-confirm-submit');
            const closeBtn = document.getElementById('custom-confirm-close');

            const prevFocused = document.activeElement;

            titleEl.textContent = options.title || "Confirm Action";
            msgEl.innerHTML = options.message || "Are you sure?";

            if (options.warning) {
                warnEl.innerHTML = options.warning;
                warnEl.style.display = "block";
            } else {
                warnEl.style.display = "none";
            }

            cancelBtn.style.display = options.singleButton ? "none" : "inline-block";
            cancelBtn.textContent = options.cancelText || "Cancel";
            submitBtn.textContent = options.confirmText || (options.singleButton ? "OK" : "Confirm");

            if (options.isDanger) {
                submitBtn.className = "btn btn-danger";
            } else if (options.isSuccess) {
                submitBtn.className = "btn btn-success";
            } else {
                submitBtn.className = "btn btn-primary";
            }

            modal.classList.add('active');
            setTimeout(() => submitBtn.focus(), 50);

            function cleanup() {
                modal.classList.remove('active');
                submitBtn.removeEventListener('click', onConfirm);
                cancelBtn.removeEventListener('click', onCancel);
                closeBtn.removeEventListener('click', onCancel);
                modal.removeEventListener('click', onBackdropClick);
                document.removeEventListener('keydown', onKeyDown);
                if (prevFocused && typeof prevFocused.focus === 'function') {
                    prevFocused.focus();
                }
            }

            function onConfirm() {
                console.log("[showCustomConfirm] onConfirm triggered");
                cleanup();
                resolve(true);
            }

            function onCancel() {
                console.log("[showCustomConfirm] onCancel triggered");
                cleanup();
                resolve(false);
            }

            function onBackdropClick(e) {
                if (e.target === modal) onCancel();
            }

            function onKeyDown(e) {
                if (e.key === 'Escape') {
                    onCancel();
                }
            }

            submitBtn.addEventListener('click', onConfirm);
            cancelBtn.addEventListener('click', onCancel);
            closeBtn.addEventListener('click', onCancel);
            modal.addEventListener('click', onBackdropClick);
            document.addEventListener('keydown', onKeyDown);
        });
    }

    function showCustomAlert(options = {}) {
        return showCustomConfirm({
            title: options.title || "Notification",
            message: options.message || "",
            warning: options.warning || null,
            confirmText: options.buttonText || "OK",
            singleButton: true,
            isDanger: options.type === "danger",
            isSuccess: options.type === "success"
        });
    }

    // ----------------- API UTILITIES -----------------
    async function apiRequest(endpoint, options = {}) {
        try {
            options.headers = options.headers || {};
            if (options.body && !(options.body instanceof FormData)) {
                if (options.headers instanceof Headers) {
                    if (!options.headers.has('Content-Type')) {
                        options.headers.set('Content-Type', 'application/json');
                    }
                } else {
                    if (!options.headers['Content-Type']) {
                        options.headers['Content-Type'] = 'application/json';
                    }
                }
            }
            if (sessionToken) {
                if (options.headers instanceof Headers) {
                    options.headers.set('X-Session-Token', sessionToken);
                } else {
                    options.headers['X-Session-Token'] = sessionToken;
                }
            }
            if (currentUser) {
                if (options.headers instanceof Headers) {
                    options.headers.set('X-User-Name', currentUser);
                } else {
                    options.headers['X-User-Name'] = currentUser;
                }
            }

            const response = await fetch(endpoint, options);
            if (response.status === 401) {
                performLogout();
                throw new Error("Session expired. Please log in again.");
            }

            if (!response.ok) {
                let errText = await response.text();
                try {
                    const parsed = JSON.parse(errText);
                    if (parsed.detail) {
                        if (Array.isArray(parsed.detail)) {
                            errText = parsed.detail.map(d => d.msg || JSON.stringify(d)).join('\n');
                        } else if (typeof parsed.detail === 'string') {
                            errText = parsed.detail;
                        }
                    }
                } catch (e) {}
                throw new Error(errText || `HTTP error ${response.status}`);
            }
            return await response.json();
        } catch (error) {
            console.error(`API Error on ${endpoint}:`, error);
            await showCustomAlert({ title: "API Error", message: error.message, type: "danger" });
            return null;
        }
    }

    // ----------------- 1. DASHBOARD CONTROLLER -----------------
    async function loadDashboardData() {
        const stats = await apiRequest('/api/stats');
        if (!stats) return;
        
        statsData = stats;
        
        // Update stats cards
        document.getElementById('stat-total-reports').innerText = stats.summary.total_reports;
        document.getElementById('stat-pending-reviews').innerText = stats.summary.pending_approvals;
        document.getElementById('stat-problem-reports').innerText = stats.summary.problem_reports;
        
        const problemRate = stats.summary.total_reports > 0 
            ? Math.round((stats.summary.problem_reports / stats.summary.total_reports) * 100)
            : 0;
        document.getElementById('stat-problem-rate').innerText = `${problemRate}%`;
        
        document.getElementById('stat-avg-rating').innerText = `${stats.summary.avg_manager_rating}/10`;
        document.getElementById('stat-avg-employee').innerText = `${stats.summary.avg_employee_rating}/10`;
        
        // Update Pending reviews badges
        const role = userRole || detectUserRole(currentUser);
        if (role === 'Admin') {
            loadPendingLeaderQueue();
            loadPendingPersonalQueue();
        } else if (role === 'Leader') {
            loadPendingPersonalQueue();
        }
        
        // Render unit champions & leaderboard
        renderUnitChampions(stats.unit_champions);
        renderLeaderboard(stats.employee_leaderboard);
        
        // Render charts
        renderDashboardCharts(stats);
    }

    function renderUnitChampions(champions) {
        const grid = document.getElementById('unit-champions-grid');
        if (!grid) return;
        grid.innerHTML = '';

        if (!champions || champions.length === 0) {
            grid.innerHTML = `<p class="text-secondary small">No department champions available</p>`;
            return;
        }

        champions.forEach(champ => {
            const card = document.createElement('div');
            card.className = 'champion-card';
            card.style.cssText = `
                background: rgba(15, 23, 42, 0.7);
                border: 1px solid rgba(245, 158, 11, 0.3);
                border-radius: 10px;
                padding: 16px;
                display: flex;
                flex-direction: column;
                gap: 6px;
                box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25);
                transition: transform 0.2s ease, border-color 0.2s ease;
            `;
            card.innerHTML = `
                <div style="display: flex; align-items: center; justify-content: space-between;">
                    <span class="badge badge-amber" style="font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;">🏆 ${champ.title}</span>
                    <span style="font-size: 1.1rem;">👑</span>
                </div>
                <div style="font-size: 1.15rem; font-weight: 700; color: #ffffff; margin-top: 4px;">${champ.name}</div>
                <div style="display: flex; align-items: center; flex-wrap: wrap; gap: 10px; font-size: 0.82rem; color: #e5e7eb; margin-top: 4px;">
                    <span>⭐ <strong style="color:#ffffff;">${champ.avg_rating}</strong>/10</span>
                    <span>📑 <strong style="color:#ffffff;">${champ.reports}</strong> rpts</span>
                    <span style="color: ${champ.missing_reports === 0 ? '#10b981' : '#f59e0b'};">🎯 <strong>${champ.missing_reports}d</strong> miss</span>
                </div>
            `;
            grid.appendChild(card);
        });
    }

    function renderLeaderboard(leaderboard) {
        const tbody = document.querySelector('#leaderboard-table tbody');
        tbody.innerHTML = '';
        
        if (!leaderboard || leaderboard.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" class="text-center text-secondary">No active employees found</td></tr>`;
            return;
        }
        
        leaderboard.forEach((emp, idx) => {
            const tr = document.createElement('tr');
            const rankBadge = idx === 0 ? '🥇' : idx === 1 ? '🥈' : idx === 2 ? '🥉' : `<span style="color:#9ca3af;">#${idx + 1}</span>`;
            const ratingBadge = emp.avg_rating > 0 
                ? `<span class="badge badge-primary font-semibold" style="font-size:0.85rem;">⭐ ${emp.avg_rating} / 10</span>` 
                : `<span class="text-secondary small">N/A</span>`;
            
            const missingBadge = emp.missing_reports === 0 
                ? `<span class="badge badge-emerald font-semibold">0 days (Perfect)</span>` 
                : `<span class="badge badge-amber font-semibold">${emp.missing_reports} days</span>`;

            tr.innerHTML = `
                <td class="font-bold" style="font-size: 1.1rem; text-align: center;">${rankBadge}</td>
                <td class="font-semibold" style="color: #ffffff; font-size: 0.95rem;">${emp.name}</td>
                <td class="font-semibold" style="color: #38bdf8; font-size: 0.9rem;">${emp.unit || '-'}</td>
                <td>${ratingBadge}</td>
                <td>${missingBadge}</td>
                <td style="color: #ffffff; font-weight: 600;">${emp.reports}</td>
                <td><span class="badge ${emp.problems > 0 ? 'badge-rose' : 'badge-emerald'}">${emp.problems}</span></td>
            `;
            tbody.appendChild(tr);
        });
    }

    async function renderDashboardCharts(stats) {
        // Destroy existing chart references to prevent memory leaks/glitches
        if (moodChartRef) moodChartRef.destroy();
        if (missingReportsChartRef) missingReportsChartRef.destroy();
        if (categoriesChartRef) categoriesChartRef.destroy();


        // Colors & Config variables
        const isDark = document.body.classList.contains('dark-theme');
        const gridColor = 'rgba(255, 255, 255, 0.1)';
        const textColor = '#ffffff';

        // 1. MOOD CHART (Doughnut)
        const ctxMood = document.getElementById('moodChart').getContext('2d');
        const moods = stats.mood_distribution;
        const moodLabels = Object.keys(moods);
        const moodData = Object.values(moods);
        
        moodChartRef = new Chart(ctxMood, {
            type: 'doughnut',
            data: {
                labels: moodLabels,
                datasets: [{
                    data: moodData,
                    backgroundColor: ['#10b981', '#f59e0b', '#f43f5e', '#6366f1', '#a855f7'],
                    borderWidth: 0
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            color: '#ffffff',
                            font: { size: 12, weight: '600' },
                            padding: 12
                        }
                    }
                }
            }
        });

        // 3. CATEGORIES CHART (Doughnut)
        const ctxCat = document.getElementById('categoriesChart').getContext('2d');
        const categories = stats.issue_categories;
        const catLabels = Object.keys(categories);
        const catData = Object.values(categories);

        // Fixed color palette per category name for consistent, distinct colors
        const categoryColorMap = {
            'r&d':       '#a855f7',   // purple
            'live':      '#f43f5e',   // rose
            'play list': '#f59e0b',   // amber
            'helpdesk':  '#06b6d4',   // cyan
            'social':    '#10b981',   // emerald
            'conductor': '#3b82f6',   // blue
            'archive':   '#f97316',   // orange
        };
        const fallbackColors = ['#f43f5e','#f59e0b','#3b82f6','#10b981','#a855f7','#06b6d4','#f97316'];
        const catColors = catLabels.map((lbl, i) => categoryColorMap[lbl.toLowerCase().trim()] || fallbackColors[i % fallbackColors.length]);

        categoriesChartRef = new Chart(ctxCat, {
            type: 'doughnut',
            data: {
                labels: catLabels.length > 0 ? catLabels : ['None'],
                datasets: [{
                    data: catData.length > 0 ? catData : [1],
                    backgroundColor: catData.length > 0 ? catColors : ['rgba(255,255,255,0.05)'],
                    borderColor: 'rgba(0,0,0,0.15)',
                    borderWidth: 2,
                    hoverOffset: 8
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: '55%',
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            color: '#ffffff',
                            padding: 14,
                            boxWidth: 12,
                            font: { size: 12, weight: '600' }
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: ctx => ` ${ctx.label}: ${ctx.parsed} issue${ctx.parsed !== 1 ? 's' : ''}`
                        }
                    }
                }
            }
        });

        // 4. MISSING REPORTS CHART (Doughnut) — loaded separately
        await renderMissingReportsChart(textColor);
    }

    async function renderMissingReportsChart(textColor) {
        const ctxMissing = document.getElementById('missingReportsChart');
        if (!ctxMissing) return;

        try {
            const data = await apiRequest('/api/stats/missing-reports');
            if (!data || !data.missing_by_unit) return;

            const missingByUnit = data.missing_by_unit;
            const totalByUnit   = data.total_by_unit || {};

            // Only show units with at least 1 employee
            const labels  = Object.keys(missingByUnit).filter(u => (totalByUnit[u] || 0) > 0);
            const missing = labels.map(u => missingByUnit[u]);
            const hasMissing = missing.some(v => v > 0);

            // Distinct warm palette per unit slot
            const palette = [
                '#f43f5e', // rose
                '#f97316', // orange
                '#f59e0b', // amber
                '#a855f7', // purple
                '#06b6d4', // cyan
                '#10b981', // emerald
                '#3b82f6', // blue
                '#ec4899', // pink
            ];
            const bgColors   = labels.map((_, i) => palette[i % palette.length]);
            const borderColors = bgColors.map(c => c + 'cc');

            if (missingReportsChartRef) missingReportsChartRef.destroy();

            missingReportsChartRef = new Chart(ctxMissing.getContext('2d'), {
                type: 'doughnut',
                data: {
                    labels: hasMissing ? labels : ['All Submitted ✓'],
                    datasets: [{
                        data: hasMissing ? missing : [1],
                        backgroundColor: hasMissing ? bgColors : ['#10b981'],
                        borderColor: hasMissing ? borderColors : ['#10b981'],
                        borderWidth: 2,
                        hoverOffset: 8
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: '55%',
                    plugins: {
                        legend: {
                            position: 'bottom',
                            labels: {
                                color: '#ffffff',
                                padding: 10,
                                boxWidth: 10,
                                font: { size: 11, weight: '600' },
                                generateLabels: (chart) => {
                                    if (!hasMissing) return [{
                                        text: 'All Submitted ✓',
                                        fillStyle: '#10b981',
                                        fontColor: '#ffffff',
                                        hidden: false,
                                        index: 0
                                    }];
                                    return labels.map((lbl, i) => {
                                        const cleanName = lbl
                                            .replace(/ and /gi, ' & ')
                                            .replace(/Creation/gi, '')
                                            .replace(/Media/gi, '')
                                            .replace(/Technical Support/gi, 'Tech Support')
                                            .trim();
                                        return {
                                            text: `${cleanName}: ${missing[i]}/${totalByUnit[lbl] || '?'} missing`,
                                            fillStyle: bgColors[i],
                                            fontColor: '#ffffff',
                                            hidden: false,
                                            index: i
                                        };
                                    });
                                }
                            }
                        },
                        tooltip: {
                            callbacks: {
                                label: ctx => {
                                    if (!hasMissing) return ' All reports submitted today!';
                                    const unit = labels[ctx.dataIndex];
                                    const total = totalByUnit[unit] || '?';
                                    return ` ${ctx.parsed} of ${total} not submitted`;
                                }
                            }
                        }
                    }
                }
            });
        } catch (e) {
            console.warn('Missing reports chart error:', e);
        }
    }

    // ----------------- 2. REPORTS DATABASE CONTROLLER -----------------
    const searchFilter = document.getElementById('filter-search');
    const reportTypeFilter = document.getElementById('filter-report-type');
    const statusFilter = document.getElementById('filter-status');
    const roleFilter = document.getElementById('filter-role');
    const categoryFilter = document.getElementById('filter-category');
    const btnClearFilters = document.getElementById('btn-clear-filters');
    
    // Set up filter events
    [searchFilter, reportTypeFilter, statusFilter, roleFilter, categoryFilter].forEach(el => {
        if (!el) return;
        el.addEventListener('input', applyFilters);
        el.addEventListener('change', applyFilters);
    });

    btnClearFilters?.addEventListener('click', () => {
        if (searchFilter) searchFilter.value = '';
        if (reportTypeFilter) reportTypeFilter.value = '';
        if (statusFilter) statusFilter.value = '';
        if (roleFilter) roleFilter.value = '';
        if (categoryFilter) categoryFilter.value = '';
        applyFilters();
    });

    async function loadReportsFilters() {
        if (!configOptions) {
            configOptions = await apiRequest('/api/config');
        }
        
        // Populate Role dropdown dynamically
        if (roleFilter && (configRoles || (employeesData && employeesData.roles))) {
            const rolesList = (employeesData && employeesData.roles) ? employeesData.roles : configRoles;
            const currentVal = roleFilter.value;
            roleFilter.innerHTML = '<option value="">All Roles</option>';
            rolesList.forEach(r => {
                const opt = document.createElement('option');
                opt.value = r;
                opt.innerText = r;
                if (r === currentVal) opt.selected = true;
                roleFilter.appendChild(opt);
            });
        }

        if (configOptions) {
            // Populate category dropdown
            if (categoryFilter) {
                const currentCat = categoryFilter.value;
                categoryFilter.innerHTML = '<option value="">All Categories</option>';
                configOptions.problem_categories.forEach(cat => {
                    const opt = document.createElement('option');
                    opt.value = cat;
                    opt.innerText = cat;
                    if (cat === currentCat) opt.selected = true;
                    categoryFilter.appendChild(opt);
                });
            }
        }
    }

    async function loadReportsData() {
        await loadReportsFilters();
        
        const reports = await apiRequest('/api/reports');
        if (!reports) return;
        
        reportsList = reports;
        renderReportsTable(reports);
    }

    function applyFilters() {
        const query = searchFilter ? searchFilter.value.toLowerCase() : '';
        const reportType = reportTypeFilter ? reportTypeFilter.value : '';
        const status = statusFilter ? statusFilter.value : '';
        const role = roleFilter ? roleFilter.value : '';
        const category = categoryFilter ? categoryFilter.value : '';
        
        const filtered = reportsList.filter(r => {
            const isConsolidated = r.is_consolidated || r.isConsolidated || false;
            const reportData = r.data || {};
            
            // Search employee name / leader name
            const empName = (reportData.employee || r.leader_name || r.employee || '').toLowerCase();
            if (query && !empName.includes(query)) return false;

            // Filter report type (personal vs leader)
            if (reportType) {
                let isLeaderReport = isConsolidated;
                if (!isLeaderReport) {
                    if (employeesData && employeesData.employees) {
                        const emp = employeesData.employees.find(e => (e.name || '').toLowerCase() === empName);
                        if (emp && Array.isArray(emp.roles) && emp.roles.includes('Leader')) {
                            isLeaderReport = true;
                        }
                    }
                }
                if (reportType === 'leader' && !isLeaderReport) return false;
                if (reportType === 'personal' && isLeaderReport) return false;
            }
            
            // Filter status
            if (status && r.status !== status) return false;

            // Filter role
            if (role) {
                let empRoles = reportData.roles || [];
                if ((!empRoles || empRoles.length === 0) && employeesData && employeesData.employees) {
                    const emp = employeesData.employees.find(e => (e.name || '').toLowerCase() === empName);
                    if (emp) empRoles = emp.roles || [];
                }
                if (!Array.isArray(empRoles) || !empRoles.includes(role)) return false;
            }
            
            // Filter problem category
            if (category) {
                const problems = r.problems || reportData.problems || [];
                const hasCat = problems.some(p => p.category === category || p.type === category);
                if (!hasCat) return false;
            }
            
            return true;
        });
        
        renderReportsTable(filtered);
    }

    function renderReportsTable(reports) {
        const tbody = document.getElementById('reports-table-body');
        tbody.innerHTML = '';
        
        if (reports.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" class="text-center text-secondary py-4">No reports found matching filters.</td></tr>`;
            return;
        }
        
        reports.forEach(r => {
            const reportData = r.data || {};
            const date = new Date(r.created_at || r.timestamp);
            const dateStr = date.toLocaleString('en-US', { dateStyle: 'short', timeStyle: 'short' });
            
            // Format unit
            const empData = reportData.employee_data || {};
            let unitText = empData.unit || reportData.unit || 'Unknown';
            if (Array.isArray(unitText)) unitText = unitText.join(', ');
            
            // Format problems badge
            const problems = reportData.problems || [];
            let problemBadge = '<span class="badge badge-emerald">Normal</span>';
            if (problems.length > 0) {
                problemBadge = `<span class="badge badge-rose">${problems.length} Incident(s)</span>`;
            }
            
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${dateStr}</td>
                <td class="font-semibold">${reportData.employee || 'Unknown'}</td>
                <td>${unitText}</td>
                <td>${problemBadge}</td>
                <td>${reportData.rating || '-'}</td>
                <td class="font-semibold">${r.manager_rating || '-'}</td>
                <td>
                    <div style="display: flex; gap: 8px;">
                        <button class="btn btn-secondary btn-icon-only btn-view" data-id="${r.id}" title="${userRole === 'Admin' ? 'View / Edit Details' : 'View Details'}">
                            <i data-lucide="${userRole === 'Admin' ? 'edit-3' : 'eye'}"></i>
                        </button>
                        ${r.status === 'pending' && userRole !== 'Admin' ? `
                            <button class="btn btn-success btn-icon-only btn-review" data-id="${r.id}" title="Review & Approve">
                                <i data-lucide="check-square"></i>
                            </button>
                        ` : ''}
                        ${userRole === 'Admin' ? `
                            <button class="btn btn-danger btn-icon-only btn-delete" data-id="${r.id}" title="Delete Report">
                                <i data-lucide="trash-2"></i>
                            </button>
                        ` : ''}
                    </div>
                </td>
            `;
            
            tbody.appendChild(tr);
        });
        
        lucide.createIcons();
        attachActionListeners();
    }

    // -----------------    // 3b. PENDING LEADER REVIEWS CONTROLLER (Admin Only)
    async function loadPendingLeaderQueue() {
        const pending = await apiRequest('/api/reports/pending-leader');
        if (!pending) return;
        
        const badge = document.getElementById('pending-leader-badge');
        if (badge) {
            if (pending.length > 0) {
                badge.innerText = pending.length;
                badge.classList.remove('hidden');
            } else {
                badge.classList.add('hidden');
            }
        }
        
        renderPendingQueue('pending-leader-queue-list', pending);
    }

    // 3c. PENDING PERSONAL REVIEWS CONTROLLER (Admin & Assigned Leaders)
    async function loadPendingPersonalQueue() {
        const pending = await apiRequest('/api/reports/pending-personal');
        if (!pending) return;
        
        const badge = document.getElementById('pending-personal-badge');
        if (badge) {
            if (pending.length > 0) {
                badge.innerText = pending.length;
                badge.classList.remove('hidden');
            } else {
                badge.classList.add('hidden');
            }
        }
        
        renderPendingQueue('pending-personal-queue-list', pending);
    }

    // Generic fallback for queue loading
    async function loadPendingQueue() {
        const role = userRole || detectUserRole(currentUser);
        if (role === 'Admin') {
            await loadPendingLeaderQueue();
            await loadPendingPersonalQueue();
        } else if (role === 'Leader') {
            await loadPendingPersonalQueue();
        }
    }

    function renderPendingQueue(containerId, queue) {
        const container = document.getElementById(containerId);
        if (!container) return;
        container.innerHTML = '';
        
        if (queue.length === 0) {
            container.innerHTML = `
                <div class="card text-center text-secondary py-5">
                    <i data-lucide="check-circle" style="width: 48px; height: 48px; stroke-width: 1.5; color: var(--emerald); margin: 0 auto 16px;"></i>
                    <h3>All caught up!</h3>
                    <p class="mt-1">There are no pending reports awaiting your review.</p>
                </div>
            `;
            lucide.createIcons();
            return;
        }
        
        queue.forEach(r => {
            const isConsolidated = r.is_consolidated || r.isConsolidated;
            const reportData = r.data || r;
            const date = new Date(r.created_at || r.submitted_at || r.timestamp);
            const dateStr = date.toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' });
            
            const employeeName = isConsolidated ? `Leader Report: ${r.leader_name || 'Leader'}` : (reportData.employee || 'Unknown');
            const metaInfoText = isConsolidated ? `Period: ${r.period || 'Daily'}` : `Self Rating: ${reportData.rating || 'Not rated'}`;

            const problems = r.problems || reportData.problems || [];
            let problemHtml = '';
            if (problems.length > 0) {
                problemHtml = `<div class="pending-issues text-rose font-semibold">⚠️ Issues: ${problems.map(p => (p.type || p.category || 'General') + (p.subtype ? ' > ' + p.subtype : '')).join(', ')}</div>`;
            } else {
                problemHtml = `<div class="pending-issues text-emerald font-semibold">✅ Shift completed with no reported issues</div>`;
            }
            
            const div = document.createElement('div');
            div.className = 'pending-card';
            div.innerHTML = `
                <div class="pending-info">
                    <h3 style="display: flex; align-items: center; gap: 8px;">
                        <span>${employeeName}</span>
                        ${isConsolidated ? '<span class="badge badge-leader" style="font-size:0.75rem;">Consolidated</span>' : ''}
                    </h3>
                    <div class="pending-meta">
                        <span><i data-lucide="calendar" style="width: 14px; height: 14px; display: inline; vertical-align: sub; margin-right: 4px;"></i>${dateStr}</span>
                        <span><i data-lucide="info" style="width: 14px; height: 14px; display: inline; vertical-align: sub; margin-right: 4px;"></i>${metaInfoText}</span>
                    </div>
                    ${problemHtml}
                </div>
                <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                    <button class="btn btn-secondary btn-view-action" data-id="${r.id}">
                        <i data-lucide="eye"></i>
                        <span>View Details</span>
                    </button>
                    <button class="btn btn-primary btn-review-action" data-id="${r.id}">
                        <i data-lucide="check-circle-2"></i>
                        <span>Review & Rate</span>
                    </button>
                    ${userRole === 'Admin' ? `
                    <button class="btn btn-danger btn-delete-action" data-id="${r.id}">
                        <i data-lucide="trash-2"></i>
                        <span>Delete</span>
                    </button>
                    ` : ''}
                </div>
            `;
            container.appendChild(div);
        });
        
        lucide.createIcons();
        
        // Add listeners to "View Details", "Review & Rate", and "Delete" buttons
        container.querySelectorAll('.btn-view-action').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const reportId = btn.getAttribute('data-id');
                openReportModal(reportId);
            });
        });

        container.querySelectorAll('.btn-review-action').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const reportId = btn.getAttribute('data-id');
                openApprovalModal(reportId);
            });
        });

        container.querySelectorAll('.btn-delete-action').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const reportId = btn.getAttribute('data-id');
                const confirmDelete = await showCustomConfirm({
                    title: "Delete Report",
                    message: "Are you sure you want to permanently delete this report?",
                    confirmText: "Yes, Delete",
                    cancelText: "Cancel",
                    isDanger: true
                });
                if (confirmDelete) {
                    try {
                        const res = await apiRequest(`/api/reports/${reportId}`, {
                            method: 'DELETE'
                        });
                        if (res) {
                            await showCustomAlert({
                                title: "Success",
                                message: "Report deleted successfully.",
                                type: "success"
                            });
                            await loadPendingQueue();
                        }
                    } catch (err) {
                        await showCustomAlert({
                            title: "Error",
                            message: "Failed to delete the report: " + err.message,
                            type: "danger"
                        });
                    }
                }
            });
        });
    }

    // ----------------- 4. EMPLOYEES CONTROLLER -----------------
    async function loadEmployeesData() {
        const data = await apiRequest('/api/employees');
        if (!data) return;
        
        employeesData = data;
        configUnits = data.units || ["Broadcast", "Social", "Conductor", "Archive"];
        configRoles = data.roles || ["Live", "Playlist", "Helpdesk", "Social", "Conductor", "R&D", "Leader"];
        configConditions = data.special_conditions || ["Night Shift", "Remote Work", "Multi Task", "Condition Hardship", "Illness", "Discrete Working Hours", "General Requirements"];
        renderEmployeesTable(data.employees || []);
        updateActiveUserSelectorUI();
    }

    function renderEmployeesTable(employees) {
        const tbody = document.getElementById('employees-table-body');
        tbody.innerHTML = '';
        
        if (employees.length === 0) {
            tbody.innerHTML = `<tr><td colspan="8" class="text-center text-secondary py-4">No employees registered yet.</td></tr>`;
            return;
        }
        
        employees.forEach(emp => {
            const conditions = emp.special_conditions || [];
            const tags = conditions.map(c => `<span class="tag">${c}</span>`).join(' ');
            
            let supervisorLabel = '-';
            const supIds = emp.reportsTo || emp.reports_to || [];
            if (Array.isArray(supIds) && supIds.length > 0) {
                const names = [];
                supIds.forEach(id => {
                    const sup = employees.find(e => parseInt(e.id) === parseInt(id));
                    if (sup) names.push(sup.name);
                });
                if (names.length > 0) {
                    supervisorLabel = names.join(', ');
                }
            } else if (supIds && !Array.isArray(supIds)) {
                const sup = employees.find(e => parseInt(e.id) === parseInt(supIds));
                if (sup) supervisorLabel = sup.name;
            }

            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td class="font-semibold">${emp.name}</td>
                <td>${Array.isArray(emp.unit) ? emp.unit.join(', ') : emp.unit}</td>
                <td>${Array.isArray(emp.roles) ? emp.roles.map(r => r === 'Leader' ? `Leader (${emp.leader_type || 'General'}${emp.leader_shift ? ' - ' + emp.leader_shift : ''})` : r).join(', ') : (emp.roles || '-')}</td>
                <td>${supervisorLabel}</td>
                <td>${emp.work_location}</td>
                <td class="small">${emp.work_hours}</td>
                <td><div class="list-tags">${tags || '-'}</div></td>
                <td>
                    <div style="display: flex; gap: 8px;">
                        <button class="btn btn-secondary btn-icon-only btn-view-emp-stats" data-id="${emp.id}" data-name="${emp.name}" title="View Performance Statistics">
                            <i data-lucide="bar-chart-2"></i>
                        </button>
                        <button class="btn btn-secondary btn-icon-only btn-edit-employee" data-name="${emp.name}" title="Edit employee">
                            <i data-lucide="edit-3"></i>
                        </button>
                        <button class="btn btn-danger btn-icon-only btn-delete-employee" data-name="${emp.name}" title="Delete employee">
                            <i data-lucide="trash-2"></i>
                        </button>
                    </div>
                </td>
            `;
            tbody.appendChild(tr);
        });
        
        lucide.createIcons();
        attachEmployeeListeners();
    }

    // ----------------- 5. CONFIGS & WEIGHTS CONTROLLER -----------------
    async function loadConfigData() {
        // Load the full settings via the employees GET endpoint (which stores weights and configurations)
        const data = await apiRequest('/api/employees');
        if (!data) return;
        
        employeesData = data;
        configUnits = data.units || ["Broadcast", "Social", "Conductor", "Archive"];
        configRoles = data.roles || ["Live", "Playlist", "Helpdesk", "Social", "Conductor", "R&D", "Leader"];
        configConditions = data.special_conditions || ["Night Shift", "Remote Work", "Multi Task", "Condition Hardship", "Illness", "Discrete Working Hours", "General Requirements"];
        
        // 1. Error weights
        const weightsArea = document.getElementById('weights-fields');
        weightsArea.innerHTML = '';
        const weights = data.error_weights || {};
        Object.entries(weights).forEach(([key, val]) => {
            const group = document.createElement('div');
            group.className = 'form-group';
            group.innerHTML = `
                <label for="weight-${key}">${key}</label>
                <input type="number" step="0.1" class="form-control config-input-weight" id="weight-${key}" data-key="${key}" value="${val}">
            `;
            weightsArea.appendChild(group);
        });

        // 2. Decision thresholds
        const thresholdsArea = document.getElementById('thresholds-fields');
        thresholdsArea.innerHTML = '';
        const thresholds = data.decision_thresholds || {};
        Object.entries(thresholds).forEach(([key, val]) => {
            const group = document.createElement('div');
            group.className = 'form-group';
            // Handles both integers and lists (like HR Referral: [6, 3])
            const displayVal = Array.isArray(val) ? val.join(', ') : val;
            group.innerHTML = `
                <label for="thresh-${key}">${key}</label>
                <input type="text" class="form-control config-input-threshold" id="thresh-${key}" data-key="${key}" value="${displayVal}">
            `;
            thresholdsArea.appendChild(group);
        });

        // 3. Modifiers (Weights for locations, experience, etc.)
        const modifiersArea = document.getElementById('modifiers-fields');
        modifiersArea.innerHTML = '';
        
        // Render location weights
        const locTitle = document.createElement('h4');
        locTitle.innerText = "Location Modifiers";
        locTitle.className = "text-secondary small font-bold mt-2";
        modifiersArea.appendChild(locTitle);
        
        const locationWeights = data.work_location_weights || {};
        Object.entries(locationWeights).forEach(([key, val]) => {
            const group = document.createElement('div');
            group.className = 'form-group';
            group.innerHTML = `
                <label for="loc-${key}">${key}</label>
                <input type="number" step="0.1" class="form-control config-input-location" id="loc-${key}" data-key="${key}" value="${val}">
            `;
            modifiersArea.appendChild(group);
        });
        
        // Render special condition weights
        const condTitle = document.createElement('h4');
        condTitle.innerText = "Condition Modifiers";
        condTitle.className = "text-secondary small font-bold mt-2";
        modifiersArea.appendChild(condTitle);
        
        const condWeights = data.special_condition_weights || {};
        Object.entries(condWeights).forEach(([key, val]) => {
            const group = document.createElement('div');
            group.className = 'form-group';
            group.innerHTML = `
                <label for="cond-${key}">${key}</label>
                <input type="number" step="0.1" class="form-control config-input-condition" id="cond-${key}" data-key="${key}" value="${val}">
            `;
            modifiersArea.appendChild(group);
        });
    }

    // Save configurations listener
    document.getElementById('btn-save-configs').addEventListener('click', async () => {
        const payload = {
            error_weights: {},
            decision_thresholds: {},
            work_location_weights: {},
            special_condition_weights: {}
        };
        
        // Collect weights
        document.querySelectorAll('.config-input-weight').forEach(el => {
            payload.error_weights[el.getAttribute('data-key')] = parseFloat(el.value);
        });

        // Collect thresholds
        document.querySelectorAll('.config-input-threshold').forEach(el => {
            const val = el.value.trim();
            if (val.includes(',')) {
                // array conversion [6, 3]
                payload.decision_thresholds[el.getAttribute('data-key')] = val.split(',').map(x => parseInt(x.trim()));
            } else {
                payload.decision_thresholds[el.getAttribute('data-key')] = parseInt(val);
            }
        });

        // Collect location modifiers
        document.querySelectorAll('.config-input-location').forEach(el => {
            payload.work_location_weights[el.getAttribute('data-key')] = parseFloat(el.value);
        });

        // Collect condition modifiers
        document.querySelectorAll('.config-input-condition').forEach(el => {
            payload.special_condition_weights[el.getAttribute('data-key')] = parseFloat(el.value);
        });
        
        // Submit configuration updates
        const result = await apiRequest('/api/employees/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        if (result) {
            await showCustomAlert({ title: "Configuration Saved", message: "Configurations saved successfully!", type: "success" });
            loadConfigData();
        }
    });

    // Change Admin PIN Form Submit Handler
    document.getElementById('form-change-pin')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const currentPinEl = document.getElementById('admin-current-pin');
        const newPinEl = document.getElementById('admin-new-pin');
        const confirmPinEl = document.getElementById('admin-confirm-pin');
        
        if (!currentPinEl || !newPinEl || !confirmPinEl) {
            console.error("Change PIN inputs not found in the DOM.");
            return;
        }
        
        const currentPin = currentPinEl.value;
        const newPin = newPinEl.value;
        const confirmPin = confirmPinEl.value;
        
        if (newPin !== confirmPin) {
            await showCustomAlert({ title: "PIN Mismatch", message: "New PIN and confirm PIN do not match.", type: "error" });
            return;
        }
        
        if (newPin.length < 4) {
            await showCustomAlert({ title: "PIN Too Short", message: "New PIN must be at least 4 characters long.", type: "error" });
            return;
        }
        
        const result = await apiRequest('/api/admin/change-pin', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                current_pin: currentPin,
                new_pin: newPin
            })
        });
        
        if (result) {
            await showCustomAlert({ title: "PIN Updated", message: "Admin PIN has been updated successfully!", type: "success" });
            currentPinEl.value = '';
            newPinEl.value = '';
            confirmPinEl.value = '';
        } else {
            currentPinEl.value = '';
        }
    });

    // ----------------- MODAL MANAGERS -----------------
    const reportModal = document.getElementById('report-modal');
    const employeeModal = document.getElementById('employee-modal');
    const employeeStatsModal = document.getElementById('employee-stats-modal');
    const approvalModal = document.getElementById('approval-modal');

    // Close Modals buttons
    document.querySelectorAll('.btn-close-modal:not(.btn-dialog-close), .btn-close-modal-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            if (reportModal) reportModal.classList.remove('active');
            if (employeeModal) employeeModal.classList.remove('active');
            if (employeeStatsModal) employeeStatsModal.classList.remove('active');
            if (approvalModal) approvalModal.classList.remove('active');
        });
    });

    // Close modal when clicking background overlay
    [reportModal, employeeModal, employeeStatsModal, approvalModal].forEach(modal => {
        if (modal) {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    modal.classList.remove('active');
                }
            });
        }
    });

    // Global listener for employee performance stats button click
    document.addEventListener('click', (e) => {
        const btnStats = e.target.closest('.btn-view-emp-stats');
        if (btnStats) {
            const empName = btnStats.getAttribute('data-name') || btnStats.getAttribute('data-id');
            openEmployeeStatsModal(empName);
        }
    });

    async function openEmployeeStatsModal(empIdOrName) {
        const modal = document.getElementById('employee-stats-modal');
        const nameEl = document.getElementById('emp-stats-name');
        const subheadEl = document.getElementById('emp-stats-subhead');
        const leaderRatingEl = document.getElementById('emp-stats-leader-rating');
        const selfRatingEl = document.getElementById('emp-stats-self-rating');
        const adminRatingEl = document.getElementById('emp-stats-admin-rating');
        const moodEl = document.getElementById('emp-stats-mood');
        const reportsCountEl = document.getElementById('emp-stats-reports-count');
        const historyTbody = document.getElementById('emp-stats-history-tbody');

        if (!modal) return;

        if (nameEl) nameEl.innerText = "Loading statistics...";
        if (leaderRatingEl) leaderRatingEl.innerText = "-";
        if (selfRatingEl) selfRatingEl.innerText = "-";
        if (adminRatingEl) adminRatingEl.innerText = "-";
        if (moodEl) moodEl.innerText = "-";
        if (reportsCountEl) reportsCountEl.innerText = "...";
        if (historyTbody) historyTbody.innerHTML = '<tr><td colspan="5" class="text-center text-secondary py-3">Loading history...</td></tr>';

        modal.classList.add('active');

        const stats = await apiRequest(`/api/employees/${encodeURIComponent(empIdOrName)}/stats`);
        if (!stats) {
            if (nameEl) nameEl.innerText = "Error Loading Statistics";
            return;
        }

        const empName = stats.employee_name || empIdOrName;
        const unitStr = Array.isArray(stats.unit) ? stats.unit.join(', ') : (stats.unit || '-');
        const roleStr = Array.isArray(stats.roles) ? stats.roles.join(', ') : (stats.roles || '-');

        if (nameEl) nameEl.innerText = `${empName}'s Performance Stats`;
        if (subheadEl) subheadEl.innerText = `Unit: ${unitStr} | Roles: ${roleStr}`;

        if (leaderRatingEl) {
            leaderRatingEl.innerText = stats.avg_leader_rating !== null ? `🏅 ${stats.avg_leader_rating} / 10` : 'Not rated';
        }
        if (selfRatingEl) {
            selfRatingEl.innerText = stats.avg_self_rating !== null ? `⭐️ ${stats.avg_self_rating} / 10` : 'Not rated';
        }
        if (adminRatingEl) {
            adminRatingEl.innerText = stats.avg_admin_rating !== null ? `👑 ${stats.avg_admin_rating} / 10` : 'Not rated';
        }
        if (moodEl) {
            moodEl.innerText = stats.dominant_mood || 'Not recorded';
        }
        if (reportsCountEl) {
            reportsCountEl.innerText = `Total ${stats.total_reports_count || 0} Reports Submitted`;
        }

        // Render history table
        if (historyTbody) {
            historyTbody.innerHTML = '';
            const history = stats.history || [];
            if (history.length === 0) {
                historyTbody.innerHTML = '<tr><td colspan="5" class="text-center text-secondary py-3">No report history recorded yet.</td></tr>';
            } else {
                history.forEach(item => {
                    const dateStr = item.date ? new Date(item.date).toLocaleString('en-US', { dateStyle: 'medium' }) : '-';
                    const selfStr = item.self_rating !== null ? `<span class="badge badge-emerald">⭐️ ${item.self_rating}/10</span>` : '-';
                    const leaderStr = item.leader_rating !== null ? `<span class="badge badge-amber">🏅 ${item.leader_rating}/10</span>` : '-';
                    const adminStr = item.admin_rating !== null ? `<span class="badge badge-primary">👑 ${item.admin_rating}/10</span>` : '-';

                    const tr = document.createElement('tr');
                    tr.innerHTML = `
                        <td>${dateStr}</td>
                        <td>${selfStr}</td>
                        <td>${leaderStr}</td>
                        <td>${adminStr}</td>
                        <td><span class="small font-semibold">${item.mood || 'Unspecified'}</span></td>
                    `;
                    historyTbody.appendChild(tr);
                });
            }
        }

        if (typeof lucide !== 'undefined') lucide.createIcons();
    }

    function attachActionListeners() {
        // View detailed report click
        document.querySelectorAll('.btn-view').forEach(btn => {
            btn.addEventListener('click', () => {
                const reportId = btn.getAttribute('data-id');
                openReportModal(reportId);
            });
        });

        // Review/Approve report click
        document.querySelectorAll('.btn-review').forEach(btn => {
            btn.addEventListener('click', () => {
                const reportId = btn.getAttribute('data-id');
                openApprovalModal(reportId);
            });
        });

        // Edit report click
        document.querySelectorAll('.btn-edit').forEach(btn => {
            btn.addEventListener('click', () => {
                const reportId = btn.getAttribute('data-id');
                openEditReportModal(reportId);
            });
        });

        // Delete report click
        document.querySelectorAll('.btn-delete').forEach(btn => {
            btn.addEventListener('click', async () => {
                const reportId = btn.getAttribute('data-id');
                const confirmDelete = await showCustomConfirm({
                    title: "Delete Report",
                    message: "Are you sure you want to permanently delete this report?",
                    confirmText: "Yes, Delete",
                    cancelText: "Cancel",
                    isDanger: true
                });
                if (confirmDelete) {
                    try {
                        const res = await fetch(`/api/reports/${reportId}`, {
                            method: 'DELETE',
                            headers: { 'X-Session-Token': sessionToken }
                        });
                        if (res.ok) {
                            await showCustomAlert({
                                title: "Success",
                                message: "Report deleted successfully.",
                                type: "success"
                            });
                            await loadReportsData();
                        } else {
                            const errData = await res.json().catch(() => ({}));
                            await showCustomAlert({
                                title: "Error",
                                message: errData.detail || "Failed to delete the report.",
                                type: "danger"
                            });
                        }
                    } catch (e) {
                        await showCustomAlert({
                            title: "Error",
                            message: "Unable to connect to server.",
                            type: "danger"
                        });
                    }
                }
            });
        });
    }

    // Modal view implementation
    async function openReportModal(reportId) {
        const report = await apiRequest(`/api/reports/${reportId}`);
        if (!report) return;
        
        const isConsolidated = report.is_consolidated || report.isConsolidated;
        const reportData = report.data || {};
        const dateStr = safeFormatDate(report.created_at || report.submitted_at || report.timestamp, { dateStyle: 'long', timeStyle: 'short' });
        
        const empData = reportData.employee_data || {};
        const empName = isConsolidated ? (report.leader_name || 'Leader') : (reportData.employee || 'Unknown');
        const unitName = isConsolidated ? 'Leader Team Operations' : (empData.unit || 'Unknown');
        const workLocation = isConsolidated ? `Reporting Period: ${report.period || '-'}` : `${empData.work_location || 'Unknown'} (${empData.work_hours || '-'})`;

        const conditions = empData.special_conditions || [];
        const conditionTags = conditions.map(c => `<span class="tag">${c}</span>`).join(' ') || 'None';
        
        const servers = reportData.servers || [];
        const serverTags = servers.map(s => `<span class="tag">${s}</span>`).join(' ') || 'None';

        const sections = reportData.work_sections || (report.section ? [report.section] : []);
        const sectionTags = sections.map(s => `<span class="tag">${s}</span>`).join(' ') || 'None';
        
        // Metadata fields for Admin editing and inspection
        const empId = reportData.employee_id || report.employee_id || empData.id || 'N/A';
        const reportTitle = report.title || reportData.title || (isConsolidated ? "Consolidated Leader Report" : "Daily Shift Report");
        const statusBadge = report.status === 'approved' ? '<span class="badge badge-emerald">Approved</span>' : '<span class="badge badge-amber">Pending</span>';
        const assignedLeader = report.leader_name || (report.manager_feedback && report.manager_feedback.manager_id) || 'None';
        
        const createdTime = report.created_at || report.timestamp || '';
        const createdDateStr = createdTime ? new Date(createdTime).toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' }) : 'N/A';
        
        const updatedTime = report.updated_at || '';
        const updatedDateStr = updatedTime ? new Date(updatedTime).toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' }) : 'Never updated';

        // Compile incidents block with explicit problem category details
        const problems = report.problems || reportData.problems || [];
        let problemsHtml = '';
        if (problems.length > 0) {
            problems.forEach((p, idx) => {
                const liveDetails = p.live_event_name ? `
                    <div style="font-size: 0.8rem; margin-top: 4px; color: var(--amber);">
                        <strong>Program:</strong> ${p.live_event_name || 'Unspecified'} | <strong>Source:</strong> ${p.live_event_source || 'Unspecified'}
                    </div>
                ` : '';
                
                problemsHtml += `
                    <div class="issue-block" style="border: 1px solid var(--border-color); padding: 12px; border-radius: 8px; margin-bottom: 12px; background: rgba(255,255,255,0.01);">
                        <div class="issue-block-title" style="margin-bottom: 6px;">
                            <h5 style="margin: 0; color: var(--indigo-400);">Incident #${idx+1}</h5>
                        </div>
                        <div style="font-size: 0.85rem; margin-bottom: 6px;">
                            <strong>Problem Category:</strong> <span class="badge badge-rose" style="font-size:0.75rem; text-transform:uppercase;">${p.category || p.type || 'General'}</span>
                            ${p.subtype ? `| <strong>Subtype:</strong> ${p.subtype}` : ''}
                            ${p.servers && p.servers.length > 0 ? `| <strong>Servers:</strong> ${p.servers.join(', ')}` : ''}
                        </div>
                        ${liveDetails}
                        <div class="issue-block-desc" style="font-style: italic; font-size:0.9rem; margin-top: 6px;">"${p.description || 'No description provided'}"</div>
                    </div>
                `;
            });
        } else {
            problemsHtml = `<p class="text-emerald" style="font-weight: 500;"><i data-lucide="check-circle" style="width:16px; height:16px; display:inline; vertical-align:middle; margin-right:6px;"></i>No issues were reported today.</p>`;
        }
        
        // Compile document attachments
        const docs = reportData.documents || [];
        let docsHtml = '';
        if (docs.length > 0) {
            docs.forEach(doc => {
                docsHtml += `
                    <a href="/api/documents?path=${encodeURIComponent(doc.file_path)}" target="_blank" class="attachment-item">
                        <i data-lucide="file-symlink"></i>
                        <span>${doc.file_name} (${(doc.file_size / 1024).toFixed(1)} KB)</span>
                    </a>
                `;
            });
        } else {
            docsHtml = '<p class="text-secondary small">No files or screenshots attached</p>';
        }
        
        // Compile manager comments section
        let managerFeedbackHtml = '';
        if (report.status === 'approved') {
            const comment = report.manager_comment || report.manager_feedback?.comment || 'Approved without comment.';
            managerFeedbackHtml = `
                <div class="card bg-emerald-soft" style="border-color: rgba(16,185,129,0.3); padding: 16px; margin-top: 16px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                        <h4 class="text-emerald" style="margin:0;">Approved by Manager</h4>
                        <span class="badge badge-emerald" style="font-size:0.85rem; padding: 4px 10px;">Rating: ${report.manager_rating || report.manager_feedback?.rating}/10</span>
                    </div>
                    <p style="font-size:0.9rem; font-style:italic;">"${comment}"</p>
                </div>
            `;
        } else {
            managerFeedbackHtml = `
                <div class="card bg-amber-soft" style="border-color: rgba(245,158,11,0.3); padding:16px; margin-top: 16px; display:flex; justify-content:space-between; align-items:center;">
                    <span class="text-amber" style="font-weight:500;">Review Pending Approval</span>
                    ${userRole !== 'Admin' ? `<button class="btn btn-primary btn-review-from-modal" data-id="${report.id}">Start Review</button>` : ''}
                </div>
            `;
        }

        const notesContent = isConsolidated ? (report.summary_notes || 'No summary provided') : (reportData.additional_info || '');

        const bodyContainer = document.getElementById('report-modal-body');
        bodyContainer.innerHTML = `
            <div class="detail-section">
                <h4>Submission Info ${isConsolidated ? '<span class="badge badge-leader" style="font-size:0.75rem; margin-left:8px;">Consolidated Leader Report</span>' : ''}</h4>
                <div class="meta-grid">
                    <div class="meta-item">
                        <span class="label">Report Title</span>
                        <strong>${reportTitle}</strong>
                    </div>
                    <div class="meta-item">
                        <span class="label">Date & Time</span>
                        <strong>${dateStr}</strong>
                    </div>
                    <div class="meta-item">
                        <span class="label">${isConsolidated ? 'Leader Name' : 'Employee'}</span>
                        <strong>${empName} (ID: ${empId})</strong>
                    </div>
                    <div class="meta-item">
                        <span class="label">Department / Unit</span>
                        <span>${unitName}</span>
                    </div>
                    <div class="meta-item">
                        <span class="label">${isConsolidated ? 'Period' : 'Work Location'}</span>
                        <span>${workLocation}</span>
                    </div>
                    <div class="meta-item">
                        <span class="label">Status</span>
                        <span>${statusBadge}</span>
                    </div>
                    <div class="meta-item">
                        <span class="label">Assigned Leader</span>
                        <strong>${assignedLeader}</strong>
                    </div>
                    <div class="meta-item">
                        <span class="label">Submission Date</span>
                        <span>${createdDateStr}</span>
                    </div>
                    <div class="meta-item">
                        <span class="label">Last Updated</span>
                        <span>${updatedDateStr}</span>
                    </div>
                </div>
            </div>

            ${!isConsolidated ? `
            <div class="detail-section">
                <h4>Work Scope</h4>
                <div class="meta-grid">
                    <div>
                        <span class="label">Servers Handled</span>
                        <div class="list-tags">${serverTags}</div>
                    </div>
                    <div>
                        <span class="label">Work Sections</span>
                        <div class="list-tags">${sectionTags}</div>
                    </div>
                </div>
            </div>
            ` : ''}

            <div class="detail-section">
                <h4>${isConsolidated ? 'Consolidated Summary & Management Notes' : 'Performance Rating & Comments'}</h4>
                ${isConsolidated ? `
                    <div style="background-color:rgba(255,255,255,0.015); border:1px solid var(--border-color); border-radius:8px; padding:12px 16px; font-size:0.9rem; line-height:1.6;">
                        ${notesContent}
                    </div>
                ` : `
                    <div class="meta-grid">
                        <div class="meta-item">
                            <span class="label">Self Performance Rating</span>
                            <strong>${reportData.rating || 'Not rated'} / 10</strong>
                        </div>
                        <div class="meta-item">
                            <span class="label">Daily Mood</span>
                            <strong>${reportData.mood || 'Not specified'}</strong>
                        </div>
                    </div>
                    ${notesContent ? `
                        <div class="mt-3">
                            <span class="label">Employee Additional Comments</span>
                            <div style="background-color:rgba(255,255,255,0.01); border:1px solid var(--border-color); border-radius:6px; padding:10px 14px; font-size:0.875rem; font-style:italic;">
                                "${notesContent}"
                            </div>
                        </div>
                    ` : ''}
                `}
            </div>

            <div class="detail-section">
                <h4>Reported Incidents</h4>
                ${problemsHtml}
            </div>

            <div class="detail-section">
                <h4>Documents / Screenshots</h4>
                <div class="list-tags mt-2">
                    ${docsHtml}
                </div>
            </div>
            
            ${managerFeedbackHtml}
        `;
        
        // Dynamically build footer with Edit Report action for Admins
        const footerContainer = document.getElementById('report-modal-footer');
        footerContainer.innerHTML = `
            <button class="btn btn-secondary btn-close-modal-btn">Close</button>
            ${userRole === 'Admin' ? `
                <button class="btn btn-primary btn-edit-from-modal">
                    <i data-lucide="edit-3"></i>
                    <span>Edit Report</span>
                </button>
            ` : ''}
        `;
        
        lucide.createIcons();
        reportModal.classList.add('active');
        
        // Wire up close button
        footerContainer.querySelector('.btn-close-modal-btn').addEventListener('click', () => {
            reportModal.classList.remove('active');
        });
        
        // Wire up Edit button
        if (userRole === 'Admin') {
            footerContainer.querySelector('.btn-edit-from-modal').addEventListener('click', () => {
                reportModal.classList.remove('active');
                openEditReportModal(report.id);
            });
        }
        
        // Listen to Quick review button inside modal if pending (for Leaders/non-admins)
        const btnReviewModal = bodyContainer.querySelector('.btn-review-from-modal');
        if (btnReviewModal) {
            btnReviewModal.addEventListener('click', () => {
                reportModal.classList.remove('active');
                openApprovalModal(reportId);
            });
        }
    }

    // Approval modal setup
    const ratingInput = document.getElementById('approval-rating');
    const ratingBadge = document.getElementById('rating-val-badge');
    
    // Sync slider display badge
    ratingInput.addEventListener('input', (e) => {
        ratingBadge.innerText = `${e.target.value} / 10`;
    });

    async function openApprovalModal(reportId) {
        const report = await apiRequest(`/api/reports/${reportId}`);
        if (!report) return;
        
        const reportData = report.data || {};
        
        document.getElementById('approval-report-id').value = reportId;
        document.getElementById('approval-emp-header').innerText = `Employee: ${reportData.employee || 'Unknown'}`;
        
        const date = new Date(report.created_at || report.timestamp);
        document.getElementById('approval-time-header').innerText = `Submitted: ${date.toLocaleString('en-US')}`;
        
        // List problems count in summary box
        const problems = reportData.problems || [];
        const summaryDiv = document.getElementById('approval-problems-summary');
        if (problems.length > 0) {
            summaryDiv.innerHTML = `
                <div class="badge badge-rose" style="margin-bottom:6px;">⚠️ Incident Report</div>
                <ul style="padding-left:16px; font-size:0.85rem; color:var(--text-secondary);">
                    ${problems.map(p => `<li>${p.type}${p.subtype ? ' > ' + p.subtype : ''}: ${p.description || 'No details'}</li>`).join('')}
                </ul>
            `;
        } else {
            summaryDiv.innerHTML = `<span class="badge badge-emerald">✅ Clean Shift Report</span>`;
        }

        // Populate Unit Dropdown
        const unitContainer = document.getElementById('approval-unit-container');
        const unitSelect = document.getElementById('approval-unit');
        
        const allowedUnits = report.allowed_review_units || [];
        const approvedUnits = report.approved_units || [];
        const pendingReviewUnits = allowedUnits.filter(u => !approvedUnits.includes(u));
        
        if (pendingReviewUnits.length > 1) {
            unitContainer.style.display = 'block';
            unitSelect.innerHTML = pendingReviewUnits.map(u => `<option value="${u}">${u}</option>`).join('');
        } else {
            unitContainer.style.display = 'none';
            unitSelect.innerHTML = '';
        }
        
        // Reset inputs
        ratingInput.value = 8;
        ratingBadge.innerText = "8 / 10";
        document.getElementById('approval-comment').value = "";
        
        lucide.createIcons();
        approvalModal.classList.add('active');
    }

    // Submit Approval Form handler
    document.getElementById('approval-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const reportId = document.getElementById('approval-report-id').value;
        const managerRating = parseInt(ratingInput.value);
        const managerComment = document.getElementById('approval-comment').value.trim();
        
        const unitSelect = document.getElementById('approval-unit');
        let selectedUnit = null;
        if (unitSelect && unitSelect.value) {
            selectedUnit = unitSelect.value;
        }
        
        const payload = {
            manager_rating: managerRating,
            manager_comment: managerComment
        };
        if (selectedUnit) {
            payload.unit = selectedUnit;
        }
        
        const result = await apiRequest(`/api/reports/${reportId}/approve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        if (result) {
            await showCustomAlert({ title: "Report Approved", message: "Report approved and Excel log generated successfully!", type: "success" });
            approvalModal.classList.remove('active');
            
            // Refresh current view
            if (activeTab === 'pending') {
                loadPendingQueue();
            } else if (activeTab === 'reports') {
                loadReportsData();
            } else {
                loadDashboardData();
            }
        }
    });

    // ----------------- MULTI-SELECT DROPDOWN CONTROLLER -----------------
    let selectedUnits = [];
    
    const unitContainer = document.getElementById('emp-unit-container');
    const unitSelected = document.getElementById('emp-unit-selected');
    const unitSearch = document.getElementById('emp-unit-search');
    const unitDropdown = document.getElementById('emp-unit-dropdown');
    const hiddenUnitInput = document.getElementById('emp-unit');
    
    function parseEmployeeUnits(unitField) {
        if (!unitField) return [];
        if (Array.isArray(unitField)) return unitField;
        if (typeof unitField === 'string') {
            const units = [];
            const uLower = unitField.toLowerCase();
            if (uLower.includes('broadcast')) units.push('Broadcast');
            if (uLower.includes('social')) units.push('Social');
            if (uLower.includes('conductor')) units.push('Conductor');
            if (uLower.includes('archive')) units.push('Archive');
            return units;
        }
        return [];
    }

    function adjustDropdownPosition(container) {
        const dropdown = container.querySelector('.multi-select-dropdown');
        if (!dropdown) return;
        
        const rect = container.getBoundingClientRect();
        const dropdownHeight = 180; // max-height is 180px
        const viewportHeight = window.innerHeight;
        
        // If there isn't enough space below, but there is space above, open above
        if (rect.bottom + dropdownHeight > viewportHeight && rect.top - dropdownHeight > 0) {
            container.classList.add('open-above');
        } else {
            container.classList.remove('open-above');
        }
    }
    
    document.addEventListener('focusin', (e) => {
        const container = e.target.closest('.multi-select-container');
        if (container) {
            adjustDropdownPosition(container);
        }
    });
    
    document.addEventListener('click', (e) => {
        const container = e.target.closest('.multi-select-container');
        if (container) {
            adjustDropdownPosition(container);
        }
    });

    function updateUnitsUI() {
        // Clear old chips
        const chips = unitSelected.querySelectorAll('.chip');
        chips.forEach(c => c.remove());
        
        // Add new chips
        selectedUnits.forEach(unit => {
            const chip = document.createElement('span');
            chip.className = 'chip';
            chip.dataset.value = unit;
            chip.innerHTML = `${unit} <button type="button" class="chip-remove" data-value="${unit}">&times;</button>`;
            unitSelected.insertBefore(chip, unitSearch);
        });
        
        // Chip removal listener
        unitSelected.querySelectorAll('.chip-remove').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const val = btn.getAttribute('data-value');
                removeUnit(val);
            });
        });
        
        // Update checkmarks in dropdown
        const options = unitDropdown.querySelectorAll('.multi-select-option');
        options.forEach(opt => {
            const val = opt.getAttribute('data-value');
            if (selectedUnits.includes(val)) {
                opt.classList.add('selected');
            } else {
                opt.classList.remove('selected');
            }
        });
        
        // Update input validity & value
        hiddenUnitInput.value = selectedUnits.length > 0 ? JSON.stringify(selectedUnits) : '';
        if (selectedUnits.length > 0) {
            unitContainer.classList.remove('is-invalid');
        }
    }
    
    function addUnit(unit) {
        if (!selectedUnits.includes(unit)) {
            selectedUnits.push(unit);
            updateUnitsUI();
        }
        unitSearch.value = '';
        filterOptions('');
    }
    
    function removeUnit(unit) {
        selectedUnits = selectedUnits.filter(u => u !== unit);
        updateUnitsUI();
    }
    
    function filterOptions(query) {
        const q = query.toLowerCase().trim();
        const options = unitDropdown.querySelectorAll('.multi-select-option');
        let visibleCount = 0;
        
        options.forEach(opt => {
            const val = opt.getAttribute('data-value').toLowerCase();
            if (val.includes(q)) {
                opt.classList.remove('hidden');
                visibleCount++;
            } else {
                opt.classList.add('hidden');
            }
        });
        
        if (visibleCount > 0 && document.activeElement === unitSearch) {
            unitContainer.classList.add('open');
        } else if (visibleCount === 0) {
            unitContainer.classList.remove('open');
        }
    }
    
    // Setup event listeners for custom dropdown UI interactions
    unitSelected.addEventListener('click', (e) => {
        // Prevent toggle if clicking on search input
        if (e.target === unitSearch) return;
        
        e.stopPropagation();
        const isOpen = unitContainer.classList.contains('open');
        if (isOpen) {
            unitContainer.classList.remove('open');
            unitContainer.classList.remove('focus');
            unitSearch.blur();
        } else {
            unitContainer.classList.add('focus');
            unitContainer.classList.add('open');
            unitSearch.focus();
            filterOptions(unitSearch.value);
        }
    });
    
    const unitToggle = document.getElementById('emp-unit-toggle');
    unitToggle.addEventListener('click', (e) => {
        e.stopPropagation();
        const isOpen = unitContainer.classList.contains('open');
        if (isOpen) {
            unitContainer.classList.remove('open');
            unitContainer.classList.remove('focus');
            unitSearch.blur();
        } else {
            unitContainer.classList.add('focus');
            unitContainer.classList.add('open');
            unitSearch.focus();
            filterOptions(unitSearch.value);
        }
    });
    
    unitSearch.addEventListener('focus', () => {
        unitContainer.classList.add('focus');
        unitContainer.classList.add('open');
        filterOptions(unitSearch.value);
    });
    
    // Close dropdown on click outside
    document.addEventListener('click', (e) => {
        if (!unitContainer.contains(e.target)) {
            unitContainer.classList.remove('open');
            unitContainer.classList.remove('focus');
        }
    });
    
    unitSearch.addEventListener('input', () => {
        filterOptions(unitSearch.value);
    });
    
    unitSearch.addEventListener('keydown', (e) => {
        if (e.key === 'Backspace' && unitSearch.value === '' && selectedUnits.length > 0) {
            removeUnit(selectedUnits[selectedUnits.length - 1]);
        } else if (e.key === 'Escape') {
            unitContainer.classList.remove('open');
            unitContainer.classList.remove('focus');
            unitSearch.blur();
            e.stopPropagation();
        }
    });
    
    unitDropdown.querySelectorAll('.multi-select-option').forEach(opt => {
        opt.addEventListener('click', (e) => {
            e.stopPropagation();
            const val = opt.getAttribute('data-value');
            if (selectedUnits.includes(val)) {
                removeUnit(val);
            } else {
                addUnit(val);
            }
            unitSearch.focus();
        });
    });

    // ----------------- MULTI-SELECT ROLES DROPDOWN CONTROLLER -----------------
    let selectedRoles = [];
    
    const rolesContainer = document.getElementById('emp-roles-container');
    const rolesSelected = document.getElementById('emp-roles-selected');
    const rolesSearch = document.getElementById('emp-roles-search');
    const rolesDropdown = document.getElementById('emp-roles-dropdown');
    const hiddenRolesInput = document.getElementById('emp-roles');
    
    function parseEmployeeRoles(rolesField) {
        if (!rolesField) return [];
        if (Array.isArray(rolesField)) return rolesField;
        if (typeof rolesField === 'string') {
            return rolesField.split(',').map(r => r.trim()).filter(Boolean);
        }
        return [];
    }

    function updateRolesUI() {
        // Clear old chips
        const chips = rolesSelected.querySelectorAll('.chip');
        chips.forEach(c => c.remove());
        
        // Add new chips
        selectedRoles.forEach(role => {
            const chip = document.createElement('span');
            chip.className = 'chip';
            chip.dataset.value = role;
            chip.innerHTML = `${role} <button type="button" class="chip-remove" data-value="${role}">&times;</button>`;
            rolesSelected.insertBefore(chip, rolesSearch);
        });
        
        // Chip removal listener
        rolesSelected.querySelectorAll('.chip-remove').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const val = btn.getAttribute('data-value');
                removeRole(val);
            });
        });
        
        // Update checkmarks in dropdown
        const options = rolesDropdown.querySelectorAll('.multi-select-option');
        options.forEach(opt => {
            const val = opt.getAttribute('data-value');
            if (selectedRoles.includes(val)) {
                opt.classList.add('selected');
            } else {
                opt.classList.remove('selected');
            }
        });
        
        // Update input validity & value
        hiddenRolesInput.value = selectedRoles.length > 0 ? JSON.stringify(selectedRoles) : '';
        if (selectedRoles.length > 0) {
            rolesContainer.classList.remove('is-invalid');
        }

        // Toggle Leader Category & Leader Shift visibility
        const isLeader = selectedRoles.includes('Leader');
        const leaderTypeGrp = document.getElementById('emp-leader-type-group');
        const leaderShiftGrp = document.getElementById('emp-leader-shift-group');
        if (leaderTypeGrp) {
            if (isLeader) {
                leaderTypeGrp.style.display = 'block';
            } else {
                leaderTypeGrp.style.display = 'none';
                selectedLeaderType = "";
                if (typeof updateLeaderTypeUI === 'function') {
                    updateLeaderTypeUI();
                }
            }
        }
        if (leaderShiftGrp) {
            leaderShiftGrp.style.display = isLeader ? 'block' : 'none';
            if (!isLeader) {
                const shiftSelect = document.getElementById('emp-leader-shift');
                if (shiftSelect) shiftSelect.value = '';
            }
        }
    }
    
    function addRole(role) {
        if (!selectedRoles.includes(role)) {
            selectedRoles.push(role);
            updateRolesUI();
        }
        rolesSearch.value = '';
        filterRolesOptions('');
    }
    
    function removeRole(role) {
        selectedRoles = selectedRoles.filter(r => r !== role);
        updateRolesUI();
    }
    
    function filterRolesOptions(query) {
        const q = query.toLowerCase().trim();
        const options = rolesDropdown.querySelectorAll('.multi-select-option');
        let visibleCount = 0;
        
        options.forEach(opt => {
            const val = opt.getAttribute('data-value').toLowerCase();
            if (val.includes(q)) {
                opt.classList.remove('hidden');
                visibleCount++;
            } else {
                opt.classList.add('hidden');
            }
        });
        
        if (visibleCount > 0 && document.activeElement === rolesSearch) {
            rolesContainer.classList.add('open');
        } else if (visibleCount === 0) {
            rolesContainer.classList.remove('open');
        }
    }
    
    // Setup event listeners for roles dropdown UI interactions
    rolesSelected.addEventListener('click', (e) => {
        if (e.target === rolesSearch) return;
        
        e.stopPropagation();
        const isOpen = rolesContainer.classList.contains('open');
        if (isOpen) {
            rolesContainer.classList.remove('open');
            rolesContainer.classList.remove('focus');
            rolesSearch.blur();
        } else {
            rolesContainer.classList.add('focus');
            rolesContainer.classList.add('open');
            rolesSearch.focus();
            filterRolesOptions(rolesSearch.value);
        }
    });
    
    const rolesToggle = document.getElementById('emp-roles-toggle');
    rolesToggle.addEventListener('click', (e) => {
        e.stopPropagation();
        const isOpen = rolesContainer.classList.contains('open');
        if (isOpen) {
            rolesContainer.classList.remove('open');
            rolesContainer.classList.remove('focus');
            rolesSearch.blur();
        } else {
            rolesContainer.classList.add('focus');
            rolesContainer.classList.add('open');
            rolesSearch.focus();
            filterRolesOptions(rolesSearch.value);
        }
    });
    
    rolesSearch.addEventListener('focus', () => {
        rolesContainer.classList.add('focus');
        rolesContainer.classList.add('open');
        filterRolesOptions(rolesSearch.value);
    });
    
    // Close dropdown on click outside
    document.addEventListener('click', (e) => {
        if (!rolesContainer.contains(e.target)) {
            rolesContainer.classList.remove('open');
            rolesContainer.classList.remove('focus');
        }
    });
    
    rolesSearch.addEventListener('input', () => {
        filterRolesOptions(rolesSearch.value);
    });
    
    rolesSearch.addEventListener('keydown', (e) => {
        if (e.key === 'Backspace' && rolesSearch.value === '' && selectedRoles.length > 0) {
            removeRole(selectedRoles[selectedRoles.length - 1]);
        } else if (e.key === 'Escape') {
            rolesContainer.classList.remove('open');
            rolesContainer.classList.remove('focus');
            rolesSearch.blur();
            e.stopPropagation();
        }
    });
    
    // ----------------- MULTI-SELECT CONDITIONS DROPDOWN CONTROLLER -----------------
    let selectedConditions = [];
    
    const conditionsContainer = document.getElementById('emp-conditions-container');
    const conditionsSelected = document.getElementById('emp-conditions-selected');
    const conditionsSearch = document.getElementById('emp-conditions-search');
    const conditionsDropdown = document.getElementById('emp-conditions-dropdown');
    const hiddenConditionsInput = document.getElementById('emp-conditions');
    
    function parseEmployeeConditions(condField) {
        if (!condField) return [];
        if (Array.isArray(condField)) return condField;
        if (typeof condField === 'string') {
            return condField.split(',').map(c => c.trim()).filter(Boolean);
        }
        return [];
    }

    function updateConditionsUI() {
        // Clear old chips
        const chips = conditionsSelected.querySelectorAll('.chip');
        chips.forEach(c => c.remove());
        
        // Add new chips
        selectedConditions.forEach(cond => {
            const chip = document.createElement('span');
            chip.className = 'chip';
            chip.dataset.value = cond;
            chip.innerHTML = `${cond} <button type="button" class="chip-remove" data-value="${cond}">&times;</button>`;
            conditionsSelected.insertBefore(chip, conditionsSearch);
        });
        
        // Chip removal listener
        conditionsSelected.querySelectorAll('.chip-remove').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const val = btn.getAttribute('data-value');
                removeCondition(val);
            });
        });
        
        // Update checkmarks in dropdown
        const options = conditionsDropdown.querySelectorAll('.multi-select-option');
        options.forEach(opt => {
            const val = opt.getAttribute('data-value');
            if (selectedConditions.includes(val)) {
                opt.classList.add('selected');
            } else {
                opt.classList.remove('selected');
            }
        });
        
        // Update input validity & value
        hiddenConditionsInput.value = JSON.stringify(selectedConditions);
        conditionsContainer.classList.remove('is-invalid');
    }
    
    function addCondition(cond) {
        if (!selectedConditions.includes(cond)) {
            selectedConditions.push(cond);
            updateConditionsUI();
        }
        conditionsSearch.value = '';
        filterConditionsOptions('');
    }
    
    function removeCondition(cond) {
        selectedConditions = selectedConditions.filter(c => c !== cond);
        updateConditionsUI();
    }
    
    function filterConditionsOptions(query) {
        const q = query.toLowerCase().trim();
        const options = conditionsDropdown.querySelectorAll('.multi-select-option');
        let visibleCount = 0;
        
        options.forEach(opt => {
            const val = opt.getAttribute('data-value').toLowerCase();
            if (val.includes(q)) {
                opt.classList.remove('hidden');
                visibleCount++;
            } else {
                opt.classList.add('hidden');
            }
        });
        
        if (visibleCount > 0 && document.activeElement === conditionsSearch) {
            conditionsContainer.classList.add('open');
        } else if (visibleCount === 0) {
            conditionsContainer.classList.remove('open');
        }
    }
    
    // Setup event listeners for conditions dropdown UI interactions
    conditionsSelected.addEventListener('click', (e) => {
        if (e.target === conditionsSearch) return;
        
        e.stopPropagation();
        const isOpen = conditionsContainer.classList.contains('open');
        if (isOpen) {
            conditionsContainer.classList.remove('open');
            conditionsContainer.classList.remove('focus');
            conditionsSearch.blur();
        } else {
            conditionsContainer.classList.add('focus');
            conditionsContainer.classList.add('open');
            conditionsSearch.focus();
            filterConditionsOptions(conditionsSearch.value);
        }
    });
    
    const conditionsToggle = document.getElementById('emp-conditions-toggle');
    conditionsToggle.addEventListener('click', (e) => {
        e.stopPropagation();
        const isOpen = conditionsContainer.classList.contains('open');
        if (isOpen) {
            conditionsContainer.classList.remove('open');
            conditionsContainer.classList.remove('focus');
            conditionsSearch.blur();
        } else {
            conditionsContainer.classList.add('focus');
            conditionsContainer.classList.add('open');
            conditionsSearch.focus();
            filterConditionsOptions(conditionsSearch.value);
        }
    });
    
    conditionsSearch.addEventListener('focus', () => {
        conditionsContainer.classList.add('focus');
        conditionsContainer.classList.add('open');
        filterConditionsOptions(conditionsSearch.value);
    });
    
    // Close dropdown on click outside
    document.addEventListener('click', (e) => {
        if (!conditionsContainer.contains(e.target)) {
            conditionsContainer.classList.remove('open');
            conditionsContainer.classList.remove('focus');
        }
    });
    
    conditionsSearch.addEventListener('input', () => {
        filterConditionsOptions(conditionsSearch.value);
    });
    
    conditionsSearch.addEventListener('keydown', (e) => {
        if (e.key === 'Backspace' && conditionsSearch.value === '' && selectedConditions.length > 0) {
            removeCondition(selectedConditions[selectedConditions.length - 1]);
        } else if (e.key === 'Escape') {
            conditionsContainer.classList.remove('open');
            conditionsContainer.classList.remove('focus');
            conditionsSearch.blur();
            e.stopPropagation();
        }
    });

    // ----------------- SINGLE-SELECT LEADER TYPE DROPDOWN CONTROLLER -----------------
    let selectedLeaderType = "";
    
    const leaderTypeContainer = document.getElementById('emp-leader-type-container');
    const leaderTypeSelected = document.getElementById('emp-leader-type-selected');
    const leaderTypeSearch = document.getElementById('emp-leader-type-search');
    const leaderTypeDropdown = document.getElementById('emp-leader-type-dropdown');
    const hiddenLeaderTypeInput = document.getElementById('emp-leader-type');
    
    function updateLeaderTypeUI() {
        // Clear old chips
        const chips = leaderTypeSelected.querySelectorAll('.chip');
        chips.forEach(c => c.remove());
        
        // Add new chip if selectedLeaderType is set
        if (selectedLeaderType) {
            const chip = document.createElement('span');
            chip.className = 'chip';
            chip.dataset.value = selectedLeaderType;
            chip.innerHTML = `${selectedLeaderType} <button type="button" class="chip-remove" data-value="${selectedLeaderType}">&times;</button>`;
            leaderTypeSelected.insertBefore(chip, leaderTypeSearch);
            leaderTypeSearch.placeholder = ""; // hide placeholder if selected
        } else {
            leaderTypeSearch.placeholder = "Select leader category...";
        }
        
        // Update checkmarks/selected class in dropdown options
        const options = leaderTypeDropdown.querySelectorAll('.multi-select-option');
        options.forEach(opt => {
            const val = opt.getAttribute('data-value');
            if (val === selectedLeaderType) {
                opt.classList.add('selected');
            } else {
                opt.classList.remove('selected');
            }
        });
        
        // Update hidden input
        hiddenLeaderTypeInput.value = selectedLeaderType;
        if (selectedLeaderType) {
            leaderTypeContainer.classList.remove('is-invalid');
        }
    }
    
    function selectLeaderType(val) {
        selectedLeaderType = val;
        updateLeaderTypeUI();
        leaderTypeContainer.classList.remove('open');
        leaderTypeContainer.classList.remove('focus');
        leaderTypeSearch.blur();
        leaderTypeSearch.value = "";
        filterLeaderTypeOptions("");
    }
    
    function removeLeaderType() {
        selectedLeaderType = "";
        updateLeaderTypeUI();
        leaderTypeSearch.focus();
    }
    
    function filterLeaderTypeOptions(query) {
        const q = query.toLowerCase().trim();
        const options = leaderTypeDropdown.querySelectorAll('.multi-select-option');
        let visibleCount = 0;
        
        options.forEach(opt => {
            const val = opt.getAttribute('data-value').toLowerCase();
            if (val.includes(q)) {
                opt.classList.remove('hidden');
                visibleCount++;
            } else {
                opt.classList.add('hidden');
            }
        });
        
        if (visibleCount > 0 && document.activeElement === leaderTypeSearch) {
            leaderTypeContainer.classList.add('open');
        } else if (visibleCount === 0) {
            leaderTypeContainer.classList.remove('open');
        }
    }
    
    // Setup event listeners for leader type dropdown UI interactions
    leaderTypeSelected.addEventListener('click', (e) => {
        if (e.target === leaderTypeSearch) return;
        
        e.stopPropagation();
        const isOpen = leaderTypeContainer.classList.contains('open');
        if (isOpen) {
            leaderTypeContainer.classList.remove('open');
            leaderTypeContainer.classList.remove('focus');
            leaderTypeSearch.blur();
        } else {
            leaderTypeContainer.classList.add('focus');
            leaderTypeContainer.classList.add('open');
            leaderTypeSearch.focus();
            filterLeaderTypeOptions(leaderTypeSearch.value);
        }
    });
    
    const leaderTypeToggle = document.getElementById('emp-leader-type-toggle');
    if (leaderTypeToggle) {
        leaderTypeToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            const isOpen = leaderTypeContainer.classList.contains('open');
            if (isOpen) {
                leaderTypeContainer.classList.remove('open');
                leaderTypeContainer.classList.remove('focus');
                leaderTypeSearch.blur();
            } else {
                leaderTypeContainer.classList.add('focus');
                leaderTypeContainer.classList.add('open');
                leaderTypeSearch.focus();
                filterLeaderTypeOptions(leaderTypeSearch.value);
            }
        });
    }
    
    leaderTypeSearch.addEventListener('focus', () => {
        leaderTypeContainer.classList.add('focus');
        leaderTypeContainer.classList.add('open');
        filterLeaderTypeOptions(leaderTypeSearch.value);
    });
    
    leaderTypeSearch.addEventListener('input', (e) => {
        filterLeaderTypeOptions(e.target.value);
    });
    
    leaderTypeDropdown.addEventListener('click', (e) => {
        const option = e.target.closest('.multi-select-option');
        if (option) {
            const val = option.getAttribute('data-value');
            selectLeaderType(val);
        }
    });
    
    leaderTypeSelected.addEventListener('click', (e) => {
        const btnRemove = e.target.closest('.chip-remove');
        if (btnRemove) {
            e.stopPropagation();
            removeLeaderType();
        }
    });
    
    document.addEventListener('click', (e) => {
        if (leaderTypeContainer && !leaderTypeContainer.contains(e.target)) {
            leaderTypeContainer.classList.remove('open');
            leaderTypeContainer.classList.remove('focus');
            leaderTypeSearch.blur();
        }
    });

    // ----------------- MULTI-SELECT PERSONAL REPORT SECTIONS CONTROLLER -----------------
    let selectedPersonalSections = [];

    // ----------------- PERSONAL REPORT ISSUES LIST CONTROLLER -----------------
    let personalIssues = [];

    function renderPersonalIssues() {
        const container = document.getElementById('personal-issues-list');
        if (!container) return;

        if (personalIssues.length === 0) {
            container.style.display = 'none';
            container.innerHTML = '';
            return;
        }

        container.style.display = 'flex';
        container.innerHTML = personalIssues.map((issue, idx) => `
            <div class="card bg-slate-800 p-3 mb-2" style="border: 1px solid var(--border-color); position: relative; border-radius: 8px; background: rgba(30, 41, 59, 0.4); width: 100%;">
                <button type="button" class="btn-delete-personal-issue" data-index="${idx}" style="position: absolute; top: 12px; right: 12px; background: none; border: none; color: #f43f5e; cursor: pointer; font-size: 1.1rem; display: flex; align-items: center; justify-content: center; width: 24px; height: 24px;">
                    &times;
                </button>
                <h5 style="margin: 0 0 6px 0; color: var(--primary); font-size: 0.85rem; font-weight: 600;">Issue #${idx+1} - ${issue.type}</h5>
                <p style="margin: 0 0 4px 0; font-size: 0.85rem;"><strong class="text-secondary">Headline:</strong> ${issue.subcategory}</p>
                ${issue.live_event_name ? `<p style="margin: 0 0 4px 0; font-size: 0.8rem;"><strong class="text-secondary">Live Event:</strong> ${issue.live_event_name} (${issue.live_event_source})</p>` : ''}
                <p style="margin: 0; font-size: 0.85rem; color: var(--text-secondary); line-height: 1.4;">${issue.description}</p>
            </div>
        `).join('');

        // Bind delete buttons
        container.querySelectorAll('.btn-delete-personal-issue').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const idx = parseInt(btn.getAttribute('data-index'));
                personalIssues.splice(idx, 1);
                renderPersonalIssues();
            });
        });
    }

    // Initialize Add Issue Button Click Listener
    document.getElementById('btn-personal-add-issue')?.addEventListener('click', () => {
        const section = document.getElementById('personal-report-section').value;
        const headline = document.getElementById('personal-report-subcategory').value.trim();
        const description = document.getElementById('personal-report-description').value.trim();

        if (!headline || !description) {
            showCustomAlert({ title: "Missing Fields", message: "Please fill in the Headline and Problem Description before adding an issue.", type: "warning" });
            return;
        }

        const newIssue = {
            type: section,
            category: section,
            subcategory: headline,
            description: description
        };

        personalIssues.push(newIssue);
        renderPersonalIssues();

        // Clear form fields
        document.getElementById('personal-report-subcategory').value = '';
        document.getElementById('personal-report-description').value = '';
    });
    


    // ----------------- SINGLE-SELECT LOCATION DROPDOWN CONTROLLER -----------------
    let selectedLocation = "";
    
    const locationContainer = document.getElementById('emp-location-container');
    const locationSelected = document.getElementById('emp-location-selected');
    const locationSearch = document.getElementById('emp-location-search');
    const locationDropdown = document.getElementById('emp-location-dropdown');
    const hiddenLocationInput = document.getElementById('emp-location');
    
    function updateLocationUI() {
        // Clear old chips
        const chips = locationSelected.querySelectorAll('.chip');
        chips.forEach(c => c.remove());
        
        // Add new chip if selectedLocation is set
        if (selectedLocation) {
            const chip = document.createElement('span');
            chip.className = 'chip';
            chip.dataset.value = selectedLocation;
            chip.innerHTML = `${selectedLocation} <button type="button" class="chip-remove" data-value="${selectedLocation}">&times;</button>`;
            locationSelected.insertBefore(chip, locationSearch);
            locationSearch.placeholder = ""; // hide placeholder if selected
        } else {
            locationSearch.placeholder = "Select location...";
        }
        
        // Update checkmarks/selected class in dropdown options
        const options = locationDropdown.querySelectorAll('.multi-select-option');
        options.forEach(opt => {
            const val = opt.getAttribute('data-value');
            if (val === selectedLocation) {
                opt.classList.add('selected');
            } else {
                opt.classList.remove('selected');
            }
        });
        
        // Update hidden input
        hiddenLocationInput.value = selectedLocation;
        if (selectedLocation) {
            locationContainer.classList.remove('is-invalid');
        }
    }
    
    function selectLocation(loc) {
        selectedLocation = loc;
        updateLocationUI();
        locationContainer.classList.remove('open');
        locationContainer.classList.remove('focus');
        locationSearch.blur();
        locationSearch.value = "";
        filterLocationOptions("");
    }
    
    function removeLocation() {
        selectedLocation = "";
        updateLocationUI();
        locationSearch.focus();
    }
    
    function filterLocationOptions(query) {
        const q = query.toLowerCase().trim();
        const options = locationDropdown.querySelectorAll('.multi-select-option');
        let visibleCount = 0;
        
        options.forEach(opt => {
            const val = opt.getAttribute('data-value').toLowerCase();
            if (val.includes(q)) {
                opt.classList.remove('hidden');
                visibleCount++;
            } else {
                opt.classList.add('hidden');
            }
        });
        
        if (visibleCount > 0 && document.activeElement === locationSearch) {
            locationContainer.classList.add('open');
        } else if (visibleCount === 0) {
            locationContainer.classList.remove('open');
        }
    }
    
    // Setup event listeners for location dropdown UI interactions
    locationSelected.addEventListener('click', (e) => {
        if (e.target === locationSearch) return;
        
        e.stopPropagation();
        const isOpen = locationContainer.classList.contains('open');
        if (isOpen) {
            locationContainer.classList.remove('open');
            locationContainer.classList.remove('focus');
            locationSearch.blur();
        } else {
            locationContainer.classList.add('focus');
            locationContainer.classList.add('open');
            locationSearch.focus();
            filterLocationOptions(locationSearch.value);
        }
    });
    
    const locationToggle = document.getElementById('emp-location-toggle');
    locationToggle.addEventListener('click', (e) => {
        e.stopPropagation();
        const isOpen = locationContainer.classList.contains('open');
        if (isOpen) {
            locationContainer.classList.remove('open');
            locationContainer.classList.remove('focus');
            locationSearch.blur();
        } else {
            locationContainer.classList.add('focus');
            locationContainer.classList.add('open');
            locationSearch.focus();
            filterLocationOptions(locationSearch.value);
        }
    });
    
    locationSearch.addEventListener('focus', () => {
        locationContainer.classList.add('focus');
        locationContainer.classList.add('open');
        filterLocationOptions(locationSearch.value);
    });
    
    // Close dropdown on click outside
    document.addEventListener('click', (e) => {
        if (!locationContainer.contains(e.target)) {
            locationContainer.classList.remove('open');
            locationContainer.classList.remove('focus');
        }
    });
    
    locationSearch.addEventListener('input', () => {
        filterLocationOptions(locationSearch.value);
    });
    
    locationSearch.addEventListener('keydown', (e) => {
        if (e.key === 'Backspace' && locationSearch.value === '' && selectedLocation) {
            removeLocation();
        } else if (e.key === 'Escape') {
            locationContainer.classList.remove('open');
            locationContainer.classList.remove('focus');
            locationSearch.blur();
            e.stopPropagation();
        }
    });

    // ----------------- WORK SHIFTS EDITOR CONTROLLER -----------------
    const hoursContainer = document.getElementById('emp-hours-container');
    const hiddenHoursInput = document.getElementById('emp-hours');
    
    let employeeShifts = []; // array of { start: "", end: "" }
    
    function generateTimeOptions() {
        const options = [];
        for (let h = 0; h < 24; h++) {
            const hStr = h.toString().padStart(2, '0');
            options.push(`${hStr}:00`);
            options.push(`${hStr}:30`);
        }
        options.push(`24:00`); // Allow shifts ending at midnight
        return options;
    }
    const availableTimes = generateTimeOptions();
    
    function parseEmployeeHours(hoursStr) {
        if (!hoursStr) return [{ start: "", end: "" }];
        const parts = hoursStr.split(',').map(p => p.trim());
        const shifts = [];
        
        parts.forEach(part => {
            const range = part.split('-').map(r => r.trim());
            if (range.length === 2) {
                shifts.push({ start: range[0], end: range[1] });
            }
        });
        
        if (shifts.length === 0) {
            return [{ start: "", end: "" }];
        }
        return shifts;
    }
    
    function renderShiftsList() {
        const listContainer = document.getElementById('emp-shifts-list');
        listContainer.innerHTML = "";
        
        employeeShifts.forEach((shift, index) => {
            const row = document.createElement('div');
            row.className = 'shift-row mb-2';
            row.dataset.index = index;
            
            row.innerHTML = `
                <div class="time-range-picker" style="width: 100%;">
                    <div class="time-picker-item" style="flex: 1;">
                        <div class="multi-select-container" id="emp-hours-start-container-${index}">
                            <div class="multi-select-selected" id="emp-hours-start-selected-${index}">
                                <input type="text" id="emp-hours-start-search-${index}" class="multi-select-search-input" placeholder="Start..." autocomplete="off">
                                <div class="multi-select-arrow" id="emp-hours-start-toggle-${index}">
                                    <i data-lucide="chevron-down"></i>
                                </div>
                            </div>
                            <div class="multi-select-dropdown" id="emp-hours-start-dropdown-${index}">
                            </div>
                        </div>
                    </div>
                    <div class="time-picker-separator" style="margin-top: 0;">to</div>
                    <div class="time-picker-item" style="flex: 1;">
                        <div class="multi-select-container" id="emp-hours-end-container-${index}">
                            <div class="multi-select-selected" id="emp-hours-end-selected-${index}">
                                <input type="text" id="emp-hours-end-search-${index}" class="multi-select-search-input" placeholder="End..." autocomplete="off">
                                <div class="multi-select-arrow" id="emp-hours-end-toggle-${index}">
                                    <i data-lucide="chevron-down"></i>
                                </div>
                            </div>
                            <div class="multi-select-dropdown" id="emp-hours-end-dropdown-${index}">
                            </div>
                        </div>
                    </div>
                    ${employeeShifts.length > 1 ? `
                    <button type="button" class="btn-remove-shift btn-icon" data-index="${index}" style="background: transparent; border: none; color: var(--text-muted); cursor: pointer; padding: 4px 8px; font-size: 1.25rem; transition: color var(--transition-speed) ease; margin-left: 4px;">
                        &times;
                    </button>
                    ` : '<div style="width: 28px;"></div>'}
                </div>
            `;
            listContainer.appendChild(row);
            
            // Populate Start Dropdown
            const startDropdown = document.getElementById(`emp-hours-start-dropdown-${index}`);
            startDropdown.innerHTML = availableTimes.map(time =>
                `<div class="multi-select-option" data-value="${time}">${time}</div>`
            ).join('');
            
            // Populate End Dropdown
            const endDropdown = document.getElementById(`emp-hours-end-dropdown-${index}`);
            endDropdown.innerHTML = availableTimes.map(time =>
                `<div class="multi-select-option" data-value="${time}">${time}</div>`
            ).join('');
            
            // Bind listeners for this row
            bindShiftRowListeners(index);
            
            // Update chips UI
            updateRowUI(index);
        });
        
        // Re-run lucide icons if there are icons in rows
        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }
    }
    
    function rowElement(index) {
        return document.querySelector(`.shift-row[data-index="${index}"]`);
    }
    
    function closeAllShiftDropdowns() {
        document.querySelectorAll('.shift-row .multi-select-container').forEach(c => {
            c.classList.remove('open');
            c.classList.remove('focus');
        });
    }
    
    function filterRowOptions(dropdown, query) {
        const q = query.toLowerCase().trim();
        const options = dropdown.querySelectorAll('.multi-select-option');
        let visibleCount = 0;
        
        options.forEach(opt => {
            const val = opt.getAttribute('data-value').toLowerCase();
            if (val.includes(q)) {
                opt.classList.remove('hidden');
                visibleCount++;
            } else {
                opt.classList.add('hidden');
            }
        });
        
        const container = dropdown.closest('.multi-select-container');
        if (visibleCount > 0 && container.classList.contains('focus')) {
            container.classList.add('open');
        } else {
            container.classList.remove('open');
        }
    }
    
    function bindShiftRowListeners(index) {
        const startContainer = document.getElementById(`emp-hours-start-container-${index}`);
        const startSelected = document.getElementById(`emp-hours-start-selected-${index}`);
        const startSearch = document.getElementById(`emp-hours-start-search-${index}`);
        const startDropdown = document.getElementById(`emp-hours-start-dropdown-${index}`);
        
        const endContainer = document.getElementById(`emp-hours-end-container-${index}`);
        const endSelected = document.getElementById(`emp-hours-end-selected-${index}`);
        const endSearch = document.getElementById(`emp-hours-end-search-${index}`);
        const endDropdown = document.getElementById(`emp-hours-end-dropdown-${index}`);
        
        // Start select event
        startDropdown.querySelectorAll('.multi-select-option').forEach(opt => {
            opt.addEventListener('click', (e) => {
                e.stopPropagation();
                const val = opt.getAttribute('data-value');
                employeeShifts[index].start = val;
                updateRowUI(index);
                validateAndSyncShifts();
                startContainer.classList.remove('open');
                startContainer.classList.remove('focus');
                startSearch.blur();
                startSearch.value = "";
                filterRowOptions(startDropdown, "");
            });
        });
        
        // End select event
        endDropdown.querySelectorAll('.multi-select-option').forEach(opt => {
            opt.addEventListener('click', (e) => {
                e.stopPropagation();
                const val = opt.getAttribute('data-value');
                employeeShifts[index].end = val;
                updateRowUI(index);
                validateAndSyncShifts();
                endContainer.classList.remove('open');
                endContainer.classList.remove('focus');
                endSearch.blur();
                endSearch.value = "";
                filterRowOptions(endDropdown, "");
            });
        });
        
        // Start Click / Toggle
        startSelected.addEventListener('click', (e) => {
            if (e.target === startSearch) return;
            e.stopPropagation();
            const isOpen = startContainer.classList.contains('open');
            closeAllShiftDropdowns();
            if (!isOpen) {
                startContainer.classList.add('focus');
                startContainer.classList.add('open');
                startSearch.focus();
                filterRowOptions(startDropdown, startSearch.value);
            }
        });
        
        const startToggle = document.getElementById(`emp-hours-start-toggle-${index}`);
        startToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            const isOpen = startContainer.classList.contains('open');
            closeAllShiftDropdowns();
            if (!isOpen) {
                startContainer.classList.add('focus');
                startContainer.classList.add('open');
                startSearch.focus();
                filterRowOptions(startDropdown, startSearch.value);
            }
        });
        
        startSearch.addEventListener('focus', () => {
            const isOpen = startContainer.classList.contains('open');
            if (!isOpen) {
                closeAllShiftDropdowns();
                startContainer.classList.add('focus');
                startContainer.classList.add('open');
            }
            filterRowOptions(startDropdown, startSearch.value);
        });
        
        startSearch.addEventListener('input', () => {
            const val = startSearch.value.trim();
            if (val.includes('-')) {
                const parts = val.split('-').map(p => p.trim());
                if (parts.length === 2) {
                    employeeShifts[index].start = parts[0];
                    employeeShifts[index].end = parts[1];
                    updateRowUI(index);
                    validateAndSyncShifts();
                    return;
                }
            }
            if (availableTimes.includes(val) || /^\d{1,2}:\d{2}$/.test(val)) {
                employeeShifts[index].start = val;
                validateAndSyncShifts();
            }
            filterRowOptions(startDropdown, val);
        });

        startSearch.addEventListener('blur', () => {
            const val = startSearch.value.trim();
            if (val && (availableTimes.includes(val) || /^\d{1,2}:\d{2}$/.test(val))) {
                employeeShifts[index].start = val;
                updateRowUI(index);
                validateAndSyncShifts();
            }
        });
        
        startSearch.addEventListener('keydown', (e) => {
            if (e.key === 'Backspace' && startSearch.value === '' && employeeShifts[index].start) {
                employeeShifts[index].start = "";
                updateRowUI(index);
                validateAndSyncShifts();
                startSearch.focus();
            } else if (e.key === 'Escape') {
                startContainer.classList.remove('open');
                startContainer.classList.remove('focus');
                startSearch.blur();
                e.stopPropagation();
            }
        });
        
        // End Click / Toggle
        endSelected.addEventListener('click', (e) => {
            if (e.target === endSearch) return;
            e.stopPropagation();
            const isOpen = endContainer.classList.contains('open');
            closeAllShiftDropdowns();
            if (!isOpen) {
                endContainer.classList.add('focus');
                endContainer.classList.add('open');
                endSearch.focus();
                filterRowOptions(endDropdown, endSearch.value);
            }
        });
        
        const endToggle = document.getElementById(`emp-hours-end-toggle-${index}`);
        endToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            const isOpen = endContainer.classList.contains('open');
            closeAllShiftDropdowns();
            if (!isOpen) {
                endContainer.classList.add('focus');
                endContainer.classList.add('open');
                endSearch.focus();
                filterRowOptions(endDropdown, endSearch.value);
            }
        });
        
        endSearch.addEventListener('focus', () => {
            const isOpen = endContainer.classList.contains('open');
            if (!isOpen) {
                closeAllShiftDropdowns();
                endContainer.classList.add('focus');
                endContainer.classList.add('open');
            }
            filterRowOptions(endDropdown, endSearch.value);
        });
        
        endSearch.addEventListener('input', () => {
            const val = endSearch.value.trim();
            if (availableTimes.includes(val) || /^\d{1,2}:\d{2}$/.test(val)) {
                employeeShifts[index].end = val;
                validateAndSyncShifts();
            }
            filterRowOptions(endDropdown, val);
        });

        endSearch.addEventListener('blur', () => {
            const val = endSearch.value.trim();
            if (val && (availableTimes.includes(val) || /^\d{1,2}:\d{2}$/.test(val))) {
                employeeShifts[index].end = val;
                updateRowUI(index);
                validateAndSyncShifts();
            }
        });
        
        endSearch.addEventListener('keydown', (e) => {
            if (e.key === 'Backspace' && endSearch.value === '' && employeeShifts[index].end) {
                employeeShifts[index].end = "";
                updateRowUI(index);
                validateAndSyncShifts();
                endSearch.focus();
            } else if (e.key === 'Escape') {
                endContainer.classList.remove('open');
                endContainer.classList.remove('focus');
                endSearch.blur();
                e.stopPropagation();
            }
        });
        
        // Remove button click listener
        const rowEl = rowElement(index);
        if (rowEl) {
            const removeBtn = rowEl.querySelector('.btn-remove-shift');
            if (removeBtn) {
                removeBtn.addEventListener('click', () => {
                    removeShiftRow(index);
                });
            }
        }
    }
    
    function removeShiftRow(index) {
        employeeShifts.splice(index, 1);
        renderShiftsList();
        validateAndSyncShifts();
    }
    
    function updateRowUI(index) {
        const shift = employeeShifts[index];
        const startSelected = document.getElementById(`emp-hours-start-selected-${index}`);
        const startSearch = document.getElementById(`emp-hours-start-search-${index}`);
        const startDropdown = document.getElementById(`emp-hours-start-dropdown-${index}`);
        
        const endSelected = document.getElementById(`emp-hours-end-selected-${index}`);
        const endSearch = document.getElementById(`emp-hours-end-search-${index}`);
        const endDropdown = document.getElementById(`emp-hours-end-dropdown-${index}`);
        
        if (!startSelected || !endSelected) return;

        // Update Start UI
        const startChips = startSelected.querySelectorAll('.chip');
        startChips.forEach(c => c.remove());
        if (shift.start) {
            const chip = document.createElement('span');
            chip.className = 'chip';
            chip.dataset.value = shift.start;
            chip.innerHTML = `${shift.start} <button type="button" class="chip-remove" data-value="${shift.start}">&times;</button>`;
            startSelected.insertBefore(chip, startSearch);
            startSearch.placeholder = "";
            
            chip.querySelector('.chip-remove').addEventListener('click', (e) => {
                e.stopPropagation();
                shift.start = "";
                updateRowUI(index);
                validateAndSyncShifts();
                startSearch.focus();
            });
        } else {
            startSearch.placeholder = "Start...";
        }
        
        const startOpts = startDropdown.querySelectorAll('.multi-select-option');
        startOpts.forEach(opt => {
            const val = opt.getAttribute('data-value');
            if (val === shift.start) {
                opt.classList.add('selected');
            } else {
                opt.classList.remove('selected');
            }
        });
        
        // Update End UI
        const endChips = endSelected.querySelectorAll('.chip');
        endChips.forEach(c => c.remove());
        if (shift.end) {
            const chip = document.createElement('span');
            chip.className = 'chip';
            chip.dataset.value = shift.end;
            chip.innerHTML = `${shift.end} <button type="button" class="chip-remove" data-value="${shift.end}">&times;</button>`;
            endSelected.insertBefore(chip, endSearch);
            endSearch.placeholder = "";
            
            chip.querySelector('.chip-remove').addEventListener('click', (e) => {
                e.stopPropagation();
                shift.end = "";
                updateRowUI(index);
                validateAndSyncShifts();
                endSearch.focus();
            });
        } else {
            endSearch.placeholder = "End...";
        }
        
        const endOpts = endDropdown.querySelectorAll('.multi-select-option');
        endOpts.forEach(opt => {
            const val = opt.getAttribute('data-value');
            if (val === shift.end) {
                opt.classList.add('selected');
            } else {
                opt.classList.remove('selected');
            }
        });
    }
    
    function validateAndSyncShifts() {
        let allValid = true;
        
        hoursContainer.classList.remove('is-invalid');
        employeeShifts.forEach((_, index) => {
            const row = rowElement(index);
            if (row) {
                row.querySelector('.time-range-picker').classList.remove('is-invalid');
            }
            // Auto sync from search inputs if typed directly
            const startInput = document.getElementById(`emp-hours-start-search-${index}`);
            const endInput = document.getElementById(`emp-hours-end-search-${index}`);
            if (startInput && startInput.value.trim()) {
                const val = startInput.value.trim();
                if (val.includes('-')) {
                    const parts = val.split('-').map(p => p.trim());
                    if (parts.length === 2) {
                        employeeShifts[index].start = parts[0];
                        employeeShifts[index].end = parts[1];
                    }
                } else if (availableTimes.includes(val) || /^\d{1,2}:\d{2}$/.test(val)) {
                    employeeShifts[index].start = val;
                }
            }
            if (endInput && endInput.value.trim()) {
                const val = endInput.value.trim();
                if (availableTimes.includes(val) || /^\d{1,2}:\d{2}$/.test(val)) {
                    employeeShifts[index].end = val;
                }
            }
        });
        
        if (employeeShifts.length === 0) {
            hiddenHoursInput.value = "";
            return false;
        }
        
        const ranges = [];
        
        for (let i = 0; i < employeeShifts.length; i++) {
            const shift = employeeShifts[i];
            if (!shift.start || !shift.end) {
                allValid = false;
                continue;
            }
            
            const [startH, startM] = shift.start.split(':').map(Number);
            const [endH, endM] = shift.end.split(':').map(Number);
            
            if (isNaN(startH) || isNaN(startM) || isNaN(endH) || isNaN(endM)) {
                allValid = false;
                const row = rowElement(i);
                if (row) {
                    row.querySelector('.time-range-picker').classList.add('is-invalid');
                }
                continue;
            }

            const startMinutes = startH * 60 + startM;
            const endMinutes = endH * 60 + endM;
            
            // Allow overnight shifts (start time > end time), but not identical
            if (endMinutes === startMinutes) {
                allValid = false;
                const row = rowElement(i);
                if (row) {
                    row.querySelector('.time-range-picker').classList.add('is-invalid');
                }
            } else {
                ranges.push(`${shift.start} - ${shift.end}`);
            }
        }
        
        if (allValid && ranges.length === employeeShifts.length) {
            hiddenHoursInput.value = ranges.join(', ');
            hoursContainer.classList.remove('is-invalid');
            return true;
        } else {
            hiddenHoursInput.value = "";
            return false;
        }
    }
    
    function hasOverlappingShifts() {
        const intervals = [];
        for (let i = 0; i < employeeShifts.length; i++) {
            const shift = employeeShifts[i];
            if (!shift.start || !shift.end) continue;
            
            const [startH, startM] = shift.start.split(':').map(Number);
            const [endH, endM] = shift.end.split(':').map(Number);
            
            const startMin = startH * 60 + startM;
            const endMin = endH * 60 + endM;
            
            if (startMin < endMin) {
                intervals.push({ start: startMin, end: endMin, index: i });
            } else if (startMin > endMin) {
                // Crosses midnight: split into two calendar-day intervals
                intervals.push({ start: 0, end: endMin, index: i });
                intervals.push({ start: startMin, end: 1440, index: i });
            }
        }
        
        for (let i = 0; i < intervals.length; i++) {
            for (let j = i + 1; j < intervals.length; j++) {
                const int1 = intervals[i];
                const int2 = intervals[j];
                
                if (int1.index !== int2.index) {
                    if (int1.start < int2.end && int2.start < int1.end) {
                        return true;
                    }
                }
            }
        }
        return false;
    }
    
    // Add Another Shift button click listener
    document.getElementById('btn-add-shift').addEventListener('click', () => {
        employeeShifts.push({ start: "", end: "" });
        renderShiftsList();
        validateAndSyncShifts();
    });
    
    // Close dropdowns on clicking outside
    document.addEventListener('click', (e) => {
        employeeShifts.forEach((_, index) => {
            const startContainer = document.getElementById(`emp-hours-start-container-${index}`);
            if (startContainer && !startContainer.contains(e.target)) {
                startContainer.classList.remove('open');
                startContainer.classList.remove('focus');
            }
            const endContainer = document.getElementById(`emp-hours-end-container-${index}`);
            if (endContainer && !endContainer.contains(e.target)) {
                endContainer.classList.remove('open');
                endContainer.classList.remove('focus');
            }
        });
    });

    function renderFormDropdowns() {
        // Populate Unit options
        const unitDropdown = document.getElementById('emp-unit-dropdown');
        unitDropdown.innerHTML = configUnits.map(unit => 
            `<div class="multi-select-option" data-value="${unit}">${unit}</div>`
        ).join('');
        
        // Populate Roles options
        const rolesDropdown = document.getElementById('emp-roles-dropdown');
        rolesDropdown.innerHTML = configRoles.map(role => 
            `<div class="multi-select-option" data-value="${role}">${role}</div>`
        ).join('');
        
        // Populate Conditions options (driven by configConditions)
        const conditionsDropdown = document.getElementById('emp-conditions-dropdown');
        conditionsDropdown.innerHTML = `<div class="multi-select-option" data-value="__NONE__" style="font-style: italic; border-bottom: 1px dashed var(--border-color); color: var(--text-secondary);">None (Clear All / Blank)</div>` +
        configConditions.map(cond =>
            `<div class="multi-select-option" data-value="${cond}">${cond}</div>`
        ).join('');
        
        // Populate Location options
        const locationDropdown = document.getElementById('emp-location-dropdown');
        locationDropdown.innerHTML = ["Office", "Home"].map(loc => 
            `<div class="multi-select-option" data-value="${loc}">${loc}</div>`
        ).join('');
        
        // Bind click selection listeners dynamically
        attachDropdownOptionListeners();
    }
    
    function attachDropdownOptionListeners() {
        const unitDropdown = document.getElementById('emp-unit-dropdown');
        unitDropdown.querySelectorAll('.multi-select-option').forEach(opt => {
            opt.addEventListener('click', (e) => {
                e.stopPropagation();
                const val = opt.getAttribute('data-value');
                if (selectedUnits.includes(val)) {
                    removeUnit(val);
                } else {
                    addUnit(val);
                }
                unitSearch.focus();
            });
        });
        
        const rolesDropdown = document.getElementById('emp-roles-dropdown');
        rolesDropdown.querySelectorAll('.multi-select-option').forEach(opt => {
            opt.addEventListener('click', (e) => {
                e.stopPropagation();
                const val = opt.getAttribute('data-value');
                if (selectedRoles.includes(val)) {
                    removeRole(val);
                } else {
                    addRole(val);
                }
                rolesSearch.focus();
            });
        });
        
        const conditionsDropdown = document.getElementById('emp-conditions-dropdown');
        conditionsDropdown.querySelectorAll('.multi-select-option').forEach(opt => {
            opt.addEventListener('click', (e) => {
                e.stopPropagation();
                const val = opt.getAttribute('data-value');
                if (val === '__NONE__' || val === '') {
                    selectedConditions = [];
                    updateConditionsUI();
                } else if (selectedConditions.includes(val)) {
                    removeCondition(val);
                } else {
                    addCondition(val);
                }
                conditionsSearch.focus();
            });
        });
        
        const locationDropdown = document.getElementById('emp-location-dropdown');
        locationDropdown.querySelectorAll('.multi-select-option').forEach(opt => {
            opt.addEventListener('click', (e) => {
                e.stopPropagation();
                const val = opt.getAttribute('data-value');
                selectLocation(val);
            });
        });

        const supervisorDropdown = document.getElementById('emp-supervisor-dropdown');
        supervisorDropdown.querySelectorAll('.multi-select-option').forEach(opt => {
            opt.addEventListener('click', (e) => {
                e.stopPropagation();
                const val = opt.getAttribute('data-value');
                selectSupervisor(val ? parseInt(val) : null);
            });
        });

        // Search input binding for Reports To supervisor search
        const supervisorSearch = document.getElementById('emp-supervisor-search');
        const supervisorContainer = document.getElementById('emp-supervisor-container');
        const supervisorToggle = document.getElementById('emp-supervisor-toggle');

        if (supervisorSearch && supervisorDropdown && supervisorContainer) {
            supervisorSearch.addEventListener('input', () => {
                const query = supervisorSearch.value.toLowerCase();
                supervisorDropdown.classList.add('active');
                supervisorContainer.classList.add('active');

                supervisorDropdown.querySelectorAll('.multi-select-option').forEach(opt => {
                    const text = opt.innerText.toLowerCase();
                    if (text.includes(query)) {
                        opt.style.display = 'flex';
                    } else {
                        opt.style.display = 'none';
                    }
                });
            });

            supervisorSearch.addEventListener('focus', () => {
                supervisorDropdown.classList.add('active');
                supervisorContainer.classList.add('active');
            });
        }

        if (supervisorToggle && supervisorDropdown && supervisorContainer) {
            supervisorToggle.addEventListener('click', (e) => {
                e.stopPropagation();
                supervisorDropdown.classList.toggle('active');
                supervisorContainer.classList.toggle('active');
            });
        }
    }

    // Reports To supervisor selection state & handlers
    let selectedSupervisors = [];

    const supervisorContainer = document.getElementById('emp-supervisor-container');
    const supervisorSelected = document.getElementById('emp-supervisor-selected');
    const supervisorSearch = document.getElementById('emp-supervisor-search');
    const supervisorToggle = document.getElementById('emp-supervisor-toggle');
    const supervisorDropdown = document.getElementById('emp-supervisor-dropdown');

    function filterSupervisorOptions(query) {
        if (!supervisorDropdown) return;
        const q = query.toLowerCase().trim();
        const options = supervisorDropdown.querySelectorAll('.multi-select-option');
        let visibleCount = 0;

        options.forEach(opt => {
            const text = opt.innerText.toLowerCase();
            if (text.includes(q)) {
                opt.style.display = 'flex';
                visibleCount++;
            } else {
                opt.style.display = 'none';
            }
        });

        if (visibleCount > 0 && document.activeElement === supervisorSearch && supervisorContainer) {
            supervisorContainer.classList.add('open');
        }
    }

    if (supervisorSelected && supervisorContainer && supervisorSearch) {
        supervisorSelected.addEventListener('click', (e) => {
            if (e.target === supervisorSearch || e.target.closest('.chip-remove')) return;
            e.stopPropagation();

            const isOpen = supervisorContainer.classList.contains('open');
            if (isOpen) {
                supervisorContainer.classList.remove('open');
                supervisorContainer.classList.remove('focus');
                supervisorSearch.blur();
            } else {
                supervisorContainer.classList.add('focus');
                supervisorContainer.classList.add('open');
                supervisorSearch.focus();
                filterSupervisorOptions(supervisorSearch.value);
            }
        });

        if (supervisorToggle) {
            supervisorToggle.addEventListener('click', (e) => {
                e.stopPropagation();
                const isOpen = supervisorContainer.classList.contains('open');
                if (isOpen) {
                    supervisorContainer.classList.remove('open');
                    supervisorContainer.classList.remove('focus');
                    supervisorSearch.blur();
                } else {
                    supervisorContainer.classList.add('focus');
                    supervisorContainer.classList.add('open');
                    supervisorSearch.focus();
                    filterSupervisorOptions(supervisorSearch.value);
                }
            });
        }

        supervisorSearch.addEventListener('focus', () => {
            supervisorContainer.classList.add('focus');
            supervisorContainer.classList.add('open');
            filterSupervisorOptions(supervisorSearch.value);
        });

        supervisorSearch.addEventListener('input', () => {
            filterSupervisorOptions(supervisorSearch.value);
        });

        supervisorSearch.addEventListener('keydown', (e) => {
            if (e.key === 'Backspace' && supervisorSearch.value === '' && selectedSupervisors.length > 0) {
                removeSupervisor(selectedSupervisors[selectedSupervisors.length - 1]);
            }
        });

        document.addEventListener('click', (e) => {
            if (supervisorContainer && !supervisorContainer.contains(e.target)) {
                supervisorContainer.classList.remove('open');
                supervisorContainer.classList.remove('focus');
            }
        });
    }

    function renderSupervisorDropdownOptions(excludeEmpId = null) {
        const dropdown = document.getElementById('emp-supervisor-dropdown');
        if (!dropdown) return;

        dropdown.innerHTML = '';

        if (!employeesData || !employeesData.employees) {
            dropdown.innerHTML = '<div class="text-rose small p-3 text-center">Failed to load Leaders list. Please try refreshing.</div>';
            return;
        }

        // Include ONLY employees who currently have the Leader role
        const leadersOnly = employeesData.employees.filter(emp =>
            Array.isArray(emp.roles) && emp.roles.includes('Leader')
        );

        // Exclude current employee if editing an existing employee
        const availableLeaders = leadersOnly.filter(emp =>
            !(excludeEmpId && parseInt(emp.id) === parseInt(excludeEmpId))
        );

        if (availableLeaders.length === 0) {
            const emptyNotice = document.createElement('div');
            emptyNotice.className = 'text-secondary small p-3 text-center';
            emptyNotice.innerHTML = 'No employees currently have the Leader role.';
            dropdown.appendChild(emptyNotice);
        } else {
            availableLeaders.forEach(emp => {
                const unitStr = Array.isArray(emp.unit) ? emp.unit.join(', ') : emp.unit;
                const opt = document.createElement('div');
                opt.className = 'multi-select-option';
                opt.setAttribute('data-value', emp.id);
                opt.style.display = 'flex';
                opt.style.justifyContent = 'space-between';
                opt.style.alignItems = 'center';
                opt.style.padding = '10px 14px';
                opt.innerHTML = `
                    <div style="display: flex; flex-direction: column; gap: 2px;">
                        <span class="font-semibold" style="font-size: 0.9rem; color: var(--text-primary);">${emp.name}</span>
                        <span class="text-secondary small">${unitStr}</span>
                    </div>
                `;
                dropdown.appendChild(opt);
            });
        }

        lucide.createIcons();

        // Re-bind click handlers
        dropdown.querySelectorAll('.multi-select-option').forEach(opt => {
            opt.addEventListener('click', (e) => {
                e.stopPropagation();
                const val = opt.getAttribute('data-value');
                if (val) {
                    const id = parseInt(val);
                    if (selectedSupervisors.includes(id)) {
                        removeSupervisor(id);
                    } else {
                        addSupervisor(id);
                    }
                }
            });
        });
    }

    function addSupervisor(supId) {
        if (!selectedSupervisors.includes(supId)) {
            selectedSupervisors.push(supId);
            updateSupervisorUI();
        }
        supervisorSearch.value = '';
        filterSupervisorOptions('');
    }

    function removeSupervisor(supId) {
        selectedSupervisors = selectedSupervisors.filter(id => id !== supId);
        updateSupervisorUI();
        supervisorSearch.value = '';
        filterSupervisorOptions('');
    }

    function updateSupervisorUI() {
        const inputHidden = document.getElementById('emp-supervisor');
        if (!inputHidden || !supervisorSelected) return;

        // Clear old chips
        const chips = supervisorSelected.querySelectorAll('.chip');
        chips.forEach(c => c.remove());

        // Add new chips
        selectedSupervisors.forEach(supId => {
            const sup = employeesData.employees.find(e => parseInt(e.id) === parseInt(supId));
            if (sup) {
                const chip = document.createElement('span');
                chip.className = 'chip';
                chip.dataset.value = supId;
                chip.innerHTML = `${sup.name} <button type="button" class="chip-remove" data-value="${supId}">&times;</button>`;
                supervisorSelected.insertBefore(chip, supervisorSearch);
            }
        });

        // Chip removal listener
        supervisorSelected.querySelectorAll('.chip-remove').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const val = btn.getAttribute('data-value');
                removeSupervisor(parseInt(val));
            });
        });

        // Update dropdown checkmark states
        if (supervisorDropdown) {
            const options = supervisorDropdown.querySelectorAll('.multi-select-option');
            options.forEach(opt => {
                const val = opt.getAttribute('data-value');
                if (val && selectedSupervisors.includes(parseInt(val))) {
                    opt.classList.add('selected');
                } else {
                    opt.classList.remove('selected');
                }
            });
        }

        // Sync hidden value
        inputHidden.value = selectedSupervisors.length > 0 ? JSON.stringify(selectedSupervisors) : '';
    }

    // Helper to check circular reporting chains in JS supporting multiple supervisors
    function checkJsReportingCycle(employees, empId, targetSupervisorIds) {
        if (!targetSupervisorIds || !empId) return false;
        
        let idsToCheck = [];
        if (Array.isArray(targetSupervisorIds)) {
            idsToCheck = targetSupervisorIds.map(x => parseInt(x));
        } else {
            idsToCheck = [parseInt(targetSupervisorIds)];
        }

        const map = {};
        employees.forEach(e => map[e.id] = e);

        for (let startId of idsToCheck) {
            const visited = new Set();
            const queue = [startId];
            while (queue.length > 0) {
                const curr = queue.shift();
                if (parseInt(curr) === parseInt(empId)) return true;
                if (visited.has(curr)) continue;
                visited.add(curr);

                const sup = map[curr];
                if (sup) {
                    const sups = sup.reportsTo || sup.reports_to || [];
                    if (Array.isArray(sups)) {
                        sups.forEach(s => {
                            if (s !== null && s !== undefined) queue.push(parseInt(s));
                        });
                    } else {
                        queue.push(parseInt(sups));
                    }
                }
            }
        }
        return false;
    }

    // ----------------- SUB-TABS NAVIGATION CONTROLLER (CONFIGS) -----------------
    document.querySelectorAll('.sub-tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.sub-tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.sub-tab-pane').forEach(p => p.style.display = 'none');
            
            btn.classList.add('active');
            const target = btn.getAttribute('data-sub-tab');
            document.getElementById(`sub-tab-${target}`).style.display = 'block';
            
            if (target === 'units') {
                renderUnitsManagementList();
            } else if (target === 'roles') {
                renderRolesManagementList();
            } else if (target === 'conditions') {
                renderConditionsManagementList();
            }
        });
    });

    function renderUnitsManagementList() {
        const listContainer = document.getElementById('units-list');
        listContainer.innerHTML = '';
        
        if (configUnits.length === 0) {
            listContainer.innerHTML = '<div class="text-secondary text-center py-3">No units defined.</div>';
            return;
        }
        
        configUnits.forEach((unit, idx) => {
            const item = document.createElement('div');
            item.className = 'list-item-manage';
            item.setAttribute('draggable', 'true');
            item.setAttribute('data-index', idx);
            item.innerHTML = `
                <div class="list-item-left">
                    <span class="drag-handle"><i data-lucide="grip-vertical"></i></span>
                    <span class="list-item-text">${unit}</span>
                </div>
                <div class="list-item-actions">
                    <button type="button" class="btn btn-secondary btn-icon-only btn-rename-unit" data-value="${unit}" title="Rename Unit">
                        <i data-lucide="edit-2"></i>
                    </button>
                    <button type="button" class="btn btn-danger btn-icon-only btn-delete-unit" data-value="${unit}" title="Delete Unit">
                        <i data-lucide="trash-2"></i>
                    </button>
                </div>
            `;
            listContainer.appendChild(item);
        });
        
        lucide.createIcons();
        attachUnitsManagementListeners();
        setupDragAndDrop('units-list', configUnits, saveUnitsConfig);
    }
    
    function renderRolesManagementList() {
        const listContainer = document.getElementById('roles-list');
        listContainer.innerHTML = '';
        
        if (configRoles.length === 0) {
            listContainer.innerHTML = '<div class="text-secondary text-center py-3">No roles defined.</div>';
            return;
        }
        
        configRoles.forEach((role, idx) => {
            const item = document.createElement('div');
            item.className = 'list-item-manage';
            item.setAttribute('draggable', 'true');
            item.setAttribute('data-index', idx);
            item.innerHTML = `
                <div class="list-item-left">
                    <span class="drag-handle"><i data-lucide="grip-vertical"></i></span>
                    <span class="list-item-text">${role}</span>
                </div>
                <div class="list-item-actions">
                    <button type="button" class="btn btn-secondary btn-icon-only btn-rename-role" data-value="${role}" title="Rename Role">
                        <i data-lucide="edit-2"></i>
                    </button>
                    <button type="button" class="btn btn-danger btn-icon-only btn-delete-role" data-value="${role}" title="Delete Role">
                        <i data-lucide="trash-2"></i>
                    </button>
                </div>
            `;
            listContainer.appendChild(item);
        });
        
        lucide.createIcons();
        attachRolesManagementListeners();
        setupDragAndDrop('roles-list', configRoles, saveRolesConfig);
    }

    function setupDragAndDrop(listId, array, saveCallback) {
        const list = document.getElementById(listId);
        let dragSrcEl = null;
        
        const items = list.querySelectorAll('.list-item-manage');
        items.forEach(item => {
            item.addEventListener('dragstart', (e) => {
                dragSrcEl = item;
                item.classList.add('dragging');
                e.dataTransfer.effectAllowed = 'move';
                e.dataTransfer.setData('text/plain', item.getAttribute('data-index'));
            });
            
            item.addEventListener('dragend', () => {
                item.classList.remove('dragging');
                items.forEach(el => {
                    el.style.borderTop = '';
                    el.style.borderBottom = '';
                });
            });
            
            item.addEventListener('dragover', (e) => {
                e.preventDefault();
                e.dataTransfer.dropEffect = 'move';
                
                const rect = item.getBoundingClientRect();
                const relativeY = e.clientY - rect.top;
                if (relativeY < rect.height / 2) {
                    item.style.borderTop = '2px solid var(--primary)';
                    item.style.borderBottom = '';
                } else {
                    item.style.borderTop = '';
                    item.style.borderBottom = '2px solid var(--primary)';
                }
            });
            
            item.addEventListener('dragleave', () => {
                item.style.borderTop = '';
                item.style.borderBottom = '';
            });
            
            item.addEventListener('drop', (e) => {
                e.preventDefault();
                item.style.borderTop = '';
                item.style.borderBottom = '';
                
                const fromIdx = parseInt(e.dataTransfer.getData('text/plain'));
                const toIdx = parseInt(item.getAttribute('data-index'));
                
                if (fromIdx !== toIdx) {
                    const element = array.splice(fromIdx, 1)[0];
                    array.splice(toIdx, 0, element);
                    saveCallback();
                }
            });
        });
    }

    async function saveUnitsConfig() {
        const payload = { units: configUnits };
        const result = await apiRequest('/api/employees/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (result) {
            renderUnitsManagementList();
        }
    }
    
    document.getElementById('btn-add-unit').addEventListener('click', async () => {
        const cleanName = await showCustomPrompt({
            title: "Add Unit",
            description: "Enter a name for the new department/unit.",
            placeholder: "e.g. Broadcast",
            submitText: "Add Unit",
            existingItems: configUnits,
            itemType: "Unit"
        });
        if (!cleanName) return;

        configUnits.push(cleanName);
        await saveUnitsConfig();
    });

    function attachUnitsManagementListeners() {
        document.querySelectorAll('.btn-rename-unit').forEach(btn => {
            btn.addEventListener('click', async () => {
                const oldName = btn.getAttribute('data-value');
                const cleanName = await showCustomPrompt({
                    title: "Rename Unit",
                    description: `Enter a new name for unit "${oldName}":`,
                    defaultValue: oldName,
                    submitText: "Rename Unit",
                    existingItems: configUnits,
                    currentItem: oldName,
                    itemType: "Unit"
                });
                if (!cleanName || cleanName === oldName) return;

                configUnits = configUnits.map(u => u === oldName ? cleanName : u);

                let updatedCount = 0;
                for (const emp of employeesData.employees) {
                    if (Array.isArray(emp.unit) && emp.unit.includes(oldName)) {
                        emp.unit = emp.unit.map(u => u === oldName ? cleanName : u);
                        await apiRequest(`/api/employees/${encodeURIComponent(emp.name)}`, {
                            method: 'PUT',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(emp)
                        });
                        updatedCount++;
                    }
                }

                await saveUnitsConfig();
                if (updatedCount > 0) {
                    await showCustomAlert({ title: "Unit Renamed", message: `Unit renamed successfully! Updated ${updatedCount} employee profile(s).`, type: "success" });
                    loadEmployeesData();
                }
            });
        });

        document.querySelectorAll('.btn-delete-unit').forEach(btn => {
            btn.addEventListener('click', async () => {
                const name = btn.getAttribute('data-value');

                const assignedEmployees = employeesData.employees.filter(emp =>
                    Array.isArray(emp.unit) && emp.unit.includes(name)
                );

                let confirmed = false;
                if (assignedEmployees.length > 0) {
                    const empNames = assignedEmployees.map(e => e.name).join(', ');
                    confirmed = await showCustomConfirm({
                        title: "Delete Unit",
                        message: `Are you sure you want to delete unit <strong>"${name}"</strong>?`,
                        warning: `Warning: This unit is currently assigned to employee(s): <strong>${empNames}</strong>. Deleting it will remove this unit from their profiles.`,
                        confirmText: "Delete Unit",
                        isDanger: true
                    });
                    if (!confirmed) return;

                    for (const emp of assignedEmployees) {
                        emp.unit = emp.unit.filter(u => u !== name);
                        await apiRequest(`/api/employees/${encodeURIComponent(emp.name)}`, {
                            method: 'PUT',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(emp)
                        });
                    }
                    loadEmployeesData();
                } else {
                    confirmed = await showCustomConfirm({
                        title: "Delete Unit",
                        message: `Are you sure you want to delete unit <strong>"${name}"</strong>?`,
                        warning: "This action cannot be undone.",
                        confirmText: "Delete Unit",
                        isDanger: true
                    });
                    if (!confirmed) return;
                }

                configUnits = configUnits.filter(u => u !== name);
                await saveUnitsConfig();
            });
        });
    }

    async function saveRolesConfig() {
        const payload = { roles: configRoles };
        const result = await apiRequest('/api/employees/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (result) {
            renderRolesManagementList();
        }
    }
    
    document.getElementById('btn-add-role').addEventListener('click', async () => {
        const cleanName = await showCustomPrompt({
            title: "Add Role",
            description: "Enter a name for the new role option.",
            placeholder: "e.g. Leader",
            submitText: "Add Role",
            existingItems: configRoles,
            itemType: "Role"
        });
        if (!cleanName) return;

        configRoles.push(cleanName);
        await saveRolesConfig();
    });

    function attachRolesManagementListeners() {
        document.querySelectorAll('.btn-rename-role').forEach(btn => {
            btn.addEventListener('click', async () => {
                const oldName = btn.getAttribute('data-value');
                const cleanName = await showCustomPrompt({
                    title: "Rename Role",
                    description: `Enter a new name for role "${oldName}":`,
                    defaultValue: oldName,
                    submitText: "Rename Role",
                    existingItems: configRoles,
                    currentItem: oldName,
                    itemType: "Role"
                });
                if (!cleanName || cleanName === oldName) return;

                configRoles = configRoles.map(r => r === oldName ? cleanName : r);

                let updatedCount = 0;
                for (const emp of employeesData.employees) {
                    if (Array.isArray(emp.roles) && emp.roles.includes(oldName)) {
                        emp.roles = emp.roles.map(r => r === oldName ? cleanName : r);
                        await apiRequest(`/api/employees/${encodeURIComponent(emp.name)}`, {
                            method: 'PUT',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(emp)
                        });
                        updatedCount++;
                    }
                }

                await saveRolesConfig();
                if (updatedCount > 0) {
                    await showCustomAlert({ title: "Role Renamed", message: `Role renamed successfully! Updated ${updatedCount} employee profile(s).`, type: "success" });
                    loadEmployeesData();
                }
            });
        });

        document.querySelectorAll('.btn-delete-role').forEach(btn => {
            btn.addEventListener('click', async () => {
                const name = btn.getAttribute('data-value');

                const assignedEmployees = employeesData.employees.filter(emp =>
                    Array.isArray(emp.roles) && emp.roles.includes(name)
                );

                let confirmed = false;
                if (assignedEmployees.length > 0) {
                    const empNames = assignedEmployees.map(e => e.name).join(', ');
                    confirmed = await showCustomConfirm({
                        title: "Delete Role",
                        message: `Are you sure you want to delete role <strong>"${name}"</strong>?`,
                        warning: `Warning: This role is currently assigned to employee(s): <strong>${empNames}</strong>. Deleting it will remove this role from their profiles.`,
                        confirmText: "Delete Role",
                        isDanger: true
                    });
                    if (!confirmed) return;

                    for (const emp of assignedEmployees) {
                        emp.roles = emp.roles.filter(r => r !== name);
                        await apiRequest(`/api/employees/${encodeURIComponent(emp.name)}`, {
                            method: 'PUT',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(emp)
                        });
                    }
                    loadEmployeesData();
                } else {
                    confirmed = await showCustomConfirm({
                        title: "Delete Role",
                        message: `Are you sure you want to delete role <strong>"${name}"</strong>?`,
                        warning: "This action cannot be undone.",
                        confirmText: "Delete Role",
                        isDanger: true
                    });
                    if (!confirmed) return;
                }

                configRoles = configRoles.filter(r => r !== name);
                await saveRolesConfig();
            });
        });
    }

    // ----------------- SPECIAL CONDITIONS MANAGEMENT CONTROLLER -----------------
    function renderConditionsManagementList() {
        const listContainer = document.getElementById('conditions-list');
        listContainer.innerHTML = '';

        if (configConditions.length === 0) {
            listContainer.innerHTML = '<div class="text-secondary text-center py-3">No special conditions defined.</div>';
            return;
        }

        configConditions.forEach((cond, idx) => {
            const item = document.createElement('div');
            item.className = 'list-item-manage';
            item.setAttribute('draggable', 'true');
            item.setAttribute('data-index', idx);
            item.innerHTML = `
                <div class="list-item-left">
                    <span class="drag-handle"><i data-lucide="grip-vertical"></i></span>
                    <span class="list-item-text">${cond}</span>
                </div>
                <div class="list-item-actions">
                    <button type="button" class="btn btn-secondary btn-icon-only btn-rename-condition" data-value="${cond}" title="Rename Special Condition">
                        <i data-lucide="edit-2"></i>
                    </button>
                    <button type="button" class="btn btn-danger btn-icon-only btn-delete-condition" data-value="${cond}" title="Delete Special Condition">
                        <i data-lucide="trash-2"></i>
                    </button>
                </div>
            `;
            listContainer.appendChild(item);
        });

        lucide.createIcons();
        attachConditionsManagementListeners();
        setupDragAndDrop('conditions-list', configConditions, saveConditionsConfig);
    }

    async function saveConditionsConfig() {
        const payload = { special_conditions: configConditions };
        const result = await apiRequest('/api/employees/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (result) {
            renderConditionsManagementList();
        }
    }

    document.getElementById('btn-add-condition').addEventListener('click', async () => {
        const cleanName = await showCustomPrompt({
            title: "Add Special Condition",
            description: "Enter a name for the new special condition.",
            placeholder: "e.g. Night Shift",
            submitText: "Add Special Condition",
            existingItems: configConditions,
            itemType: "Special Condition"
        });
        if (!cleanName) return;

        configConditions.push(cleanName);
        await saveConditionsConfig();
    });

    function attachConditionsManagementListeners() {
        document.querySelectorAll('.btn-rename-condition').forEach(btn => {
            btn.addEventListener('click', async () => {
                const oldName = btn.getAttribute('data-value');
                const cleanName = await showCustomPrompt({
                    title: "Rename Special Condition",
                    description: `Enter a new name for condition "${oldName}":`,
                    defaultValue: oldName,
                    submitText: "Rename Condition",
                    existingItems: configConditions,
                    currentItem: oldName,
                    itemType: "Special Condition"
                });
                if (!cleanName || cleanName === oldName) return;

                configConditions = configConditions.map(c => c === oldName ? cleanName : c);

                // Cascade rename to all employees who have this condition assigned
                let updatedCount = 0;
                for (const emp of employeesData.employees) {
                    if (Array.isArray(emp.special_conditions) && emp.special_conditions.includes(oldName)) {
                        emp.special_conditions = emp.special_conditions.map(c => c === oldName ? cleanName : c);
                        await apiRequest(`/api/employees/${encodeURIComponent(emp.name)}`, {
                            method: 'PUT',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(emp)
                        });
                        updatedCount++;
                    }
                }

                await saveConditionsConfig();
                if (updatedCount > 0) {
                    await showCustomAlert({ title: "Condition Renamed", message: `Special Condition renamed successfully! Updated ${updatedCount} employee profile(s).`, type: "success" });
                    loadEmployeesData();
                }
            });
        });

        document.querySelectorAll('.btn-delete-condition').forEach(btn => {
            btn.addEventListener('click', async () => {
                const name = btn.getAttribute('data-value');

                const assignedEmployees = employeesData.employees.filter(emp =>
                    Array.isArray(emp.special_conditions) && emp.special_conditions.includes(name)
                );

                let confirmed = false;
                if (assignedEmployees.length > 0) {
                    const empNames = assignedEmployees.map(e => e.name).join(', ');
                    confirmed = await showCustomConfirm({
                        title: "Delete Special Condition",
                        message: `Are you sure you want to delete special condition <strong>"${name}"</strong>?`,
                        warning: `Warning: This condition is currently assigned to employee(s): <strong>${empNames}</strong>. Deleting it will remove this condition from their profiles.`,
                        confirmText: "Delete Condition",
                        isDanger: true
                    });
                    if (!confirmed) return;

                    for (const emp of assignedEmployees) {
                        emp.special_conditions = emp.special_conditions.filter(c => c !== name);
                        await apiRequest(`/api/employees/${encodeURIComponent(emp.name)}`, {
                            method: 'PUT',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(emp)
                        });
                    }
                    loadEmployeesData();
                } else {
                    confirmed = await showCustomConfirm({
                        title: "Delete Special Condition",
                        message: `Are you sure you want to delete special condition <strong>"${name}"</strong>?`,
                        warning: "This action cannot be undone.",
                        confirmText: "Delete Condition",
                        isDanger: true
                    });
                    if (!confirmed) return;
                }

                configConditions = configConditions.filter(c => c !== name);
                await saveConditionsConfig();
            });
        });
    }

    // ----------------- SUB-TABS NAVIGATION CONTROLLER (EMPLOYEES TAB) -----------------
    document.querySelectorAll('.emp-sub-tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.emp-sub-tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.emp-sub-pane').forEach(p => p.style.display = 'none');

            btn.classList.add('active');
            const target = btn.getAttribute('data-emp-sub-tab');
            document.getElementById(`emp-sub-pane-${target}`).style.display = 'block';

            if (target === 'hierarchy') {
                renderManagerHierarchy();
            } else if (target === 'leader') {
                renderLeaderDashboard();
            } else if (target === 'analytics') {
                renderEmployeePerformanceAnalytics();
            }
        });
    });

    // ----------------- RATINGS & PERFORMANCE ANALYTICS CONTROLLER -----------------
    let cachedAnalyticsData = null;

    async function renderEmployeePerformanceAnalytics() {
        const tbody = document.getElementById('analytics-table-body');
        const countStat = document.getElementById('analytics-total-past-month-reports');
        const selfStat = document.getElementById('analytics-avg-self-rating');
        const mgrStat = document.getElementById('analytics-avg-manager-rating');
        const overallStat = document.getElementById('analytics-combined-overall-avg');
        const searchInput = document.getElementById('analytics-search-input');

        if (!tbody) return;
        tbody.innerHTML = '<tr><td colspan="6" class="text-center text-secondary py-4"><i data-lucide="loader" class="spin mb-2"></i><br>Loading employee performance data...</td></tr>';
        if (typeof lucide !== 'undefined') lucide.createIcons();

        const data = await apiRequest('/api/analytics/employee-performance');
        if (!data || !data.employees) {
            tbody.innerHTML = '<tr><td colspan="6" class="text-center text-rose py-4">Failed to load performance analytics.</td></tr>';
            return;
        }

        cachedAnalyticsData = data.employees;

        // Compute top metric summary stats
        let totalPastMonthReports = 0;
        let sumSelf = 0, countSelf = 0;
        let sumMgr = 0, countMgr = 0;
        let sumOverall = 0, countOverall = 0;

        cachedAnalyticsData.forEach(emp => {
            totalPastMonthReports += emp.past_month_reports_count || 0;
            if (emp.avg_self_rating !== null) {
                sumSelf += emp.avg_self_rating;
                countSelf++;
            }
            if (emp.avg_manager_rating !== null) {
                sumMgr += emp.avg_manager_rating;
                countMgr++;
            }
            if (emp.combined_avg_rating !== null) {
                sumOverall += emp.combined_avg_rating;
                countOverall++;
            }
        });

        if (countStat) countStat.innerText = totalPastMonthReports;
        if (selfStat) selfStat.innerText = countSelf > 0 ? (sumSelf / countSelf).toFixed(1) + ' / 10' : '-';
        if (mgrStat) mgrStat.innerText = countMgr > 0 ? (sumMgr / countMgr).toFixed(1) + ' / 10' : '-';
        if (overallStat) overallStat.innerText = countOverall > 0 ? (sumOverall / countOverall).toFixed(1) + ' / 10' : '-';

        filterAndRenderAnalyticsTable();

        if (searchInput) {
            searchInput.oninput = () => filterAndRenderAnalyticsTable();
        }
    }

    function filterAndRenderAnalyticsTable() {
        const tbody = document.getElementById('analytics-table-body');
        const searchInput = document.getElementById('analytics-search-input');
        if (!tbody || !cachedAnalyticsData) return;

        const query = searchInput ? searchInput.value.toLowerCase().trim() : '';

        const filtered = cachedAnalyticsData.filter(emp => {
            const name = (emp.employee_name || '').toLowerCase();
            const unit = (emp.unit || '').toLowerCase();
            return name.includes(query) || unit.includes(query);
        });

        tbody.innerHTML = '';
        if (filtered.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" class="text-center text-secondary py-4">No matching employees found.</td></tr>';
            return;
        }

        filtered.forEach(emp => {
            const selfStr = emp.avg_self_rating !== null ? `<span class="badge badge-emerald">⭐️ ${emp.avg_self_rating} / 10</span>` : '<span class="text-secondary small">Not rated</span>';
            const mgrStr = emp.avg_manager_rating !== null ? `<span class="badge badge-amber">🏅 ${emp.avg_manager_rating} / 10</span>` : '<span class="text-secondary small">Not rated</span>';
            const combinedStr = emp.combined_avg_rating !== null ? `<span class="badge badge-primary font-bold" style="font-size: 0.9rem; padding: 4px 10px;">📈 ${emp.combined_avg_rating} / 10</span>` : '<span class="text-secondary small">-</span>';

            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td class="font-semibold">${emp.employee_name}</td>
                <td>${emp.unit}</td>
                <td><span class="badge badge-secondary font-semibold">${emp.past_month_reports_count} Reports</span></td>
                <td>${selfStr}</td>
                <td>${mgrStr}</td>
                <td>${combinedStr}</td>
            `;
            tbody.appendChild(tr);
        });

        if (typeof lucide !== 'undefined') lucide.createIcons();
    }

    // ----------------- MANAGER HIERARCHY CONTROLLER -----------------
    function renderManagerHierarchy() {
        const container = document.getElementById('hierarchy-tree-container');
        container.innerHTML = '';

        if (!employeesData || !employeesData.employees || employeesData.employees.length === 0) {
            container.innerHTML = '<div class="text-secondary text-center py-4">No employees registered yet.</div>';
            return;
        }

        const employees = employeesData.employees;
        const leaders = employees.filter(e => Array.isArray(e.roles) && e.roles.includes('Leader'));

        if (leaders.length === 0) {
            container.innerHTML = '<div class="text-secondary text-center py-4">No Leaders defined in the organization yet. Assign the "Leader" role to an employee to build the hierarchy.</div>';
            return;
        }

        leaders.forEach(leader => {
            const teamMembers = employees.filter(m => {
                const sups = m.reportsTo || m.reports_to || [];
                if (Array.isArray(sups)) {
                    return sups.map(x => parseInt(x)).includes(parseInt(leader.id));
                }
                return parseInt(sups) === parseInt(leader.id);
            });

            const card = document.createElement('div');
            card.className = 'hierarchy-card';
            card.setAttribute('data-leader-id', leader.id);

            const membersHtml = teamMembers.length === 0
                ? '<div class="text-secondary small py-2">No employees currently assigned to this Leader. Drag and drop team members here to assign.</div>'
                : teamMembers.map(m => `
                    <div class="hierarchy-member-item" draggable="true" data-emp-id="${m.id}">
                        <div class="flex items-center gap-2">
                            <i data-lucide="grip-vertical" class="text-secondary" style="width: 14px; cursor: grab;"></i>
                            <span class="font-semibold">${m.name}</span>
                            <span class="text-secondary small">(${Array.isArray(m.unit) ? m.unit.join(', ') : m.unit})</span>
                        </div>
                        <div class="flex items-center gap-2">
                            <select class="hierarchy-reassign-select" data-emp-id="${m.id}">
                                <option value="">Re-assign...</option>
                                ${leaders.map(l => `<option value="${l.id}" ${parseInt(l.id) === parseInt(leader.id) ? 'selected' : ''}>${l.name} (Leader)</option>`).join('')}
                                <option value="none">Unassigned / Top Level</option>
                            </select>
                        </div>
                    </div>
                `).join('');

            card.innerHTML = `
                <div class="hierarchy-leader-header">
                    <div class="flex items-center gap-2">
                        <span class="font-semibold" style="font-size: 1.05rem;">${leader.name}</span>
                        <span class="badge-leader">Leader</span>
                        ${leader.leader_shift ? `<span class="badge badge-amber" style="font-size:0.75rem; padding: 2px 8px;">${leader.leader_shift}</span>` : ''}
                        <span class="text-secondary small">(${Array.isArray(leader.unit) ? leader.unit.join(', ') : leader.unit})</span>
                    </div>
                    <span class="badge badge-primary">${teamMembers.length} Team Member(s)</span>
                </div>
                <div class="hierarchy-members-list">
                    ${membersHtml}
                </div>
            `;
            container.appendChild(card);

            // Drag & Drop event listeners on Leader card
            card.addEventListener('dragover', (e) => {
                e.preventDefault();
                card.classList.add('drag-over');
            });

            card.addEventListener('dragleave', () => {
                card.classList.remove('drag-over');
            });

            card.addEventListener('drop', async (e) => {
                e.preventDefault();
                card.classList.remove('drag-over');

                const empId = e.dataTransfer.getData('text/plain');
                if (!empId) return;

                const targetLeaderId = parseInt(leader.id);
                if (parseInt(empId) === targetLeaderId) {
                    await showCustomAlert({ title: "Assignment Error", message: "An employee cannot report to themselves.", type: "danger" });
                    return;
                }

                if (checkJsReportingCycle(employees, empId, targetLeaderId)) {
                    await showCustomAlert({ title: "Circular Reporting Error", message: "Circular reporting chain detected! Employee cannot report to a supervisor in their own downstream chain.", type: "danger" });
                    return;
                }

                const result = await apiRequest('/api/employees/reassign', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ employee_id: parseInt(empId), supervisor_id: targetLeaderId })
                });

                if (result) {
                    await loadEmployeesData();
                    renderManagerHierarchy();
                }
            });
        });

        lucide.createIcons();

        // Drag start listeners for team items
        container.querySelectorAll('.hierarchy-member-item').forEach(item => {
            item.addEventListener('dragstart', (e) => {
                item.classList.add('dragging');
                e.dataTransfer.setData('text/plain', item.getAttribute('data-emp-id'));
            });
            item.addEventListener('dragend', () => {
                item.classList.remove('dragging');
            });
        });

        // Re-assign dropdown change listeners
        container.querySelectorAll('.hierarchy-reassign-select').forEach(sel => {
            sel.addEventListener('change', async (e) => {
                const empId = parseInt(sel.getAttribute('data-emp-id'));
                const val = sel.value;
                const newSupId = val === 'none' || val === '' ? null : parseInt(val);

                if (newSupId !== null) {
                    if (newSupId === empId) {
                        await showCustomAlert({ title: "Assignment Error", message: "An employee cannot report to themselves.", type: "danger" });
                        renderManagerHierarchy();
                        return;
                    }
                    if (checkJsReportingCycle(employees, empId, newSupId)) {
                        await showCustomAlert({ title: "Circular Reporting Error", message: "Circular reporting chain detected! Employee cannot report to a supervisor in their own downstream chain.", type: "danger" });
                        renderManagerHierarchy();
                        return;
                    }
                }

                const result = await apiRequest('/api/employees/reassign', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ employee_id: empId, supervisor_id: newSupId })
                });

                if (result) {
                    await loadEmployeesData();
                    renderManagerHierarchy();
                }
            });
        });
    }

    // ----------------- LEADER DASHBOARD CONTROLLER -----------------
    async function renderLeaderDashboard() {
        const selector = document.getElementById('leader-selector');
        const container = document.getElementById('leader-team-reports-list');

        if (!employeesData || !employeesData.employees) return;

        const leaders = employeesData.employees.filter(e => Array.isArray(e.roles) && e.roles.includes('Leader'));

        selector.innerHTML = '';
        if (leaders.length === 0) {
            selector.innerHTML = '<option value="">No Leaders defined</option>';
            container.innerHTML = '<div class="text-secondary text-center py-4">No Leaders available.</div>';
            return;
        }

        leaders.forEach(l => {
            const opt = document.createElement('option');
            opt.value = l.id;
            opt.innerText = `${l.name} (${Array.isArray(l.unit) ? l.unit.join(', ') : l.unit})`;
            selector.appendChild(opt);
        });

        async function updateLeaderView() {
            await loadEmployeesData();
            const leaderId = parseInt(selector.value);
            const leader = leaders.find(l => parseInt(l.id) === leaderId);
            if (!leader) return;

            const teamMembers = (employeesData.employees || []).filter(m => 
                parseInt(m.reportsTo || m.reports_to) === leaderId || 
                String(m.reportsTo || m.reports_to) === String(leaderId) ||
                String(m.reportsTo || m.reports_to).toLowerCase() === String(leader.name).toLowerCase()
            );

            const reports = await apiRequest('/api/reports') || [];

            container.innerHTML = '';
            if (teamMembers.length === 0) {
                container.innerHTML = `<div class="text-secondary text-center py-4">No team members assigned to <strong>${leader.name}</strong>.</div>`;
                return;
            }

            teamMembers.forEach(member => {
                const mName = (member.name || '').toLowerCase();
                const mId = String(member.id);

                const memberReports = reports.filter(r => {
                    const empName = (r.data?.employee || r.employee || '').toLowerCase();
                    const empId = String(r.data?.employee_id || r.employee_id || '');
                    return empName === mName || (empId && empId === mId);
                });

                if (memberReports.length > 0) {
                    memberReports.forEach(r => {
                        const reportData = r.data || {};
                        const problems = reportData.problems || [];
                        const div = document.createElement('div');
                        div.className = 'report-card mb-3 p-3';
                        div.style.background = 'rgba(255, 255, 255, 0.02)';
                        div.style.border = '1px solid var(--border-color)';
                        div.style.borderRadius = '10px';

                        div.innerHTML = `
                            <div class="flex justify-between items-center mb-2">
                                <div class="flex items-center gap-2">
                                    <span class="font-semibold" style="font-size: 1rem;">${member.name}</span>
                                    <span class="badge badge-primary">${reportData.unit || (Array.isArray(member.unit) ? member.unit[0] : member.unit) || 'Unit'}</span>
                                </div>
                                <span class="text-secondary small">Date: ${reportData.date || r.submitted_at || '-'}</span>
                            </div>
                            <p class="small text-secondary mb-2">Work hours: ${reportData.work_hours || member.work_hours || '-'} | Location: ${reportData.work_location || member.work_location || '-'}</p>
                            <div class="text-secondary small mb-2">Logged Problems: <strong>${problems.length}</strong></div>
                        `;
                        container.appendChild(div);
                    });
                } else {
                    const div = document.createElement('div');
                    div.className = 'report-card mb-3 p-3';
                    div.style.background = 'rgba(255, 255, 255, 0.01)';
                    div.style.border = '1px dashed var(--border-color)';
                    div.style.borderRadius = '10px';

                    div.innerHTML = `
                        <div class="flex justify-between items-center">
                            <div class="flex items-center gap-2">
                                <span class="font-semibold" style="font-size: 1rem; color: var(--text-primary);">${member.name}</span>
                                <span class="badge badge-secondary">${Array.isArray(member.unit) ? member.unit.join(', ') : member.unit}</span>
                            </div>
                            <span class="text-secondary small" style="font-style: italic;">No report logged yet</span>
                        </div>
                    `;
                    container.appendChild(div);
                }
            });
            lucide.createIcons();
        }

        selector.onchange = updateLeaderView;
        updateLeaderView();
    }

    // Multi-Select Team Member Controller for Consolidated Leader Report
    let selectedConsolidatedMemberIds = [];
    let currentConsolidatedTeamMembers = [];

    function renderConsolidatedMembersDropdown(teamMembers) {
        currentConsolidatedTeamMembers = teamMembers || [];
        const dropdown = document.getElementById('consolidated-members-dropdown');
        if (!dropdown) return;

        dropdown.innerHTML = '';
        if (currentConsolidatedTeamMembers.length === 0) {
            dropdown.innerHTML = '<div class="text-secondary small p-3 text-center">No team members assigned to this Leader.</div>';
            return;
        }

        // Toggle All option
        const allSelected = selectedConsolidatedMemberIds.length === currentConsolidatedTeamMembers.length;
        const allOpt = document.createElement('div');
        allOpt.className = `multi-select-option ${allSelected ? 'selected' : ''}`;
        allOpt.setAttribute('data-value', '__ALL__');
        allOpt.style.fontWeight = '600';
        allOpt.style.borderBottom = '1px dashed var(--border-color)';
        allOpt.innerHTML = `<span>${allSelected ? 'Deselect All Team Members' : 'Select All Team Members'}</span>`;
        dropdown.appendChild(allOpt);

        // Individual options
        currentConsolidatedTeamMembers.forEach(m => {
            const isSel = selectedConsolidatedMemberIds.includes(String(m.id)) || selectedConsolidatedMemberIds.includes(m.name);
            const unitStr = Array.isArray(m.unit) ? m.unit.join(', ') : m.unit;
            const opt = document.createElement('div');
            opt.className = `multi-select-option ${isSel ? 'selected' : ''}`;
            opt.setAttribute('data-value', m.id);
            opt.style.display = 'flex';
            opt.style.justifyContent = 'space-between';
            opt.style.alignItems = 'center';
            opt.innerHTML = `
                <span class="font-semibold">${m.name}</span>
                <span class="text-secondary small">${unitStr}</span>
            `;
            dropdown.appendChild(opt);
        });

        // Re-bind option click handlers
        dropdown.querySelectorAll('.multi-select-option').forEach(opt => {
            opt.addEventListener('click', (e) => {
                e.stopPropagation();
                const val = opt.getAttribute('data-value');
                if (val === '__ALL__') {
                    if (selectedConsolidatedMemberIds.length === currentConsolidatedTeamMembers.length) {
                        selectedConsolidatedMemberIds = [];
                    } else {
                        selectedConsolidatedMemberIds = currentConsolidatedTeamMembers.map(m => String(m.id));
                    }
                } else {
                    const strVal = String(val);
                    if (selectedConsolidatedMemberIds.includes(strVal)) {
                        selectedConsolidatedMemberIds = selectedConsolidatedMemberIds.filter(id => id !== strVal);
                    } else {
                        selectedConsolidatedMemberIds.push(strVal);
                    }
                }
                updateConsolidatedMembersUI();
            });
        });
    }

    function updateConsolidatedMembersUI() {
        const selectedContainer = document.getElementById('consolidated-members-selected');
        const searchInput = document.getElementById('consolidated-members-search');
        const hiddenInput = document.getElementById('consolidated-members-hidden');
        if (!selectedContainer || !searchInput) return;

        // Clear existing chips
        selectedContainer.querySelectorAll('.chip').forEach(chip => chip.remove());

        // Render chips
        selectedConsolidatedMemberIds.forEach(id => {
            const member = currentConsolidatedTeamMembers.find(m => String(m.id) === String(id) || m.name === id);
            if (member) {
                const chip = document.createElement('span');
                chip.className = 'chip';
                chip.setAttribute('data-value', member.id);
                chip.innerHTML = `${member.name} <button type="button" class="chip-remove" data-value="${member.id}">&times;</button>`;
                selectedContainer.insertBefore(chip, searchInput);

                chip.querySelector('.chip-remove').addEventListener('click', (e) => {
                    e.stopPropagation();
                    selectedConsolidatedMemberIds = selectedConsolidatedMemberIds.filter(x => String(x) !== String(member.id));
                    updateConsolidatedMembersUI();
                });
            }
        });

        if (selectedConsolidatedMemberIds.length > 0) {
            searchInput.placeholder = "";
        } else {
            searchInput.placeholder = "Select team members...";
        }

        if (hiddenInput) {
            hiddenInput.value = selectedConsolidatedMemberIds.join(',');
        }

        renderConsolidatedMembersDropdown(currentConsolidatedTeamMembers);
    }

    // Bind Container Events
    const consContainer = document.getElementById('consolidated-members-container');
    const consSelected = document.getElementById('consolidated-members-selected');
    const consSearch = document.getElementById('consolidated-members-search');
    const consToggle = document.getElementById('consolidated-members-toggle');
    const consDropdown = document.getElementById('consolidated-members-dropdown');

    if (consSelected && consContainer && consSearch && consDropdown) {
        consSelected.addEventListener('click', (e) => {
            if (e.target === consSearch || e.target.classList.contains('chip-remove')) return;
            e.stopPropagation();
            const isOpen = consContainer.classList.contains('open');
            if (isOpen) {
                consContainer.classList.remove('open');
                consContainer.classList.remove('focus');
                consSearch.blur();
            } else {
                consContainer.classList.add('focus');
                consContainer.classList.add('open');
                consSearch.focus();
            }
        });

        if (consToggle) {
            consToggle.addEventListener('click', (e) => {
                e.stopPropagation();
                const isOpen = consContainer.classList.contains('open');
                if (isOpen) {
                    consContainer.classList.remove('open');
                    consContainer.classList.remove('focus');
                    consSearch.blur();
                } else {
                    consContainer.classList.add('focus');
                    consContainer.classList.add('open');
                    consSearch.focus();
                }
            });
        }

        consSearch.addEventListener('focus', () => {
            consContainer.classList.add('focus');
            consContainer.classList.add('open');
        });

        consSearch.addEventListener('input', () => {
            const q = consSearch.value.toLowerCase().trim();
            consDropdown.querySelectorAll('.multi-select-option').forEach(opt => {
                const text = opt.innerText.toLowerCase();
                if (text.includes(q)) {
                    opt.style.display = 'flex';
                } else {
                    opt.style.display = 'none';
                }
            });
        });

        document.addEventListener('click', (e) => {
            if (consContainer && !consContainer.contains(e.target)) {
                consContainer.classList.remove('open');
                consContainer.classList.remove('focus');
            }
        });
    }

    // Consolidated Leader Report submission handler
    async function openConsolidatedLeaderReportModal() {
        try {
            if (!employeesData || !employeesData.employees) {
                await loadEmployeesData();
            }

            let leader = null;
            if (currentUser) {
                leader = (employeesData.employees || []).find(e => (e.name || '').toLowerCase() === currentUser.toLowerCase() || String(e.id) === String(currentUser));
            }

            if (!leader && (userRole === 'Admin' || currentUser?.toUpperCase() === 'RAL')) {
                leader = (employeesData.employees || []).find(e => Array.isArray(e.roles) && e.roles.includes('Leader')) || { name: currentUser || "RAL", id: 1 };
            }

            if (!leader) {
                await showCustomAlert({ title: "Leader Account Required", message: "Logged-in user must be a Leader to submit consolidated team reports.", type: "warning" });
                return;
            }

            const leaderId = leader.id;
            const leaderNameEl = document.getElementById('consolidated-leader-name');
            const periodEl = document.getElementById('consolidated-period');
            const modalEl = document.getElementById('consolidated-modal');

            // Reset form fields first
            const form = document.getElementById('consolidated-form');
            if (form) form.reset();

            if (leaderNameEl) leaderNameEl.value = leader.name;
            if (periodEl) periodEl.value = new Date().toISOString().split('T')[0];

            // Populate #consolidated-section select with available roles
            const sectionSelect = document.getElementById('consolidated-section');
            if (sectionSelect) {
                sectionSelect.innerHTML = '';
                const rolesList = (configRoles && configRoles.length > 0) ? configRoles.filter(r => r !== 'Leader') : ["Live", "Playlist", "Helpdesk", "Social", "Conductor", "Archive", "R&D"];
                rolesList.forEach(sec => {
                    const opt = document.createElement('option');
                    opt.value = sec;
                    opt.innerText = sec;
                    sectionSelect.appendChild(opt);
                });
                if (sectionSelect.options.length > 0) {
                    sectionSelect.selectedIndex = 0;
                }
                updateConsolidatedLiveEventFieldsVisibility();
            }

            // Set default has-issue value to 'no'
            const hasIssueEl = document.getElementById('consolidated-has-issue');
            if (hasIssueEl) hasIssueEl.value = 'no';
            updateConsolidatedHasIssueVisibility();

            const teamMembers = (employeesData.employees || []).filter(m => 
                parseInt(m.reportsTo || m.reports_to) === parseInt(leaderId) || 
                String(m.reportsTo || m.reports_to) === String(leaderId) ||
                String(m.reportsTo || m.reports_to).toLowerCase() === String(leader.name).toLowerCase()
            );

            // Populate multi-select team member component
            currentConsolidatedTeamMembers = teamMembers;
            selectedConsolidatedMemberIds = teamMembers.map(m => String(m.id));
            updateConsolidatedMembersUI();

            const notesEl = document.getElementById('consolidated-summary-notes');
            if (notesEl) notesEl.value = '';
            if (modalEl) modalEl.classList.add('active');
            if (hasIssueEl) hasIssueEl.focus();
        } catch (err) {
            console.error("Error opening consolidated leader report modal:", err);
            await showCustomAlert({ title: "Error", message: "Failed to open Leader Report modal: " + err.message, type: "danger" });
        }
    }

    function updateConsolidatedHasIssueVisibility() {
        const hasIssueEl = document.getElementById('consolidated-has-issue');
        const probContainer = document.getElementById('consolidated-problem-details-container');
        const descInput = document.getElementById('consolidated-description');
        if (!hasIssueEl || !probContainer) return;

        if (hasIssueEl.value === 'yes') {
            probContainer.style.display = 'block';
            if (descInput) descInput.required = true;
        } else {
            probContainer.style.display = 'none';
            if (descInput) {
                descInput.required = false;
                descInput.value = '';
            }
        }
    }

    function updateConsolidatedLiveEventFieldsVisibility() {
        const sectionSelect = document.getElementById('consolidated-section');
        const liveFields = document.getElementById('consolidated-live-event-fields');
        if (!sectionSelect || !liveFields) return;

        const val = (sectionSelect.value || '').toLowerCase();
        if (val.includes('live')) {
            liveFields.style.display = 'block';
        } else {
            liveFields.style.display = 'none';
        }
    }

    document.getElementById('consolidated-has-issue')?.addEventListener('change', updateConsolidatedHasIssueVisibility);
    document.getElementById('consolidated-section')?.addEventListener('change', updateConsolidatedLiveEventFieldsVisibility);

    // Global Event Delegation for Submit Report buttons
    document.addEventListener('click', (e) => {
        const leaderBtn = e.target.closest('#btn-trigger-leader-report') || e.target.closest('#btn-create-consolidated-report');
        if (leaderBtn) {
            e.preventDefault();
            openConsolidatedLeaderReportModal();
            return;
        }

        const submitBtn = e.target.closest('#btn-trigger-submit-report');
        if (submitBtn) {
            e.preventDefault();
            openSubmitPersonalReportModal();
            return;
        }
    });

    // ----------------- PERSONAL REPORT MODAL CONTROLLER -----------------
    async function openSubmitPersonalReportModal() {
        try {
            if (!employeesData || !employeesData.employees) {
                await loadEmployeesData();
            }

            let emp = null;
            if (currentUser) {
                emp = (employeesData.employees || []).find(e => (e.name || '').toLowerCase() === currentUser.toLowerCase() || String(e.id) === String(currentUser));
            }

            // Get section roles assigned to this employee
            let availableSections = [];
            if (emp && Array.isArray(emp.roles) && emp.roles.length > 0) {
                availableSections = emp.roles.filter(r => r !== 'Leader');
                if (availableSections.length === 0) availableSections = emp.roles;
            }

            if (availableSections.length === 0) {
                availableSections = (configRoles && configRoles.length > 0) ? configRoles.filter(r => r !== 'Leader') : ["Live", "Playlist", "Helpdesk", "Social", "Conductor", "R&D"];
            }

            // Reset form fields first
            const form = document.getElementById('personal-report-form');
            if (form) form.reset();



            personalIssues = [];
            renderPersonalIssues();

            // Set Reporting Period date picker value
            const periodEl = document.getElementById('personal-report-period');
            if (periodEl) periodEl.value = new Date().toISOString().split('T')[0];

            // Set default has-issue value to 'no'
            const hasIssueEl = document.getElementById('personal-report-has-issue');
            if (hasIssueEl) hasIssueEl.value = 'no';
            updateHasIssueVisibility();

            // Populate #personal-report-section select dynamically with authorized units/roles
            const sectionSelect = document.getElementById('personal-report-section');
            if (sectionSelect) {
                sectionSelect.innerHTML = '';
                
                const validCategories = ['broadcast', 'conductor', 'archive', 'social', 'r&d', 'live', 'playlist', 'helpdesk'];
                const allowedCats = new Set();
                
                const isAdmin = userRole === 'Admin' || (currentUser && currentUser.toUpperCase() === 'RAL');
                
                if (isAdmin) {
                    validCategories.forEach(c => allowedCats.add(c));
                } else if (emp) {
                    // Extract units
                    const units = emp.unit || [];
                    const empUnits = Array.isArray(units) ? units : [units];
                    empUnits.forEach(u => {
                        if (u) {
                            const uClean = u.trim().toLowerCase();
                            allowedCats.add(uClean);
                            if (uClean.includes('social')) allowedCats.add('social');
                            if (uClean.includes('r&d') || uClean.includes('r & d')) allowedCats.add('r&d');
                        }
                    });
                    
                }
                
                // Filter allowedCats to only valid categories
                let finalCats = [];
                validCategories.forEach(cat => {
                    let isAllowed = false;
                    allowedCats.forEach(item => {
                        if (cat === item || item.includes(cat) || cat.includes(item)) {
                            isAllowed = true;
                        }
                    });
                    if (isAllowed) {
                        finalCats.push(cat);
                    }
                });
                
                if (finalCats.length === 0) {
                    finalCats = ['broadcast']; // Default fallback
                }
                
                const officialNames = {
                    'social': 'Social Media',
                    'r&d': 'R&D',
                    'conductor': 'Conductor',
                    'archive': 'Archive',
                    'broadcast': 'Broadcast',
                    'helpdesk': 'Helpdesk',
                    'live': 'Live',
                    'playlist': 'Playlist'
                };
                
                finalCats.forEach(cat => {
                    const opt = document.createElement('option');
                    opt.value = officialNames[cat] || (cat.charAt(0).toUpperCase() + cat.slice(1));
                    opt.textContent = cat;
                    sectionSelect.appendChild(opt);
                });
                
                sectionSelect.value = sectionSelect.options[0]?.value || 'Broadcast';
                updateLiveEventFieldsVisibility();
            }

            // Reset slider badge
            const ratingInput = document.getElementById('personal-report-rating');
            const ratingBadge = document.getElementById('personal-rating-val');
            if (ratingInput && ratingBadge) {
                ratingInput.value = 8;
                ratingBadge.innerText = '8 / 10';
            }

            const modal = document.getElementById('personal-report-modal');
            if (modal) modal.classList.add('active');
            
            if (hasIssueEl) hasIssueEl.focus();
        } catch (err) {
            console.error("Error opening personal report modal:", err);
            await showCustomAlert({ title: "Error", message: "Failed to open Personal Report form: " + err.message, type: "danger" });
        }
    }

    function updateHasIssueVisibility() {
        const hasIssueEl = document.getElementById('personal-report-has-issue');
        const probContainer = document.getElementById('problem-details-container');
        const descInput = document.getElementById('personal-report-description');
        if (!hasIssueEl || !probContainer) return;

        if (hasIssueEl.value === 'yes') {
            probContainer.style.display = 'block';
            if (descInput) descInput.required = true;
        } else {
            probContainer.style.display = 'none';
            if (descInput) {
                descInput.required = false;
                descInput.value = '';
            }
        }
    }

    function updateLiveEventFieldsVisibility() {
        const sectionSelect = document.getElementById('personal-report-section');
        const liveFields = document.getElementById('live-event-fields');
        if (!sectionSelect || !liveFields) return;

        const val = (sectionSelect.value || '').toLowerCase();
        if (val.includes('live') || val.includes('broadcast')) {
            liveFields.style.display = 'block';
        } else {
            liveFields.style.display = 'none';
        }
    }

    document.getElementById('personal-report-has-issue')?.addEventListener('change', updateHasIssueVisibility);
    document.getElementById('personal-report-section')?.addEventListener('change', updateLiveEventFieldsVisibility);

    const personalRatingInput = document.getElementById('personal-report-rating');
    const personalRatingBadge = document.getElementById('personal-rating-val');
    if (personalRatingInput && personalRatingBadge) {
        personalRatingInput.addEventListener('input', () => {
            personalRatingBadge.innerText = `${personalRatingInput.value} / 10`;
        });
    }

    document.getElementById('personal-report-cancel')?.addEventListener('click', () => {
        document.getElementById('personal-report-modal')?.classList.remove('active');
    });

    document.getElementById('personal-report-modal-close')?.addEventListener('click', () => {
        document.getElementById('personal-report-modal')?.classList.remove('active');
    });

    document.getElementById('personal-report-form')?.addEventListener('submit', async (e) => {
        e.preventDefault();

        try {


            const hasIssue = document.getElementById('personal-report-has-issue')?.value || 'no';
            const sectionEl = document.getElementById('personal-report-section');
            const section = sectionEl ? sectionEl.value : 'General';
            const subcatEl = document.getElementById('personal-report-subcategory');
            const subcategory = subcatEl ? subcatEl.value : 'General';
            const description = document.getElementById('personal-report-description')?.value.trim() || '';
            const ratingInput = document.getElementById('personal-report-rating');
            const rating = ratingInput ? parseInt(ratingInput.value || 8) : 8;
            const mood = document.getElementById('personal-report-mood')?.value || '😐 Normal';
            const notes = document.getElementById('personal-report-notes')?.value.trim() || '';

            const period = document.getElementById('personal-report-period')?.value || new Date().toISOString().split('T')[0];

            if (hasIssue === 'yes') {
                // If there's an issue currently typed in the input fields, auto-add it to personalIssues array
                if (description || subcategory) {
                    if (!subcategory || !description) {
                        await showCustomAlert({ title: "Validation Error", message: "Please fill in both Headline and Description for the current issue.", type: "warning" });
                        return;
                    }

                    const currentIssue = {
                        type: section,
                        category: section,
                        subcategory: subcategory,
                        description: description
                    };
                    personalIssues.push(currentIssue);
                }

                if (personalIssues.length === 0) {
                    await showCustomAlert({ title: "Validation Error", message: "Please add at least one issue details.", type: "warning" });
                    return;
                }
            }

            const payload = {
                period: period,
                has_issue: hasIssue,
                problems: hasIssue === 'yes' ? personalIssues : [],
                // Legacy fields fallback for backward compatibility using the first issue
                section: hasIssue === 'yes' && personalIssues.length > 0 ? personalIssues[0].type : 'General',
                category: hasIssue === 'yes' && personalIssues.length > 0 ? personalIssues[0].category : 'General',
                subcategory: hasIssue === 'yes' && personalIssues.length > 0 ? personalIssues[0].subcategory : 'General',
                description: hasIssue === 'yes' && personalIssues.length > 0 ? personalIssues[0].description : '',
                rating: rating,
                mood: mood,
                additional_info: notes
            };

            const result = await apiRequest('/api/reports', {
                method: 'POST',
                body: JSON.stringify(payload)
            });

            if (result) {
                document.getElementById('personal-report-modal')?.classList.remove('active');
                await showCustomAlert({
                    title: "Report Submitted Successfully",
                    message: hasIssue === 'yes'
                        ? `Your incident report for the "${section}" section has been logged and sent to your supervisor for review.`
                        : `Your clean shift report has been logged successfully and sent to your supervisor.`,
                    type: "success"
                });
                
                if (typeof loadReportsData === 'function') loadReportsData();
                if (typeof loadPendingQueue === 'function') loadPendingQueue();
            }
        } catch (err) {
            console.error("Error submitting personal report:", err);
            await showCustomAlert({ title: "Submission Error", message: "Failed to submit report: " + err.message, type: "danger" });
        }
    });

    document.getElementById('consolidated-cancel')?.addEventListener('click', () => {
        document.getElementById('consolidated-modal')?.classList.remove('active');
    });

    document.getElementById('consolidated-modal-close')?.addEventListener('click', () => {
        document.getElementById('consolidated-modal')?.classList.remove('active');
    });

    document.getElementById('consolidated-form')?.addEventListener('submit', async (e) => {
        e.preventDefault();

        const leaderName = document.getElementById('consolidated-leader-name').value;
        const period = document.getElementById('consolidated-period').value.trim();
        const notes = document.getElementById('consolidated-summary-notes').value.trim();
        const hasIssue = document.getElementById('consolidated-has-issue')?.value || 'no';
        const sectionEl = document.getElementById('consolidated-section');
        const section = sectionEl ? sectionEl.value : 'General';
        const category = document.getElementById('consolidated-category')?.value || 'General';
        const description = document.getElementById('consolidated-description')?.value.trim() || '';
        const liveName = document.getElementById('consolidated-live-name')?.value.trim() || null;
        const liveSource = document.getElementById('consolidated-live-source')?.value || 'Controls';

        if (hasIssue === 'yes' && !description) {
            await showCustomAlert({ title: "Validation Error", message: "Please describe the problem that occurred for the team.", type: "warning" });
            return;
        }

        const isLive = hasIssue === 'yes' && section && typeof section === 'string' && section.toLowerCase().includes('live');
        const payload = {
            leader_name: leaderName,
            period: period,
            summary_notes: notes,
            included_report_ids: selectedConsolidatedMemberIds,
            has_issue: hasIssue,
            section: hasIssue === 'yes' ? section : 'General',
            category: hasIssue === 'yes' ? category : 'General',
            description: hasIssue === 'yes' ? description : '',
            live_event_name: isLive ? liveName : null,
            live_event_source: isLive ? liveSource : null
        };

        const result = await apiRequest('/api/reports/consolidated', {
            method: 'POST',
            body: JSON.stringify(payload)
        });

        if (result) {
            document.getElementById('consolidated-modal')?.classList.remove('active');
            await showCustomAlert({ title: "Report Submitted", message: "Consolidated Leader Report submitted successfully to management!", type: "success" });
            if (typeof loadReportsData === 'function') loadReportsData();
        }
    });

    // ----------------- EMPLOYEE CRUD ACTION LISTENERS -----------------
    const empModalTitle = document.getElementById('employee-modal-title');
    const empForm = document.getElementById('employee-form');
    const empEditModeInput = document.getElementById('emp-edit-mode');
    const empOriginalNameInput = document.getElementById('emp-original-name');
    
    document.getElementById('btn-add-employee').addEventListener('click', () => {
        empModalTitle.innerText = "Add New Employee";
        empEditModeInput.value = "add";
        empOriginalNameInput.value = "";
        empForm.reset();
        
        renderFormDropdowns();

        renderSupervisorDropdownOptions();
        selectedSupervisors = [];
        updateSupervisorUI();

        selectedUnits = [];
        updateUnitsUI();

        selectedRoles = [];
        updateRolesUI();

        selectedConditions = [];
        updateConditionsUI();

        selectedLocation = "";
        updateLocationUI();

        selectedLeaderType = "";
        updateLeaderTypeUI();

        const shiftSelect = document.getElementById('emp-leader-shift');
        if (shiftSelect) shiftSelect.value = '';

        employeeShifts = [{ start: "", end: "" }];
        renderShiftsList();
        validateAndSyncShifts();

        employeeModal.classList.add('active');
    });

    function attachEmployeeListeners() {
        document.querySelectorAll('.btn-edit-employee').forEach(btn => {
            btn.addEventListener('click', () => {
                const name = btn.getAttribute('data-name');
                const emp = employeesData.employees.find(e => e.name === name);
                if (!emp) return;
                
                empModalTitle.innerText = `Edit Employee: ${emp.name}`;
                empEditModeInput.value = "edit";
                empOriginalNameInput.value = emp.name;
                
                document.getElementById('emp-name').value = emp.name;
                selectedLocation = emp.work_location || "";
                updateLocationUI();
                
                employeeShifts = parseEmployeeHours(emp.work_hours);
                renderShiftsList();
                validateAndSyncShifts();
                
                renderFormDropdowns();

                renderSupervisorDropdownOptions(emp.id);
                const rawSups = emp.reportsTo || emp.reports_to || [];
                if (Array.isArray(rawSups)) {
                    selectedSupervisors = rawSups.map(x => parseInt(x));
                } else if (rawSups) {
                    selectedSupervisors = [parseInt(rawSups)];
                } else {
                    selectedSupervisors = [];
                }
                updateSupervisorUI();

                selectedUnits = parseEmployeeUnits(emp.unit);
                updateUnitsUI();

                selectedRoles = parseEmployeeRoles(emp.roles);
                updateRolesUI();

                selectedConditions = parseEmployeeConditions(emp.special_conditions);
                updateConditionsUI();

                selectedLeaderType = emp.leader_type || "";
                updateLeaderTypeUI();

                const shiftSelect = document.getElementById('emp-leader-shift');
                if (shiftSelect) shiftSelect.value = emp.leader_shift || "";

                employeeModal.classList.add('active');
            });
        });

        document.querySelectorAll('.btn-delete-employee').forEach(btn => {
            btn.addEventListener('click', async () => {
                const name = btn.getAttribute('data-name');
                console.log("[Delete Employee] Button clicked for name:", name);
                const emp = employeesData.employees.find(e => e.name === name);
                console.log("[Delete Employee] Found employee object:", emp);

                let warningText = "This action cannot be undone.";
                let subordinates = [];

                if (emp) {
                    subordinates = employeesData.employees.filter(e => {
                        const raws = e.reportsTo || e.reports_to || [];
                        const sups = Array.isArray(raws) ? raws : [raws];
                        return sups.map(x => parseInt(x)).includes(parseInt(emp.id));
                    });
                    console.log("[Delete Employee] Subordinates found:", subordinates);
                    if (subordinates.length > 0) {
                        const subNames = subordinates.map(s => s.name).join(', ');
                        warningText = `Warning: ${name} is currently supervising ${subordinates.length} employee(s): ${subNames}. Deleting this employee will unassign their team members.`;
                    }
                }

                const confirmed = await showCustomConfirm({
                    title: "Delete Employee",
                    message: `Are you sure you want to delete employee <strong>"${name}"</strong>?`,
                    warning: warningText,
                    confirmText: "Delete Employee",
                    isDanger: true
                });
                console.log("[Delete Employee] Confirmation result:", confirmed);
                if (!confirmed) return;

                if (subordinates.length > 0) {
                    console.log("[Delete Employee] Unassigning subordinates supervisor relations...");
                    for (const sub of subordinates) {
                        await apiRequest('/api/employees/reassign', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ employee_id: sub.id, supervisor_id: null })
                        });
                    }
                }

                const deleteTarget = emp && emp.id ? emp.id : encodeURIComponent(name);
                console.log("[Delete Employee] Sending DELETE request to backend for target:", deleteTarget);
                const result = await apiRequest(`/api/employees/${deleteTarget}`, {
                    method: 'DELETE'
                });
                console.log("[Delete Employee] DELETE request result:", result);

                if (result) {
                    await showCustomAlert({ title: "Employee Deleted", message: `Employee "${name}" deleted successfully!`, type: "success" });
                    loadEmployeesData();
                }
            });
        });
    }

    empForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        if (selectedUnits.length === 0) {
            unitContainer.classList.add('is-invalid');
            unitSearch.focus();
            return;
        }

        if (selectedRoles.length === 0) {
            rolesContainer.classList.add('is-invalid');
            rolesSearch.focus();
            return;
        }

        if (selectedRoles.includes('Leader') && !selectedLeaderType) {
            leaderTypeContainer.classList.add('is-invalid');
            leaderTypeSearch.focus();
            return;
        }

        if (!selectedLocation) {
            locationContainer.classList.add('is-invalid');
            locationSearch.focus();
            return;
        }

        if (!validateAndSyncShifts()) {
            hoursContainer.classList.add('is-invalid');
            const firstEmptySearch = document.querySelector('.shift-row .multi-select-search-input');
            if (firstEmptySearch) firstEmptySearch.focus();
            return;
        }

        if (hasOverlappingShifts()) {
            const proceedOverlapping = await showCustomConfirm({
                title: "Overlapping Shifts Warning",
                message: "Some of the specified work shifts overlap.",
                warning: "Are you sure you want to save this shift configuration with overlapping hours?",
                confirmText: "Save Configuration",
                cancelText: "Fix Shifts",
                isDanger: false
            });
            if (!proceedOverlapping) {
                hoursContainer.classList.add('is-invalid');
                return;
            }
        }

        const mode = empEditModeInput.value;
        const origName = empOriginalNameInput.value;

        const empObj = employeesData.employees.find(e => e.name === origName);
        const currentEmpId = empObj ? empObj.id : null;

        if (empObj) {
            const wasLeader = Array.isArray(empObj.roles) && empObj.roles.includes("Leader");
            const isStillLeader = selectedRoles.includes("Leader");

            if (wasLeader && !isStillLeader) {
                const subordinates = employeesData.employees.filter(e => parseInt(e.reportsTo || e.reports_to) === parseInt(empObj.id));
                if (subordinates.length > 0) {
                    const subNames = subordinates.map(s => s.name).join(', ');
                    const confirmed = await showCustomConfirm({
                        title: "Leader Role Removal Warning",
                        message: `<strong>${empObj.name}</strong> is currently assigned as supervisor for <strong>${subordinates.length} employee(s)</strong>: <em>${subNames}</em>.`,
                        warning: "Removing the Leader role will unassign all team members reporting to this employee. Do you want to proceed and unassign their team?",
                        confirmText: "Proceed & Unassign Team",
                        cancelText: "Cancel",
                        isDanger: true
                    });
                    if (!confirmed) return;

                    for (const sub of subordinates) {
                        await apiRequest('/api/employees/reassign', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ employee_id: sub.id, supervisor_id: null })
                        });
                    }
                }
            }
        }

        if (currentEmpId && selectedSupervisors.length > 0) {
            if (selectedSupervisors.map(x => parseInt(x)).includes(parseInt(currentEmpId))) {
                await showCustomAlert({ title: "Assignment Error", message: "An employee cannot report to themselves.", type: "danger" });
                return;
            }
            if (checkJsReportingCycle(employeesData.employees, currentEmpId, selectedSupervisors)) {
                await showCustomAlert({ title: "Circular Reporting Error", message: "Circular reporting chain detected! Employee cannot report to a supervisor in their own downstream chain.", type: "danger" });
                return;
            }
        }

        const name = document.getElementById('emp-name').value.trim();
        const location = document.getElementById('emp-location').value.trim();
        const hours = document.getElementById('emp-hours').value.trim();

        const payload = {
            name: name,
            unit: selectedUnits,
            roles: selectedRoles,
            leader_type: selectedRoles.includes('Leader') ? selectedLeaderType : null,
            leader_shift: selectedRoles.includes('Leader') ? (document.getElementById('emp-leader-shift')?.value || null) : null,
            work_location: location,
            work_hours: hours,
            special_conditions: selectedConditions,
            reportsTo: selectedSupervisors
        };

        let result = null;
        if (mode === 'add') {
            result = await apiRequest('/api/employees', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
        } else {
            result = await apiRequest(`/api/employees/${encodeURIComponent(origName)}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
        }

        if (result) {
            await showCustomAlert({
                title: mode === 'add' ? "Employee Added" : "Employee Updated",
                message: mode === 'add' ? `Employee "${name}" added successfully!` : `Employee details for "${name}" updated!`,
                type: "success"
            });
            employeeModal.classList.remove('active');
            loadEmployeesData();
        }
    });

    // ----------------- EDIT REPORT MODAL CONTROLLERS & HANDLERS -----------------
    async function openEditReportModal(reportId) {
        const report = await apiRequest(`/api/reports/${reportId}`);
        if (!report) return;
        
        const reportData = report.data || {};
        
        // 1. Populate basic fields
        const idField = document.getElementById('edit-report-id');
        if (idField) idField.value = report.id;
        
        // Split timestamp into date and time
        const ts = report.created_at || report.timestamp || "";
        let datePart = reportData.date || "";
        let timePart = "00:00";
        if (ts.includes('T')) {
            const parts = ts.split('T');
            if (!datePart) datePart = parts[0];
            timePart = parts[1].substring(0, 5);
        }
        const dateField = document.getElementById('edit-report-date');
        if (dateField) dateField.value = datePart;
        const timeField = document.getElementById('edit-report-time');
        if (timeField) timeField.value = timePart;
        
        // 2. Populate Employee Select
        const employeeSelect = document.getElementById('edit-report-employee');
        if (employeeSelect) {
            employeeSelect.innerHTML = '';
            if (employeesData && employeesData.employees) {
                employeesData.employees.forEach(emp => {
                    const opt = document.createElement('option');
                    opt.value = emp.name;
                    opt.textContent = emp.name;
                    if (emp.name === reportData.employee) {
                        opt.selected = true;
                    }
                    employeeSelect.appendChild(opt);
                });
            }
        }
        
        // 3. Populate Unit Select
        const unitSelect = document.getElementById('edit-report-unit');
        if (unitSelect) {
            unitSelect.innerHTML = '';
            const unitsList = (employeesData && employeesData.units) || ['Broadcast', 'Social', 'Conductor', 'Archive', 'R&D'];
            unitsList.forEach(u => {
                const opt = document.createElement('option');
                opt.value = u;
                opt.textContent = u;
                const empUnit = (reportData.employee_data && reportData.employee_data.unit) || '';
                const isMatch = Array.isArray(empUnit) ? empUnit.includes(u) : empUnit === u;
                if (isMatch) {
                    opt.selected = true;
                }
                unitSelect.appendChild(opt);
            });
        }
        
        // 4. Populate Rating, Mood, Notes
        const ratingField = document.getElementById('edit-report-rating');
        if (ratingField) ratingField.value = reportData.rating || 10;
        const moodField = document.getElementById('edit-report-mood');
        if (moodField) moodField.value = reportData.mood || '😐 Normal';
        const descField = document.getElementById('edit-report-description');
        if (descField) descField.value = reportData.additional_info || '';
        
        // 5. Populate Status
        const statusField = document.getElementById('edit-report-status');
        if (statusField) statusField.value = report.status || 'pending';
        
        // 6. Populate Leader Select
        const leaderSelect = document.getElementById('edit-report-leader');
        if (leaderSelect) {
            leaderSelect.innerHTML = '<option value="">No Reviewing Leader</option>';
            let currentLeaderName = report.leader_name || (report.manager_feedback && report.manager_feedback.manager_id) || '';
            
            if (employeesData && employeesData.employees) {
                employeesData.employees.forEach(emp => {
                    const isLeader = emp.roles && emp.roles.includes('Leader');
                    if (isLeader) {
                        const opt = document.createElement('option');
                        opt.value = emp.name;
                        opt.textContent = emp.name;
                        if (emp.name === currentLeaderName) {
                            opt.selected = true;
                        }
                        leaderSelect.appendChild(opt);
                    }
                });
            }
        }
        
        // 7. Populate Approval feedback
        const managerRatingField = document.getElementById('edit-report-manager-rating');
        if (managerRatingField) managerRatingField.value = report.manager_rating || '';
        const managerCommentField = document.getElementById('edit-report-manager-comment');
        if (managerCommentField) managerCommentField.value = report.manager_comment || '';
        
        const approvalDetails = document.getElementById('edit-report-approval-details');
        if (statusField && approvalDetails) {
            const toggleApprovalDetails = () => {
                if (statusField.value === 'approved') {
                    approvalDetails.style.display = 'grid';
                } else {
                    approvalDetails.style.display = 'none';
                }
            };
            statusField.removeEventListener('change', toggleApprovalDetails);
            statusField.addEventListener('change', toggleApprovalDetails);
            toggleApprovalDetails();
        }
        
        // 8. Populate Problems list
        const problemsContainer = document.getElementById('edit-report-problems-container');
        if (problemsContainer) {
            problemsContainer.innerHTML = '';
            
            const problems = report.problems || reportData.problems || [];
            if (problems.length === 0) {
                problemsContainer.innerHTML = '<div class="text-secondary small">No problems reported in this shift.</div>';
            } else {
                problems.forEach((prob, index) => {
                    if (!prob || typeof prob !== 'object') return;
                    const probDiv = document.createElement('div');
                    probDiv.className = 'problem-edit-row';
                    probDiv.style.border = '1px solid var(--border-color)';
                    probDiv.style.padding = '12px';
                    probDiv.style.borderRadius = '8px';
                    probDiv.style.backgroundColor = 'rgba(255, 255, 255, 0.02)';
                    probDiv.style.marginBottom = '10px';
                    
                    const categoriesList = ['broadcast', 'conductor', 'archive', 'social', 'r&d', 'live', 'playlist', 'helpdesk'];
                    const currentCategory = (prob.category || prob.type || 'broadcast').toLowerCase();
                    
                    let categoriesOpts = '';
                    categoriesList.forEach(cat => {
                        const selected = cat === currentCategory ? 'selected' : '';
                        categoriesOpts += `<option value="${cat}" ${selected}>${cat.toUpperCase()}</option>`;
                    });
                    
                    probDiv.innerHTML = `
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                            <span style="font-weight: 600; color: var(--indigo-400);">Incident #${index + 1}</span>
                        </div>
                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 8px;">
                            <div class="form-group">
                                <label>Category</label>
                                <select class="form-control prob-category" data-index="${index}">
                                    ${categoriesOpts}
                                </select>
                            </div>
                            <div class="form-group">
                                <label>Affected Servers (comma-separated)</label>
                                <input type="text" class="form-control prob-servers" data-index="${index}" value="${(prob.servers || []).join(', ')}">
                            </div>
                        </div>
                        <div class="form-group" style="margin-bottom: 0;">
                            <label>Description</label>
                            <textarea class="form-control prob-description" data-index="${index}" rows="2" required>${prob.description || ''}</textarea>
                        </div>
                    `;
                    problemsContainer.appendChild(probDiv);
                });
            }
        }
        
        const modal = document.getElementById('edit-report-modal');
        if (modal) modal.classList.add('active');
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }

    document.getElementById('edit-report-close')?.addEventListener('click', () => {
        document.getElementById('edit-report-modal').classList.remove('active');
    });
    document.getElementById('edit-report-cancel')?.addEventListener('click', () => {
        document.getElementById('edit-report-modal').classList.remove('active');
    });
    
    document.getElementById('edit-report-form')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const confirmSave = await showCustomConfirm({
            title: "Save Changes",
            message: "Are you sure you want to save these changes?",
            confirmText: "Yes, Save",
            cancelText: "Cancel"
        });
        if (!confirmSave) return;
        
        const saveButton = document.getElementById('edit-report-save');
        const saveButtonText = saveButton ? saveButton.querySelector('span') : null;
        const originalText = saveButtonText ? saveButtonText.textContent : 'Save Changes';
        
        if (saveButton) {
            saveButton.disabled = true;
            if (saveButtonText) saveButtonText.textContent = 'Saving...';
        }
        
        try {
            const reportId = document.getElementById('edit-report-id').value;
            const date = document.getElementById('edit-report-date').value;
            const time = document.getElementById('edit-report-time').value;
            const employee = document.getElementById('edit-report-employee').value;
            
            let employeeId = 0;
            if (employeesData && employeesData.employees) {
                const emp = employeesData.employees.find(e => e.name === employee);
                if (emp) employeeId = emp.id;
            }
            
            const unit = document.getElementById('edit-report-unit').value;
            const rating = parseInt(document.getElementById('edit-report-rating').value) || 10;
            const mood = document.getElementById('edit-report-mood').value;
            const additionalInfo = document.getElementById('edit-report-description').value;
            const status = document.getElementById('edit-report-status').value;
            const leaderName = document.getElementById('edit-report-leader').value || null;
            
            let managerRating = null;
            let managerComment = "";
            if (status === 'approved') {
                const rVal = document.getElementById('edit-report-manager-rating').value;
                managerRating = rVal ? parseInt(rVal) : null;
                managerComment = document.getElementById('edit-report-manager-comment').value || "";
            }
            
            const problems = [];
            document.querySelectorAll('.problem-edit-row').forEach(row => {
                const cat = row.querySelector('.prob-category').value;
                const desc = row.querySelector('.prob-description').value;
                const servsStr = row.querySelector('.prob-servers').value;
                const servers = servsStr ? servsStr.split(',').map(s => s.trim()).filter(s => s) : [];
                
                problems.push({
                    "type": cat,
                    "category": cat,
                    "description": desc,
                    "servers": servers
                });
            });
            
            const payload = {
                date: date,
                time: time,
                employee: employee,
                employee_id: employeeId,
                unit: unit,
                rating: rating,
                mood: mood,
                additional_info: additionalInfo,
                status: status,
                leader_name: leaderName,
                manager_rating: managerRating,
                manager_comment: managerComment,
                problems: problems
            };
            
            const res = await fetch(`/api/reports/${reportId}`, {
                method: 'PUT',
                headers: { 
                    'Content-Type': 'application/json',
                    'X-Session-Token': sessionToken
                },
                body: JSON.stringify(payload)
            });
            
            if (res.ok) {
                document.getElementById('edit-report-modal').classList.remove('active');
                await showCustomAlert({
                    title: "Success",
                    message: "Report updated successfully.",
                    type: "success"
                });
                await loadReportsData();
            } else {
                const errData = await res.json().catch(() => ({}));
                await showCustomAlert({
                    title: "Error",
                    message: errData.detail || "Failed to update the report.",
                    type: "danger"
                });
            }
        } catch (err) {
            await showCustomAlert({
                title: "Error",
                message: err.message || "Unable to connect to server.",
                type: "danger"
            });
        } finally {
            if (saveButton) {
                saveButton.disabled = false;
                if (saveButtonText) saveButtonText.textContent = originalText;
            }
        }
    });

    // ----------------- PAGE BOOTSTRAPPING -----------------
    async function initApp() {
        if (sessionToken) {
            try {
                const meRes = await fetch('/api/auth/me', {
                    headers: { 'X-Session-Token': sessionToken }
                });
                if (meRes.ok) {
                    const data = await meRes.json();
                    currentUser = data.username;
                    userRole = data.role;
                    userName = data.name;
                    updateActiveUserProfileUI(userName, userRole);
                    applyRolePermissions();
                    showAppContainer();
                    await loadEmployeesData();
                    return;
                }
            } catch (e) {}
        }
        performLogout();
    }
    initApp();
});
