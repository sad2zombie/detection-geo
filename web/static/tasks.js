// ---- 任务管理页 ----



const STATUS_LABELS = {

    pending: "等待中",

    running: "进行中",

    succeed: "成功",

    completed: "成功",

    partial: "失败",

    failed: "失败",

};



let pollTimer = null;

let currentSearchId = "";
let currentSearchKeyword = "";

function hasActiveSearchFilter() {
    return Boolean(currentSearchId.trim() || currentSearchKeyword.trim());
}

function buildTasksListUrl() {
    const params = new URLSearchParams();
    const tid = currentSearchId.trim();
    const kw = currentSearchKeyword.trim();
    if (tid) params.set("task_id", tid);
    if (kw) params.set("keyword", kw);
    const qs = params.toString();
    return qs ? `/api/tasks?${qs}` : "/api/tasks";
}

let lastTaskList = [];

let platformMap = {};

let dropdownOpen = false;
let pendingDeleteTaskId = "";
let currentViewTaskId = "";



async function api(url, options = {}) {

    if (window.electronAPI && window.electronAPI.apiFetch) {

        return window.electronAPI.apiFetch(url, options);

    }

    const res = await fetch(url, options);

    const data = await res.json().catch(() => ({}));

    return { ok: res.ok, status: res.status, data };

}



function statusLabel(status) {

    return STATUS_LABELS[status] || status || "-";

}



function statusClass(status) {

    if (status === "succeed" || status === "completed") return "task-status-ok";

    if (status === "failed" || status === "partial") return "task-status-fail";

    if (status === "running" || status === "pending") return "task-status-run";

    return "";

}



function suggestTestTaskId(list) {

    let minNeg = 0;

    for (const t of list) {

        const id = String(t.task_id || "").trim();

        if (/^-?\d+$/.test(id)) {

            const n = parseInt(id, 10);

            if (n < minNeg) minNeg = n;

        }

    }

    return String(minNeg - 1);

}



function getSelectedModalPlatforms() {

    return Array.from(document.querySelectorAll("#platform-dropdown-list .platform-dd-cb:checked")).map((cb) => cb.value);

}



function updateDropdownLabel() {

    const labelEl = document.getElementById("platform-dropdown-label");

    const cbs = document.querySelectorAll("#platform-dropdown-list .platform-dd-cb");

    if (!labelEl || !cbs.length) return;



    const checked = Array.from(cbs).filter((cb) => cb.checked);

    if (checked.length === cbs.length) {

        labelEl.textContent = "全部平台";

    } else if (checked.length === 0) {

        labelEl.textContent = "请选择平台";

    } else {

        labelEl.textContent = `已选 ${checked.length} 个平台`;

    }

}



function renderModalPlatformDropdown(platforms) {

    const list = document.getElementById("platform-dropdown-list");

    if (!list) return;



    platformMap = platforms || {};

    list.innerHTML = "";



    Object.keys(platformMap).forEach((key) => {

        const p = platformMap[key];

        if (!p.enabled) return;



        const item = document.createElement("label");

        item.className = "platform-dropdown-item";

        item.innerHTML = `

            <input type="checkbox" value="${key}" class="platform-dd-cb" checked>

            <span class="pcb-icon">${p.icon || "🔗"}</span>

            <span class="pcb-name">${p.name || key}</span>`;

        list.appendChild(item);

    });



    list.querySelectorAll(".platform-dd-cb").forEach((cb) => {

        cb.addEventListener("change", updateDropdownLabel);

    });



    updateDropdownLabel();

}



function setDropdownOpen(open) {

    const panel = document.getElementById("platform-dropdown-panel");

    const trigger = document.getElementById("platform-dropdown-trigger");

    if (!panel || !trigger) return;



    dropdownOpen = open;

    panel.style.display = open ? "block" : "none";

    trigger.classList.toggle("open", open);

}



async function loadPlatforms() {

    try {

        const result = await api("/api/platforms");

        renderModalPlatformDropdown(result.data || {});

    } catch (e) {

        console.warn("加载平台列表失败", e);

    }

}



function showModalMsg(text, type) {

    const el = document.getElementById("modal-create-msg");

    if (!el) return;

    el.style.display = "block";

    el.className = `modal-msg ${type}`;

    el.textContent = text;

}



function hideModalMsg() {

    const el = document.getElementById("modal-create-msg");

    if (el) el.style.display = "none";

}



function showSearchMsg(text, type) {
    const el = document.getElementById("search-task-msg");
    if (!el) return;
    el.style.display = "block";
    el.className = `modal-msg ${type}`;
    el.textContent = text;
}

function hideSearchMsg() {
    const el = document.getElementById("search-task-msg");
    if (el) el.style.display = "none";
}

function updateSearchFilterBar() {
    const bar = document.getElementById("task-filter-bar");
    const label = document.getElementById("task-filter-label");
    if (!bar) return;
    const tid = currentSearchId.trim();
    const kw = currentSearchKeyword.trim();
    if (tid || kw) {
        bar.style.display = "flex";
        const parts = [];
        if (tid) parts.push(`任务 ID：${tid}`);
        if (kw) parts.push(`品牌：${kw}`);
        if (label) label.textContent = `当前筛选 · ${parts.join(" · ")}`;
    } else {
        bar.style.display = "none";
    }
}

function openSearchModal() {
    const modal = document.getElementById("search-task-modal");
    const idInput = document.getElementById("search-task-id-input");
    const kwInput = document.getElementById("search-task-keyword-input");
    if (!modal) return;

    hideSearchMsg();
    if (idInput) idInput.value = currentSearchId || "";
    if (kwInput) kwInput.value = currentSearchKeyword || "";

    modal.style.display = "flex";
    modal.setAttribute("aria-hidden", "false");
    idInput?.focus();
}

function closeSearchModal() {
    const modal = document.getElementById("search-task-modal");
    if (!modal) return;

    modal.style.display = "none";
    modal.setAttribute("aria-hidden", "true");
    hideSearchMsg();
}

async function submitTaskSearch() {
    const idInput = document.getElementById("search-task-id-input");
    const kwInput = document.getElementById("search-task-keyword-input");
    const taskId = (idInput?.value || "").trim();
    const keyword = (kwInput?.value || "").trim();

    if (!taskId && !keyword) {
        showSearchMsg("请至少填写任务 ID 或品牌名其中一项", "error");
        return;
    }

    hideSearchMsg();
    closeSearchModal();
    currentSearchId = taskId;
    currentSearchKeyword = keyword;
    updateSearchFilterBar();
    await loadTaskList();
}

function clearTaskSearch() {
    currentSearchId = "";
    currentSearchKeyword = "";
    updateSearchFilterBar();
    loadTaskList();
}



function openCreateModal() {

    const modal = document.getElementById("create-task-modal");

    const keywordEl = document.getElementById("modal-keyword");

    if (!modal) return;



    hideModalMsg();

    if (keywordEl) keywordEl.value = "";



    document.querySelectorAll("#platform-dropdown-list .platform-dd-cb").forEach((cb) => {

        cb.checked = true;

    });

    updateDropdownLabel();

    setDropdownOpen(false);



    modal.style.display = "flex";

    modal.setAttribute("aria-hidden", "false");

    keywordEl?.focus();

}



function closeCreateModal() {
    const modal = document.getElementById("create-task-modal");
    if (!modal) return;

    modal.style.display = "none";
    modal.setAttribute("aria-hidden", "true");
    setDropdownOpen(false);
    hideModalMsg();
}

function showTaskNotice(msg, isError) {
    const section = document.getElementById("task-detail-section");
    const reportEl = document.getElementById("task-analysis-report");
    if (!section || !reportEl) return;
    const color = isError ? "var(--danger)" : "var(--text-secondary)";
    section.style.display = "block";
    reportEl.innerHTML = `<p style="color:${color};">${escapeHtml(msg)}</p>`;
    section.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function runDetectInBackground(taskId, keyword, platforms) {
    const detectPromise = api("/api/detect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task_id: taskId, keyword, platforms }),
        timeout: 900000,
    });

    setTimeout(() => loadTaskList(), 300);

    try {
        const result = await detectPromise;
        if (!result.ok) {
            const err = result.data?.error || `请求失败 (${result.status})`;
            showTaskNotice(`任务 ${taskId} 创建失败：${err}`, true);
            await loadTaskList();
            return;
        }
        await loadTaskList();
        await showTaskReport(taskId);
    } catch (e) {
        showTaskNotice(`任务 ${taskId} 请求失败：${e.message || "网络错误"}`, true);
        await loadTaskList();
    }
}



async function createTestTask() {
    const keywordEl = document.getElementById("modal-keyword");
    const keyword = (keywordEl?.value || "").trim();
    const taskId = suggestTestTaskId(lastTaskList);
    const platforms = getSelectedModalPlatforms();

    if (!keyword) {
        showModalMsg("请输入品牌关键词", "error");
        return;
    }
    if (!platforms.length) {
        showModalMsg("请至少选择一个平台", "error");
        return;
    }

    closeCreateModal();
    currentSearchId = "";
    currentSearchKeyword = "";
    updateSearchFilterBar();
    const searchIdInput = document.getElementById("search-task-id-input");
    const searchKwInput = document.getElementById("search-task-keyword-input");
    if (searchIdInput) searchIdInput.value = "";
    if (searchKwInput) searchKwInput.value = "";

    runDetectInBackground(taskId, keyword, platforms);
}



async function loadTaskList() {

    const tbody = document.getElementById("task-tbody");

    const url = buildTasksListUrl();
    const filtering = hasActiveSearchFilter();



    try {

        const result = await api(url);

        const data = result.data || {};

        const list = data.list || [];

        lastTaskList = list;
        updateSearchFilterBar();



        if (!list.length) {
            tbody.innerHTML = `<tr><td colspan="6" class="task-empty">${filtering ? "未找到匹配任务" : "暂无任务"}</td></tr>`;
            return;
        }

        tbody.innerHTML = list.map((t) => {
            const canDelete = t.status !== "pending" && t.status !== "running";
            const deleteCell = canDelete
                ? `<button type="button" class="btn btn-sm btn-danger btn-task-delete" data-task-id="${escapeHtml(t.task_id)}" data-keyword="${escapeHtml(t.keyword || "")}">删除</button>`
                : `<span class="task-action-disabled" title="进行中的任务不可删除">—</span>`;
            return `
            <tr class="task-row" data-task-id="${escapeHtml(t.task_id)}">
                <td class="task-id-cell">${escapeHtml(t.task_id)}</td>
                <td>${escapeHtml(t.keyword || "-")}</td>
                <td><span class="task-status ${statusClass(t.status)}">${escapeHtml(statusLabel(t.status))}</span></td>
                <td>${escapeHtml(t.created_at || "-")}</td>
                <td><button type="button" class="btn btn-sm btn-outline btn-task-view" data-task-id="${escapeHtml(t.task_id)}">查看</button></td>
                <td>${deleteCell}</td>
            </tr>`;
        }).join("");

        document.querySelectorAll(".btn-task-view").forEach((btn) => {
            btn.addEventListener("click", (e) => {
                e.stopPropagation();
                showTaskReport(btn.dataset.taskId);
            });
        });

        document.querySelectorAll(".btn-task-delete").forEach((btn) => {
            btn.addEventListener("click", (e) => {
                e.stopPropagation();
                openDeleteModal(btn.dataset.taskId, btn.dataset.keyword);
            });
        });
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="6" class="task-empty">加载失败: ${escapeHtml(e.message)}</td></tr>`;

    }

}



async function showTaskReport(taskId) {
    if (!taskId) return;
    currentViewTaskId = taskId;

    const section = document.getElementById("task-detail-section");

    const reportEl = document.getElementById("task-analysis-report");



    section.style.display = "block";

    reportEl.innerHTML = '<span class="loading"><span class="spinner"></span>加载中...</span>';



    try {

        const result = await api(`/api/tasks/${encodeURIComponent(taskId)}`);

        if (!result.ok && result.data && result.data.error) {

            reportEl.innerHTML = `<p style="color:var(--danger);">${escapeHtml(result.data.error)}</p>`;

            return;

        }



        const task = result.data;

        if (!task) {

            reportEl.innerHTML = '<p style="color:var(--text-secondary);">任务不存在</p>';

            return;

        }



        if (task.status === "pending" || task.status === "running") {

            reportEl.innerHTML = '<p style="color:var(--text-secondary);">任务尚未完成，请稍后再查看。</p>';

            section.scrollIntoView({ behavior: "smooth", block: "nearest" });

            return;

        }



        if (task.status === "failed") {

            const msg = task.error_message || "任务执行失败";

            reportEl.innerHTML = `<p style="color:var(--danger);">${escapeHtml(msg)}</p>`;

            section.scrollIntoView({ behavior: "smooth", block: "nearest" });

            return;

        }



        const reportData = task.result;

        if (!reportData || !reportData.results) {

            reportEl.innerHTML = '<p style="color:var(--text-secondary);">暂无分析结果。</p>';

            return;

        }



        reportEl.innerHTML = window.renderBrandAnalysisReport(reportData);

        section.scrollIntoView({ behavior: "smooth", block: "nearest" });

    } catch (e) {

        reportEl.innerHTML = `<p style="color:var(--danger);">加载失败: ${escapeHtml(e.message)}</p>`;

    }

}



function hideDeleteMsg() {
    const el = document.getElementById("delete-task-msg");
    if (el) el.style.display = "none";
}

function showDeleteMsg(text, type) {
    const el = document.getElementById("delete-task-msg");
    if (!el) return;
    el.style.display = "block";
    el.className = `modal-msg ${type}`;
    el.textContent = text;
}

function openDeleteModal(taskId, keyword) {
    pendingDeleteTaskId = taskId || "";
    const modal = document.getElementById("delete-task-modal");
    const textEl = document.getElementById("delete-confirm-text");
    if (!modal || !pendingDeleteTaskId) return;

    hideDeleteMsg();
    const label = keyword ? `「${keyword}」` : pendingDeleteTaskId;
    if (textEl) {
        textEl.textContent = `确定要删除任务 ${pendingDeleteTaskId}（${label}）吗？此操作不可恢复。`;
    }

    modal.style.display = "flex";
    modal.setAttribute("aria-hidden", "false");
}

function closeDeleteModal() {
    const modal = document.getElementById("delete-task-modal");
    if (!modal) return;
    modal.style.display = "none";
    modal.setAttribute("aria-hidden", "true");
    pendingDeleteTaskId = "";
    hideDeleteMsg();
}

async function confirmDeleteTask() {
    if (!pendingDeleteTaskId) return;

    const taskId = pendingDeleteTaskId;
    const btn = document.getElementById("btn-confirm-delete");
    if (btn) {
        btn.disabled = true;
        btn.textContent = "删除中…";
    }

    try {
        const result = await api(`/api/tasks/${encodeURIComponent(taskId)}`, { method: "DELETE" });
        if (!result.ok) {
            const err = result.data?.error || `删除失败 (${result.status})`;
            showDeleteMsg(err, "error");
            return;
        }

        closeDeleteModal();
        if (currentViewTaskId === taskId) {
            currentViewTaskId = "";
            const section = document.getElementById("task-detail-section");
            if (section) section.style.display = "none";
        }
        await loadTaskList();
    } catch (e) {
        showDeleteMsg(e.message || "网络请求失败", "error");
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = "删除";
        }
    }
}

function escapeHtml(str) {

    return String(str)

        .replace(/&/g, "&amp;")

        .replace(/</g, "&lt;")

        .replace(/>/g, "&gt;")

        .replace(/"/g, "&quot;");

}



function startPolling() {

    if (pollTimer) clearInterval(pollTimer);

    pollTimer = setInterval(loadTaskList, 5000);

}



document.addEventListener("click", async (e) => {

    const a = e.target.closest && e.target.closest("a.profile-link");

    if (!a) return;

    const platform = a.getAttribute("data-platform") || "";

    const url = a.getAttribute("href") || a.href || "";

    if (!platform || !url) return;

    e.preventDefault();

    try {

        await api(`/api/auth/login/${platform}`, {

            method: "POST",

            headers: { "Content-Type": "application/json" },

            body: JSON.stringify({ url }),

        });

    } catch (_) {

        window.open(url, "_blank");

    }

});



document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("btn-open-search-modal").addEventListener("click", openSearchModal);
    document.getElementById("btn-close-search-modal").addEventListener("click", closeSearchModal);
    document.getElementById("btn-cancel-search").addEventListener("click", closeSearchModal);
    document.getElementById("btn-submit-search").addEventListener("click", submitTaskSearch);
    document.getElementById("btn-clear-search").addEventListener("click", clearTaskSearch);
    document.getElementById("search-task-modal").addEventListener("click", (e) => {
        if (e.target.id === "search-task-modal") closeSearchModal();
    });
    document.getElementById("search-task-id-input").addEventListener("keydown", (e) => {
        if (e.key === "Enter") submitTaskSearch();
    });
    document.getElementById("search-task-keyword-input").addEventListener("keydown", (e) => {
        if (e.key === "Enter") submitTaskSearch();
    });

    document.getElementById("btn-open-create-modal").addEventListener("click", openCreateModal);

    document.getElementById("btn-close-create-modal").addEventListener("click", closeCreateModal);

    document.getElementById("btn-cancel-create").addEventListener("click", closeCreateModal);

    document.getElementById("btn-create-task").addEventListener("click", createTestTask);

    document.getElementById("btn-close-delete-modal").addEventListener("click", closeDeleteModal);
    document.getElementById("btn-cancel-delete").addEventListener("click", closeDeleteModal);
    document.getElementById("btn-confirm-delete").addEventListener("click", confirmDeleteTask);
    document.getElementById("delete-task-modal").addEventListener("click", (e) => {
        if (e.target.id === "delete-task-modal") closeDeleteModal();
    });

    document.getElementById("platform-dropdown-trigger").addEventListener("click", (e) => {

        e.stopPropagation();

        setDropdownOpen(!dropdownOpen);

    });



    document.getElementById("platform-dropdown-panel").addEventListener("click", (e) => {

        e.stopPropagation();

    });



    document.getElementById("create-task-modal").addEventListener("click", (e) => {

        if (e.target.id === "create-task-modal") closeCreateModal();

    });



    document.addEventListener("click", (e) => {

        if (!dropdownOpen) return;

        const dropdown = document.getElementById("platform-dropdown");

        if (dropdown && !dropdown.contains(e.target)) {

            setDropdownOpen(false);

        }

    });



    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            const deleteModal = document.getElementById("delete-task-modal");
            const searchModal = document.getElementById("search-task-modal");
            if (deleteModal && deleteModal.style.display !== "none") {
                closeDeleteModal();
            } else if (searchModal && searchModal.style.display !== "none") {
                closeSearchModal();
            } else if (dropdownOpen) {
                setDropdownOpen(false);
            } else {
                closeCreateModal();
            }
        }
    });



    loadPlatforms();

    loadTaskList();

    startPolling();

});

