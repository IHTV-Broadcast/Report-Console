/**
 * Client-Side Application for Quick Incident Reporter.
 * Handles:
 * - Passwordless Employee Name selection and local state persistence
 * - Fast 3-step reporting wizard with dynamic card rendering
 * - Real-time auto-detection of Farsi (RTL) vs English (LTR) in text inputs
 * - Form submission and My Reports tracking
 */

document.addEventListener('DOMContentLoaded', async () => {
    // Strict Per-Refresh Login Enforcement:
    // With every page refresh/reload, clear past credentials so the user MUST re-select their name or re-enter password.
    localStorage.removeItem('incident_reporter_name');
    localStorage.removeItem('incident_admin_token');
    sessionStorage.removeItem('incident_reporter_name');
    sessionStorage.removeItem('incident_active_reporter');

    let bootstrapData = { users: [], units: [], preset_tags: [] };
    let currentReporter = null;
    let selectedUnit = null;
    let selectedSection = null;
    let activePreset = null;
    let selectedMentionIds = new Set();

    // Elements
    const userBadgeBtn = document.getElementById('user-badge-btn');
    const currentUserNameEl = document.getElementById('current-user-name');
    const userPickerModal = document.getElementById('user-picker-modal');
    const userCardsGrid = document.getElementById('user-cards-grid');
    const adminPasswordBox = document.getElementById('admin-password-box');
    const adminInlinePassword = document.getElementById('admin-inline-password');
    const adminAuthInlineForm = document.getElementById('admin-auth-inline-form');
    const adminAuthErrorMsg = document.getElementById('admin-auth-error-msg');
    const btnClosePickerModal = document.getElementById('btn-close-picker-modal');
    const adminCardTopBtn = document.getElementById('admin-card-top-btn');

    const step1 = document.getElementById('step-1');
    const step2 = document.getElementById('step-2');
    const step3 = document.getElementById('step-3');
    const stepSuccess = document.getElementById('step-success');
    const viewMyReports = document.getElementById('view-my-reports');

    const unitsGrid = document.getElementById('units-grid');
    const sectionsGrid = document.getElementById('sections-grid');
    const presetsContainer = document.getElementById('presets-container');
    const incidentForm = document.getElementById('incident-form');
    const descTextarea = document.getElementById('incident-description');
    
    // Priority and Mentions elements
    const btnPrioNormal = document.getElementById('btn-prio-normal');
    const btnPrioCritical = document.getElementById('btn-prio-critical');
    const incidentPriorityInput = document.getElementById('incident-priority');
    const mentionsGrid = document.getElementById('mentions-grid');
    const btnSelectAllMentions = document.getElementById('btn-select-all-mentions');
    const btnClearMentions = document.getElementById('btn-clear-mentions');
    const mentionsCounter = document.getElementById('mentions-selected-counter');

    // Initialize Lucide icons
    function refreshIcons() {
        if (window.lucide && window.lucide.createIcons) {
            window.lucide.createIcons();
        }
    }

    // Bidirectional text detection (Auto RTL for Farsi, LTR for English)
    function applyAutoBidi(el) {
        if (!el) return;
        el.addEventListener('input', () => {
            const val = el.value.trim();
            if (!val) {
                el.style.direction = 'ltr';
                return;
            }
            // Check if first non-space character is Arabic/Persian Unicode range
            const isFarsi = /^[\u0600-\u06FF\uFB8A\u067E\u0686\u06AF]/.test(val);
            el.style.direction = isFarsi ? 'rtl' : 'ltr';
            el.style.textAlign = isFarsi ? 'right' : 'left';
        });
    }
    applyAutoBidi(descTextarea);

    // Fetch Bootstrap Data
    async function loadBootstrap() {
        try {
            const res = await fetch('/api/public/bootstrap');
            if (res.ok) {
                bootstrapData = await res.json();
                renderUnits();
                renderUserPickerList();
                renderPresetTags();
                renderExtraMentionsList();
            }
        } catch (e) {
            console.error("Failed to load bootstrap data:", e);
        }
    }

    let selectedAdminStaff = null;
    const btnLoginAsAdminReporter = document.getElementById('btn-login-as-admin-reporter');
    const btnLoginReporterLabel = document.getElementById('btn-login-reporter-label');

    // --- User Selection Logic ---
    function updateCurrentUserDisplay() {
        if (currentReporter) {
            currentUserNameEl.innerText = currentReporter;
        } else {
            currentUserNameEl.innerText = "Select Your Name";
            openUserPicker();
        }
    }

    function openUserPicker() {
        if (!userPickerModal) return;
        userPickerModal.classList.add('active');
        selectedAdminStaff = null;
        if (btnLoginAsAdminReporter) {
            btnLoginAsAdminReporter.style.display = 'none';
        }
        if (btnClosePickerModal) {
            btnClosePickerModal.style.display = currentReporter ? 'inline-flex' : 'none';
        }
        if (adminPasswordBox) {
            adminPasswordBox.style.display = 'none';
        }
        if (adminCardTopBtn) {
            adminCardTopBtn.classList.remove('active');
        }
        if (adminInlinePassword) {
            adminInlinePassword.value = '';
        }
        if (adminAuthErrorMsg) {
            adminAuthErrorMsg.style.display = 'none';
            adminAuthErrorMsg.innerText = '';
        }
        renderUserPickerList();
    }

    function closeUserPicker() {
        if (userPickerModal) {
            userPickerModal.classList.remove('active');
        }
    }

    function renderUserPickerList() {
        if (!userCardsGrid) return;
        userCardsGrid.innerHTML = '';

        // Only exclude the special top dedicated 'Admin' from the grid so it remains as top card
        const staffMembers = (bootstrapData.users || []).filter(u => u.name.toLowerCase() !== 'admin');

        if (staffMembers.length === 0) {
            userCardsGrid.innerHTML = `<div style="grid-column: 1 / -1; padding: 16px; font-size: 0.9rem; color: var(--text-muted); text-align: center;">No active staff accounts configured.</div>`;
            return;
        }

        staffMembers.forEach(u => {
            const card = document.createElement('div');
            const isSelected = (currentReporter === u.name);

            card.className = `staff-card ${isSelected ? 'active' : ''}`;
            card.innerHTML = `<div class="staff-name">${u.name}</div>`;

            card.addEventListener('click', () => {
                if (u.role === 'Admin') {
                    // Admin role strictly requires password before access
                    selectedAdminStaff = u;
                    document.querySelectorAll('.staff-card').forEach(c => c.classList.remove('active'));
                    card.classList.add('active');
                    if (adminCardTopBtn) adminCardTopBtn.classList.remove('active');
                    if (adminPasswordBox) {
                        adminPasswordBox.style.display = 'block';
                        if (adminAuthErrorMsg) adminAuthErrorMsg.style.display = 'none';
                        if (btnLoginAsAdminReporter && btnLoginReporterLabel) {
                            btnLoginAsAdminReporter.style.display = 'inline-flex';
                            btnLoginReporterLabel.innerText = `Report as ${u.name}`;
                        }
                        if (adminInlinePassword) {
                            adminInlinePassword.value = '';
                            adminInlinePassword.placeholder = `Enter Admin Password for ${u.name}...`;
                            adminInlinePassword.focus();
                        }
                    }
                    return;
                }

                selectedAdminStaff = null;
                if (adminPasswordBox) adminPasswordBox.style.display = 'none';
                if (adminCardTopBtn) adminCardTopBtn.classList.remove('active');
                if (btnLoginAsAdminReporter) btnLoginAsAdminReporter.style.display = 'none';
                currentReporter = u.name;
                sessionStorage.setItem('incident_active_reporter', u.name);
                updateCurrentUserDisplay();
                closeUserPicker();
            });

            userCardsGrid.appendChild(card);
        });

        refreshIcons();
    }

    // Top Admin Button Click Handler
    if (adminCardTopBtn) {
        adminCardTopBtn.addEventListener('click', () => {
            selectedAdminStaff = null;
            if (btnLoginAsAdminReporter) btnLoginAsAdminReporter.style.display = 'none';
            // Deselect any active staff card
            document.querySelectorAll('.staff-card').forEach(c => c.classList.remove('active'));

            if (adminPasswordBox) {
                const isShowing = adminPasswordBox.style.display === 'block';
                if (isShowing) {
                    adminPasswordBox.style.display = 'none';
                    adminCardTopBtn.classList.remove('active');
                } else {
                    adminPasswordBox.style.display = 'block';
                    adminCardTopBtn.classList.add('active');
                    if (adminAuthErrorMsg) adminAuthErrorMsg.style.display = 'none';
                    if (adminInlinePassword) {
                        adminInlinePassword.value = '';
                        adminInlinePassword.placeholder = 'Enter Admin Password...';
                        adminInlinePassword.focus();
                    }
                }
            }
        });
    }

    // Inline Admin Password Form Submission
    if (adminAuthInlineForm) {
        adminAuthInlineForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            if (adminAuthErrorMsg) adminAuthErrorMsg.style.display = 'none';

            const pwd = adminInlinePassword ? adminInlinePassword.value.trim() : '';
            if (!pwd) return;

            try {
                const res = await fetch('/api/admin/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ password: pwd })
                });
                const data = await res.json();
                if (res.ok && data.success) {
                    sessionStorage.setItem('incident_admin_token', data.token);
                    window.location.href = '/admin';
                } else {
                    if (adminAuthErrorMsg) {
                        adminAuthErrorMsg.innerText = data.detail || 'Incorrect administrator password. Access denied.';
                        adminAuthErrorMsg.style.display = 'block';
                    }
                    if (adminInlinePassword) {
                        adminInlinePassword.select();
                    }
                }
            } catch (err) {
                if (adminAuthErrorMsg) {
                    adminAuthErrorMsg.innerText = 'Network connection error while validating password.';
                    adminAuthErrorMsg.style.display = 'block';
                }
            }
        });
    }

    if (btnLoginAsAdminReporter) {
        btnLoginAsAdminReporter.addEventListener('click', async () => {
            const pwd = adminInlinePassword ? adminInlinePassword.value.trim() : '';
            if (!pwd) {
                if (adminInlinePassword) adminInlinePassword.focus();
                return;
            }
            if (adminAuthErrorMsg) adminAuthErrorMsg.style.display = 'none';
            try {
                const res = await fetch('/api/admin/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ password: pwd })
                });
                const data = await res.json();
                if (res.ok && data.success) {
                    sessionStorage.setItem('incident_admin_token', data.token);
                    if (selectedAdminStaff) {
                        currentReporter = selectedAdminStaff.name;
                        sessionStorage.setItem('incident_active_reporter', selectedAdminStaff.name);
                        updateCurrentUserDisplay();
                        closeUserPicker();
                    } else {
                        window.location.href = '/admin';
                    }
                } else {
                    if (adminAuthErrorMsg) {
                        adminAuthErrorMsg.innerText = data.detail || 'Incorrect administrator password. Access denied.';
                        adminAuthErrorMsg.style.display = 'block';
                    }
                    if (adminInlinePassword) adminInlinePassword.select();
                }
            } catch (err) {
                if (adminAuthErrorMsg) {
                    adminAuthErrorMsg.innerText = 'Network connection error while validating password.';
                    adminAuthErrorMsg.style.display = 'block';
                }
            }
        });
    }

    if (btnClosePickerModal) {
        btnClosePickerModal.addEventListener('click', () => {
            if (currentReporter) {
                closeUserPicker();
            }
        });
    }

    if (userPickerModal) {
        userPickerModal.addEventListener('click', (e) => {
            if (e.target === userPickerModal && currentReporter) {
                closeUserPicker();
            }
        });
    }

    window.addEventListener('pageshow', (event) => {
        if (event.persisted) {
            currentReporter = null;
            sessionStorage.removeItem('incident_active_reporter');
            sessionStorage.removeItem('incident_admin_token');
            updateCurrentUserDisplay();
        }
    });

    userBadgeBtn.addEventListener('click', openUserPicker);

    // --- Render Units Cards (Step 1) ---
    function renderUnits() {
        unitsGrid.innerHTML = '';
        const iconMap = {
            'Broadcast': '📡',
            'Archive & Transfers': '🗄️',
            'Social Media': '📱',
            'Conductor & Playlists': '🎬',
            'Monitoring & OTT': '📺',
            'R&D Services': '🔬',
            'Other': '📋'
        };

        bootstrapData.units.forEach(unit => {
            const card = document.createElement('div');
            card.className = 'selection-card';
            card.innerHTML = `
                <div class="card-icon">${iconMap[unit.name] || '🏢'}</div>
                <div class="card-title">${unit.name}</div>
                <div class="card-desc">${unit.description || `Log incidents directly under ${unit.name}`}</div>
            `;
            card.addEventListener('click', () => {
                selectUnit(unit);
            });
            unitsGrid.appendChild(card);
        });
    }

    function selectUnit(unit) {
        selectedUnit = unit;
        selectedSection = null;

        if (unit.sections && unit.sections.length > 0) {
            // Unit has child sections -> Go to Step 2
            document.getElementById('step-2-title').innerText = `Select ${unit.name} Section`;
            sectionsGrid.innerHTML = '';
            unit.sections.forEach(sec => {
                const card = document.createElement('div');
                card.className = 'selection-card';
                card.innerHTML = `
                    <div class="card-icon">⚡</div>
                    <div class="card-title">${sec.name}</div>
                    <div class="card-desc">${sec.description || 'Desk/Service incident reporting'}</div>
                `;
                card.addEventListener('click', () => {
                    selectSection(sec);
                });
                sectionsGrid.appendChild(card);
            });

            step1.style.display = 'none';
            step2.style.display = 'block';
            step3.style.display = 'none';
            window.scrollTo({ top: 0, behavior: 'smooth' });
            refreshIcons();
        } else {
            // Direct progression without sub-sections!
            document.getElementById('summary-unit').innerText = selectedUnit.name;
            const secDivider = document.getElementById('summary-section-divider');
            const secSummary = document.getElementById('summary-section');
            if (secDivider) secDivider.style.display = 'none';
            if (secSummary) secSummary.style.display = 'none';
            document.getElementById('summary-reporter').innerText = currentReporter || 'Anonymous';

            renderPresetTags();

            step1.style.display = 'none';
            step2.style.display = 'none';
            step3.style.display = 'block';

            const btnBack = document.getElementById('btn-back-to-step-2');
            const btnBackText = document.getElementById('btn-back-text');
            if (btnBackText) btnBackText.innerText = 'Back to Categories';
            if (btnBack) {
                btnBack.onclick = () => {
                    step3.style.display = 'none';
                    step1.style.display = 'block';
                    window.scrollTo({ top: 0, behavior: 'smooth' });
                };
            }

            window.scrollTo({ top: 0, behavior: 'smooth' });
            setTimeout(() => descTextarea.focus(), 150);
            refreshIcons();
        }
    }

    // Step 2 -> Step 3 (when sections exist)
    function selectSection(sec) {
        selectedSection = sec;
        document.getElementById('summary-unit').innerText = selectedUnit.name;
        const secDivider = document.getElementById('summary-section-divider');
        const secSummary = document.getElementById('summary-section');
        if (secDivider) secDivider.style.display = 'inline';
        if (secSummary) {
            secSummary.style.display = 'inline';
            secSummary.innerText = sec.name;
        }
        document.getElementById('summary-reporter').innerText = currentReporter || 'Anonymous';

        renderPresetTags();

        const btnBackText = document.getElementById('btn-back-text');
        if (btnBackText) btnBackText.innerText = 'Back to Sections';
        const btnBack = document.getElementById('btn-back-to-step-2');
        if (btnBack) {
            btnBack.onclick = () => {
                step3.style.display = 'none';
                step2.style.display = 'block';
                window.scrollTo({ top: 0, behavior: 'smooth' });
            };
        }

        step2.style.display = 'none';
        step3.style.display = 'block';
        window.scrollTo({ top: 0, behavior: 'smooth' });
        setTimeout(() => descTextarea.focus(), 150);
        refreshIcons();
    }

    // Navigation back
    document.getElementById('btn-back-to-step-1')?.addEventListener('click', () => {
        step2.style.display = 'none';
        step1.style.display = 'block';
    });

    // Preset Tags & Dynamic Issue Categories (cleanly hidden if none exist)
    function renderPresetTags() {
        const presetsGroup = document.getElementById('presets-group');
        if (!presetsContainer) return;
        presetsContainer.innerHTML = '';
        const allCategories = bootstrapData.issue_categories || [];
        const applicable = allCategories.length > 0
            ? allCategories.filter(c => c.is_active && (!c.unit_id || (selectedUnit && c.unit_id === selectedUnit.id)))
            : (bootstrapData.preset_tags || []).map(t => ({ name: t }));

        if (applicable.length === 0) {
            if (presetsGroup) presetsGroup.style.display = 'none';
            return;
        }

        if (presetsGroup) presetsGroup.style.display = 'block';
        applicable.forEach(cat => {
            const tag = cat.name;
            const chip = document.createElement('span');
            chip.className = 'preset-chip';
            if (activePreset === tag) chip.classList.add('active');
            chip.innerText = tag;
            chip.addEventListener('click', () => {
                if (activePreset === tag) {
                    activePreset = null;
                    chip.classList.remove('active');
                } else {
                    activePreset = tag;
                    document.querySelectorAll('.preset-chip').forEach(c => c.classList.remove('active'));
                    chip.classList.add('active');
                    if (!descTextarea.value.trim()) {
                        descTextarea.value = `${tag}: `;
                    }
                }
            });
            presetsContainer.appendChild(chip);
        });
    }

    // Priority Toggle Handlers
    function setPriority(level) {
        if (!incidentPriorityInput) return;
        incidentPriorityInput.value = level;
        if (btnPrioNormal) {
            btnPrioNormal.classList.toggle('active', level === 'Normal');
        }
        if (btnPrioCritical) {
            btnPrioCritical.classList.toggle('active', level === 'Critical');
        }
    }

    if (btnPrioNormal) {
        btnPrioNormal.addEventListener('click', () => setPriority('Normal'));
    }
    if (btnPrioCritical) {
        btnPrioCritical.addEventListener('click', () => setPriority('Critical'));
    }

    // Extra Mentions Multi-Column Cards Grid
    function updateMentionsCounter() {
        if (mentionsCounter) {
            const count = selectedMentionIds.size;
            mentionsCounter.innerText = `${count} selected`;
        }
    }

    function renderExtraMentionsList() {
        if (!mentionsGrid) return;
        mentionsGrid.innerHTML = '';

        (bootstrapData.users || []).forEach(u => {
            const card = document.createElement('div');
            const isSelected = selectedMentionIds.has(u.id);
            card.className = `mention-card ${isSelected ? 'selected' : ''}`;
            card.setAttribute('data-id', u.id);
            card.innerHTML = `
                <span>${u.name}</span>
                <span class="check-marker">✓</span>
            `;

            card.addEventListener('click', () => {
                if (selectedMentionIds.has(u.id)) {
                    selectedMentionIds.delete(u.id);
                    card.classList.remove('selected');
                } else {
                    selectedMentionIds.add(u.id);
                    card.classList.add('selected');
                }
                updateMentionsCounter();
            });

            mentionsGrid.appendChild(card);
        });

        updateMentionsCounter();
    }

    if (btnSelectAllMentions) {
        btnSelectAllMentions.addEventListener('click', () => {
            (bootstrapData.users || []).forEach(u => selectedMentionIds.add(u.id));
            if (mentionsGrid) {
                mentionsGrid.querySelectorAll('.mention-card').forEach(c => c.classList.add('selected'));
            }
            updateMentionsCounter();
        });
    }

    if (btnClearMentions) {
        btnClearMentions.addEventListener('click', () => {
            selectedMentionIds.clear();
            if (mentionsGrid) {
                mentionsGrid.querySelectorAll('.mention-card').forEach(c => c.classList.remove('selected'));
            }
            updateMentionsCounter();
        });
    }

    // Form Submission
    incidentForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        if (!currentReporter) {
            openUserPicker();
            return;
        }

        const description = descTextarea.value.trim();
        if (!description) {
            alert("Please provide a description of the incident.");
            descTextarea.focus();
            return;
        }

        const priority = incidentPriorityInput ? incidentPriorityInput.value : 'Normal';
        const extraMentions = Array.from(selectedMentionIds);

        const payload = {
            reporter_name: currentReporter,
            unit_id: selectedUnit.id,
            section_id: selectedSection ? selectedSection.id : null,
            preset_tag: activePreset || null,
            description: description,
            priority: priority,
            extra_mention_user_ids: extraMentions
        };

        const submitBtn = document.getElementById('btn-submit-report');
        const origBtnText = submitBtn.innerHTML;
        submitBtn.disabled = true;
        submitBtn.innerHTML = `<span>Dispatching to Telegram...</span>`;

        try {
            const res = await fetch('/api/reports', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (res.ok) {
                const data = await res.json();
                document.getElementById('success-tracking-code').innerText = data.tracking_code;

                step3.style.display = 'none';
                stepSuccess.style.display = 'block';
                incidentForm.reset();
                activePreset = null;
                selectedMentionIds.clear();
                setPriority('Normal');
                renderExtraMentionsList();
                document.querySelectorAll('.preset-chip').forEach(c => c.classList.remove('active'));
                window.scrollTo({ top: 0, behavior: 'smooth' });
            } else {
                const err = await res.json();
                alert("Failed to submit report: " + (err.detail || "Server error"));
            }
        } catch (err) {
            alert("Network error connecting to incident server.");
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = origBtnText;
            refreshIcons();
        }
    });

    // Copy Tracking Code Handler
    document.getElementById('btn-copy-code')?.addEventListener('click', () => {
        const code = document.getElementById('success-tracking-code')?.innerText || '';
        if (!code) return;
        navigator.clipboard.writeText(code).then(() => {
            const label = document.getElementById('copy-code-label');
            if (label) {
                const orig = label.innerText;
                label.innerText = 'Copied to Clipboard! ✓';
                setTimeout(() => { label.innerText = orig; }, 2000);
            }
        }).catch(() => {
            alert(`Tracking Code: ${code}`);
        });
    });

    // Reset wizard
    document.getElementById('btn-report-another')?.addEventListener('click', () => {
        stepSuccess.style.display = 'none';
        step1.style.display = 'block';
        selectedUnit = null;
        selectedSection = null;
        window.scrollTo({ top: 0, behavior: 'smooth' });
    });

    // My Reports
    document.getElementById('btn-view-my-reports')?.addEventListener('click', openMyReportsView);
    document.getElementById('btn-back-to-new-report')?.addEventListener('click', () => {
        viewMyReports.style.display = 'none';
        step1.style.display = 'block';
    });

    async function openMyReportsView() {
        stepSuccess.style.display = 'none';
        step1.style.display = 'none';
        step2.style.display = 'none';
        step3.style.display = 'none';
        viewMyReports.style.display = 'block';

        const listContainer = document.getElementById('my-reports-list');
        listContainer.innerHTML = '<div style="padding: 20px; text-align: center; color: var(--text-muted);">Loading your reports...</div>';

        try {
            const res = await fetch(`/api/reports/my?reporter_name=${encodeURIComponent(currentReporter)}`);
            if (res.ok) {
                const reports = await res.json();
                if (reports.length === 0) {
                    listContainer.innerHTML = `<div style="padding: 30px; text-align: center; background: var(--bg-secondary); border-radius: var(--radius-md); border: 1px solid var(--border-color); color: var(--text-muted);">No reports logged yet under your name.</div>`;
                    return;
                }

                listContainer.innerHTML = reports.map(r => {
                    const time = r.created_at.slice(0, 16).replace('T', ' ');
                    const statusClass = r.status === 'Resolved' ? 'badge-sent' : 'badge-pending';
                    const isCrit = (r.priority || '').toUpperCase() === 'CRITICAL';
                    const prioBadge = isCrit
                        ? `<span class="badge badge-priority-critical" style="font-size: 0.7rem;">🔴 Critical</span>`
                        : `<span class="badge badge-priority-normal" style="font-size: 0.7rem;">🟡 Normal</span>`;

                    const isTg = (r.source || '').toLowerCase() === 'telegram';
                    const sourceBadge = isTg
                        ? `<span class="badge" style="font-size: 0.7rem; background: rgba(14, 165, 233, 0.15); color: #0284c7;"><i data-lucide="bot"></i> Telegram</span>`
                        : `<span class="badge" style="font-size: 0.7rem; background: rgba(16, 185, 129, 0.15); color: #059669;"><i data-lucide="globe"></i> Web</span>`;

                    return `
                        <div style="background: var(--bg-secondary); border: 1px solid var(--border-color); border-radius: var(--radius-md); padding: 16px 18px;">
                            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px; flex-wrap: wrap; gap: 8px;">
                                <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                                    <a href="/reports/${r.id}" target="_blank" style="color: var(--primary); font-size: 1.05rem; font-weight: 700; text-decoration: none;">#${r.tracking_code}</a>
                                    <span class="badge ${statusClass}">${r.status}</span>
                                    ${prioBadge}
                                    ${sourceBadge}
                                    <span class="badge badge-sent" style="font-size: 0.7rem;">PV ${r.telegram_dispatch_status || 'SENT'}</span>
                                </div>
                                <span style="font-size: 0.8rem; color: var(--text-muted);">${time}</span>
                            </div>
                            <div style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 6px;">
                                <strong>${r.unit_name}</strong>${r.section_name && r.section_name !== r.unit_name ? ` / ${r.section_name}` : ''} ${r.preset_tag ? `&bull; <span style="color: var(--primary);">${r.preset_tag}</span>` : ''}
                            </div>
                            <p style="font-size: 0.9rem; color: var(--text-primary); unicode-bidi: plaintext; line-height: 1.45; word-break: break-word;">${r.description}</p>
                        </div>
                    `;
                }).join('');
            }
        } catch (e) {
            listContainer.innerHTML = '<div style="color: var(--rose); padding: 20px;">Error loading reports history.</div>';
        }
        refreshIcons();
    }

    // Startup flow
    await loadBootstrap();
    updateCurrentUserDisplay();
    refreshIcons();

    // Check if open_admin query param is requested
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('open_admin') === '1') {
        openUserPicker();
        if (adminCardTopBtn) {
            adminCardTopBtn.click();
        }
    }

    // Check if admin is authenticated in current active session to display shortcut
    const savedToken = sessionStorage.getItem('incident_admin_token');
    if (savedToken) {
        fetch('/api/admin/verify-session', { headers: { 'X-Admin-Token': savedToken } })
            .then(res => {
                if (res.ok) {
                    const header = document.querySelector('.header-actions');
                    if (header && !document.getElementById('btn-header-admin')) {
                        const link = document.createElement('a');
                        link.id = 'btn-header-admin';
                        link.href = '/admin';
                        link.className = 'btn btn-secondary btn-sm';
                        link.style.color = 'var(--amber)';
                        link.style.borderColor = 'rgba(245, 158, 11, 0.4)';
                        link.innerHTML = '<span>🛡️ Admin Panel</span>';
                        header.prepend(link);
                    }
                }
            }).catch(() => {});
    }
});
