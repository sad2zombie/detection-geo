// ---- 初始化 ----
let searchResults = [];
// 跨平台登录串行化：同一时刻只能有一个平台在等待登录，其余按钮禁用并提示排队
let loginInFlight = null;   // 当前正在登录的平台 key；null 表示空闲

function setLoginButtonsState() {
    // 登录中：所有按钮禁用；空闲：恢复
    const cards = document.querySelectorAll(".platform-card-item");
    cards.forEach(card => {
        const btn = card.querySelector("button[onclick*='loginPlatform']");
        if (!btn) return;
        if (loginInFlight === null) {
            btn.disabled = false;
            btn.style.opacity = "";
            btn.style.cursor = "";
            btn.title = "";
        } else {
            const cardKey = card.id.replace("platform-card-", "");
            if (cardKey === loginInFlight) {
                btn.disabled = false;
                btn.style.opacity = "";
                btn.style.cursor = "";
                btn.title = "正在登录…";
            } else {
                btn.disabled = true;
                btn.style.opacity = "0.45";
                btn.style.cursor = "not-allowed";
                btn.title = "其他平台正在登录，请等待其完成后再操作（登录流程串行）";
            }
        }
    });
}

// ---- 统一 API 入口（Electron 走 IPC 转发，浏览器直连 fallback） ----
async function api(url, options = {}) {
    if (window.electronAPI && window.electronAPI.apiFetch) {
        return window.electronAPI.apiFetch(url, options);
    }
    const res = await fetch(url, options);
    return { ok: res.ok, status: res.status, data: await res.json() };
}

// ---- 平台选择栏 ----
const PLATFORM_META = [
    { key: "douyin",      name: "抖音",   icon: "🎵" },
    { key: "baidu",       name: "百度",   icon: "🔍" },
    { key: "xiaohongshu", name: "小红书", icon: "📕" },
    { key: "taobao",      name: "淘宝",   icon: "🛒" },
    { key: "jd",          name: "京东",   icon: "📦" },
];

function renderPlatformSelectBar() {
    const bar = document.getElementById("platform-select-bar");
    if (!bar) return;
    const container = document.createElement("div");
    container.style.cssText = "display:flex;flex-wrap:wrap;gap:8px;align-items:center;";
    PLATFORM_META.forEach(p => {
        const label = document.createElement("label");
        label.className = "platform-checkbox";
        label.innerHTML = `
            <input type="checkbox" value="${p.key}" class="platform-cb">
            <span class="pcb-icon">${p.icon}</span>
            <span class="pcb-name">${p.name}</span>`;
        container.appendChild(label);
    });
    const toggleBtn = document.createElement("button");
    toggleBtn.className = "btn btn-sm btn-outline";
    toggleBtn.textContent = "全选/取消";
    toggleBtn.onclick = togglePlatformAll;
    container.appendChild(toggleBtn);
    bar.innerHTML = "";
    bar.appendChild(container);

    // 默认全部选中
    document.querySelectorAll(".platform-cb").forEach(cb => cb.checked = true);
}

function togglePlatformAll() {
    const cbs = document.querySelectorAll(".platform-cb");
    const allChecked = Array.from(cbs).every(cb => cb.checked);
    cbs.forEach(cb => cb.checked = !allChecked);
}

function getSelectedPlatforms() {
    return Array.from(document.querySelectorAll(".platform-cb:checked")).map(cb => cb.value);
}

// ---- Toast提示 ----
function toast(msg, type = "success") {
    const el = document.createElement("div");
    el.className = `toast ${type}`;
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3000);
}

// ---- 登录状态 ----
async function checkAuth(platformKey = null) {
    const container = document.getElementById("auth-status");

    if (platformKey) {
        // 检测单个平台：在该平台卡片上显示loading
        const card = document.getElementById("platform-card-" + platformKey);
        if (card) {
            card.querySelector(".platform-status").innerHTML = '<span class="spinner"></span> 检测中...';
        }
    } else {
        // 检测全部
        container.innerHTML = '<span class="loading"><span class="spinner"></span>正在检测所有平台...</span>';
    }

    try {
        // 手动 🔄 检测 → 强制 refresh=true（走后端真检测）；DOMContentLoaded 走默认缓存
        const refreshParam = "refresh=true";
        const url = platformKey
            ? `/api/auth/status/${platformKey}?${refreshParam}`
            : `/api/auth/status?${refreshParam}`;
        const result = await api(url);
        const data = result.data;
        const results = Array.isArray(data) ? data : [data];

        // 极短延迟避免 spinner 闪一下
        await new Promise(resolve => setTimeout(resolve, 300));

        if (platformKey) {
            // 单个平台：只更新该平台的卡片状态
            updatePlatformCard(results[0]);
        } else {
            // 全部平台：重新渲染所有卡片
            renderPlatformCards(results);
        }
        // 同步登录按钮串行化状态（渲染后必须重设）
        setLoginButtonsState();
        toast(platformKey ? `${results[0]?.platform_name || platformKey} 检测完成` : "全部检测完成");
    } catch (e) {
        if (platformKey) {
            const card = document.getElementById("platform-card-" + platformKey);
            if (card) card.querySelector(".platform-status").innerHTML = '<span style="color:var(--red)">检测失败</span>';
        } else {
            container.innerHTML = '<span style="color:var(--red)">检测失败: ' + e.message + '</span>';
        }
        toast("检测失败: " + e.message, "error");
    }
}

function updatePlatformCard(p) {
    const card = document.getElementById("platform-card-" + p.platform);
    if (!card) return;
    const loggedIn = Boolean(p.isLoggedIn);
    const note = (p.note || "").trim();
    const errorMsg = (p.error || "").trim();
    // 状态行文案：note 是诊断信息，仅作 tooltip；主标题只显示简短状态
    let statusText;
    if (errorMsg) {
        statusText = "检测异常";
    } else if (loggedIn) {
        statusText = "已登录";
    } else {
        statusText = "未登录";
    }
    const statusEl = card.querySelector(".platform-status");
    statusEl.textContent = statusText;
    statusEl.className = `platform-status ${loggedIn ? 'logged-in' : 'logged-out'}`;
    // 鼠标悬停看详情（note=诊断原因 / error=异常），做防御性截断
    const shortNote = note.length > 80 ? note.substring(0, 80) + "…" : note;
    statusEl.title = errorMsg ? `⚠️ ${errorMsg}` : (shortNote || "");
    card.querySelector(".status-dot").className = `status-dot ${loggedIn ? 'on' : 'off'}`;

    // 更新操作按钮：登录按钮始终显示，方便搜索时发现登录态掉了能重新登录
    const actions = card.querySelector(".platform-card-actions");
    const hasLoginBtn = actions.querySelector("button[onclick*='loginPlatform']");
    if (!hasLoginBtn) {
        actions.innerHTML = `<button class="btn btn-sm btn-primary" onclick="loginPlatform('${p.platform}')">🔑 登录</button>`
            + actions.innerHTML;
    }
    // 同步串行化按钮状态（用户当前是否在登录其他平台）
    setLoginButtonsState();
}

function renderPlatformCards(platforms) {
    const container = document.getElementById("auth-status");
    container.innerHTML = platforms.map(p => {
        const loggedIn = Boolean(p.isLoggedIn);
        const note = (p.note || "").trim();
        const errorMsg = (p.error || "").trim();
        // 状态行文案：note 是诊断信息，鼠标悬停看；主标题只显示简短状态
        let statusText;
        if (errorMsg) {
            statusText = "检测异常";
        } else if (loggedIn) {
            statusText = "已登录";
        } else {
            statusText = "未登录";
        }
        const tooltip = errorMsg ? `⚠️ ${errorMsg}` : (note.length > 80 ? note.substring(0, 80) + "…" : note);
        return `
            <div class="platform-card-item" id="platform-card-${p.platform}">
                <div class="platform-card-header">
                    <span class="platform-icon">${p.platform === 'douyin' ? '🎵' : p.platform === 'xiaohongshu' ? '📕' : p.platform === 'taobao' ? '🛒' : p.platform === 'jd' ? '📦' : '🔍'}</span>
                    <span class="platform-name">${p.platform_name || p.platform}</span>
                    <span class="status-dot ${loggedIn ? 'on' : 'off'}"></span>
                    <span class="platform-status ${loggedIn ? 'logged-in' : 'logged-out'}" title="${tooltip.replace(/"/g, '&quot;')}">${statusText}</span>
                </div>
                <div class="platform-card-actions">
                    <button class="btn btn-sm btn-primary" onclick="loginPlatform('${p.platform}')">🔑 登录</button>
                    <button class="btn btn-sm btn-outline" onclick="checkAuth('${p.platform}')">🔄 检测</button>
                </div>
            </div>
        `;
    }).join("")
    + `<div class="btn-row" style="margin-top:12px;">
        <button class="btn btn-outline" onclick="checkAuth()">🔄 检测全部平台</button>
    </div>`;
    // 重渲染后同步串行化按钮状态
    setLoginButtonsState();
}

// 页面加载时拉一次后端状态（lifespan 启动检测已写入 _auth_status_cache，这里是"无脑读缓存"，不启浏览器）
async function loadInitialAuthStatus() {
    try {
        const result = await api("/api/auth/status");
        renderPlatformCards(result.data);
    } catch (e) {
        // 后端没起来/lifespan 还没跑完：直接显示需要登录的占位
        renderPlatformCards([{ platform: "douyin", isLoggedIn: false, note: "后端未就绪" }]);
    }
}

document.addEventListener("DOMContentLoaded", () => {
    loadInitialAuthStatus();   // 只读 lifespan 写入的缓存，不再启浏览器
    renderPlatformSelectBar();
});

async function loginPlatform(key) {
    const nameMap = { douyin: "抖音", baidu: "百度", xiaohongshu: "小红书", taobao: "淘宝", jd: "京东" };
    const name = nameMap[key] || key;
    // 串行化：其他平台正在登录时直接拒绝
    if (loginInFlight !== null && loginInFlight !== key) {
        const busyName = nameMap[loginInFlight] || loginInFlight;
        toast(`${busyName} 正在登录，请等待完成后再操作其他平台`, "warn");
        return;
    }
    loginInFlight = key;
    setLoginButtonsState();

    const card = document.getElementById("platform-card-" + key);
    if (card) {
        card.querySelector(".platform-status").innerHTML = '<span class="spinner"></span> 等待登录...';
    }

    try {
        const result = await api("/api/auth/login/" + key, { method: "POST", timeout: 30000 });
        const data = result.data;
        console.log("[登录结果]", data);
        const pname = data.platform_name || key;
        if (data.success) {
            updatePlatformCard({
                platform: key,
                platform_name: pname,
                isLoggedIn: true,
            });
            toast(`${pname} 登录成功！`);
        } else {
            const errStr = (data.error || "").toLowerCase();
            const cancelled = errStr.includes("closed") || errStr.includes("cancel");
            toast(`${pname} ${cancelled ? "浏览器已关闭" : "登录未完成"}`, "warn");
            if (cancelled) {
                checkAuth(key);
            }
        }
    } catch (e) {
        const isTimeout = e && e.message && e.message.includes("timeout");
        toast(`登录请求${isTimeout ? "超时（30 秒）" : "失败"}: ${isTimeout ? "请刷新页面查看实际状态" : e.message}`, "error");
        checkAuth(key);
    } finally {
        loginInFlight = null;
        setLoginButtonsState();
    }
}

// ---- 搜索 ----
async function startSearch() {
    const keyword = document.getElementById("keyword").value.trim();
    if (!keyword) { toast("请输入品牌关键词", "error"); return; }

    const progressEl = document.getElementById("search-progress");
    const resultSection = document.getElementById("result-section");
    const analyzeRow = document.getElementById("analyze-row");
    const brandAnalysisResult = document.getElementById("brand-analysis-result");

    progressEl.style.display = "block";
    progressEl.innerHTML = '<span class="loading"><span class="spinner"></span>正在打开浏览器搜索，请稍候...</span>';
    resultSection.style.display = "none";
    analyzeRow.style.display = "none";
    searchResults = [];

    try {
        const selectedPlatforms = getSelectedPlatforms();
        if (!selectedPlatforms.length) { toast("请至少选择一个平台", "error"); return; }
        const result = await api("/api/search", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ keyword: keyword, platforms: selectedPlatforms }),
        });
        const data = result.data;

    progressEl.style.display = "none";
    searchResults = Array.isArray(data) ? data : [data];
    renderResults(searchResults);
    resultSection.style.display = "block";
    analyzeRow.style.display = "block";
    // 品牌匹配分析结果区域默认隐藏，搜索后重新显示（先清空旧内容）
    brandAnalysisResult.style.display = "none";
    brandAnalysisResult.innerHTML = "";
} catch (e) {
        progressEl.innerHTML = '<div class="progress-item error">❌ 搜索请求失败: ' + e.message + '</div>';
    }
}

function renderResults(results) {
    const container = document.getElementById("search-results");
    container.innerHTML = results.map(r => {
        const allUsers = r.users || [];
        const visibleUsers = allUsers.slice(0, 5);
        const hiddenCount = allUsers.length - 5;
        const error = r.error ? `<div class="progress-item error">⚠️ ${r.error}</div>` : "";
        const userCards = visibleUsers.map(u => {
            const v = u.verification || "unknown";
            return `
                <div class="user-card">
                    <div class="user-name">
                        ${u.name || "(无名称)"}
                        <span class="verify-badge verify-${v}">${getVerifyLabel(v, u.verify_type)}</span>
                        ${u.is_private ? '<span class="private-badge">私密</span>' : ''}
                    </div>
                    ${u.xhs_id ? `<div class="user-meta"><span>小红书号: ${u.xhs_id}</span></div>` : ''}
                    ${(u.follower_count || u.note_count) ? `<div class="user-meta">${u.follower_count ? `<span>粉丝: ${u.follower_count}</span>` : ''}${u.note_count ? `<span>笔记: ${u.note_count}</span>` : ''}</div>` : ''}
                    ${u.description ? `<div class="user-desc">${u.description}</div>` : ''}
                    ${u.profile_url ? `<div class="user-link"><a href="${u.profile_url}" target="_blank">${u.profile_url.length > 60 ? u.profile_url.substring(0, 60) + '...' : u.profile_url}</a></div>` : ''}
                </div>
            `;
        }).join("");
        const platformKey = (r.platform || '').replace(/[^a-z0-9]/gi, '_');
        const hiddenSection = hiddenCount > 0
            ? `<div class="hidden-users" id="hidden-users-${platformKey}" style="display:none">
                ${allUsers.slice(5).map(u => {
                    const v = u.verification || "unknown";
                    return `<div class="user-card">
                        <div class="user-name">
                            ${u.name || "(无名称)"}
                            <span class="verify-badge verify-${v}">${getVerifyLabel(v, u.verify_type)}</span>
                            ${u.is_private ? '<span class="private-badge">私密</span>' : ''}
                        </div>
                        ${u.xhs_id ? `<div class="user-meta"><span>小红书号: ${u.xhs_id}</span></div>` : ''}
                        ${(u.follower_count || u.note_count) ? `<div class="user-meta">${u.follower_count ? `<span>粉丝: ${u.follower_count}</span>` : ''}${u.note_count ? `<span>笔记: ${u.note_count}</span>` : ''}</div>` : ''}
                        ${u.description ? `<div class="user-desc">${u.description}</div>` : ''}
                        ${u.profile_url ? `<div class="user-link"><a href="${u.profile_url}" target="_blank">${u.profile_url.length > 60 ? u.profile_url.substring(0, 60) + '...' : u.profile_url}</a></div>` : ''}
                    </div>`;
                }).join("")}
               </div>
               <button class="btn btn-sm btn-outline" onclick="toggleHiddenUsers('${platformKey}', this)">
                   查看更多 (${hiddenCount})
               </button>`
            : '';

        return `
            <div class="platform-result">
                <h3>${r.platform_name || r.platform} (${r.total_found}条结果)</h3>
                ${error}
                ${userCards || '<div class="user-card" style="color:var(--text-secondary)">暂无搜索结果</div>'}
                ${hiddenSection}
            </div>
        `;
    }).join("");
}

function toggleHiddenUsers(platformKey, btn) {
    const el = document.getElementById("hidden-users-" + platformKey);
    if (!el) return;
    if (el.style.display === "none") {
        el.style.display = "";
        btn.textContent = "收起";
    } else {
        el.style.display = "none";
        const platform = platformKey.replace(/_/g, '');
        const allResults = window.searchResults || [];
        for (const r of allResults) {
            if ((r.platform || '').replace(/[^a-z0-9]/gi, '_') === platformKey) {
                btn.textContent = `查看更多 (${Math.max(0, (r.users || []).length - 5)})`;
                break;
            }
        }
        if (btn.textContent.includes("查看更多")) {
            const currentText = btn.textContent;
            btn.textContent = currentText.includes("(") ? "查看更多 " + currentText.match(/\((\d+)\)/)[0] : "查看更多";
        }
    }
}

function getVerifyLabel(verification, verifyType) {
    if (verifyType) {
        return verifyType;
    }
    return verification || "未知";
}

// ---- 品牌匹配分析 ----
async function startBrandAnalysis() {
    const resultEl = document.getElementById("brand-analysis-result");
    resultEl.style.display = "block";
    resultEl.innerHTML = '<span class="loading"><span class="spinner"></span>加载中...</span>';
    try {
        const result = await api("/api/analyze_brand");
        const data = result.data;
        if (!data.results || data.results.length === 0) {
            resultEl.innerHTML = '<p style="color:var(--text-secondary)">暂无分析结果，请先进行搜索。</p>';
            return;
        }
        let html = "";
        if (data.brand) {
            html += `<p style="margin-bottom:16px;color:var(--text-secondary);">品牌: <strong>${data.brand}</strong> &nbsp; Task ID: ${data.task_id}</p>`;
        }

        for (const r of data.results) {
            const p = r.platform;

            if (p === "douyin" && r.users && r.users.length > 0) {
                html += `<h3 style="margin-top:24px;">🔍 抖音蓝V账号（粉丝排名前3）</h3>`;
                html += `<table style="width:100%; border-collapse:collapse;">
                    <thead><tr style="text-align:left; border-bottom:1px solid var(--border);"><th style="padding:8px;">#</th><th style="padding:8px;">名称</th><th style="padding:8px;">抖音号</th><th style="padding:8px;">主页链接</th></tr></thead>
                    <tbody>`;
                r.users.forEach((u, i) => {
                    html += `<tr>
                        <td style="padding:8px;">${i + 1}</td>
                        <td style="padding:8px;">${u.name || "-"}</td>
                        <td style="padding:8px;">${u.douyin_id || "-"}</td>
                        <td style="padding:8px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${u.profile_url ? `<a href="${u.profile_url}" target="_blank">${u.profile_url}</a>` : "-"}</td>
                    </tr>`;
                });
                html += `</tbody></table>`;
            } else if (p === "douyin") {
                html += `<h3 style="margin-top:24px;">🔍 抖音蓝V账号（粉丝排名前3）</h3>`;
                html += `<p style="color:var(--text-secondary);padding:8px 0;">无</p>`;
            }

            if (p === "xiaohongshu" && r.users && r.users.length > 0) {
                html += `<h3 style="margin-top:24px;">🔍 小红书企业认证账号（粉丝排名前3）</h3>`;
                html += `<table style="width:100%; border-collapse:collapse;">
                    <thead><tr style="text-align:left; border-bottom:1px solid var(--border);"><th style="padding:8px;">#</th><th style="padding:8px;">名称</th><th style="padding:8px;">小红书号</th><th style="padding:8px;">主页链接</th></tr></thead>
                    <tbody>`;
                r.users.forEach((u, i) => {
                    html += `<tr>
                        <td style="padding:8px;">${i + 1}</td>
                        <td style="padding:8px;">${u.name || "-"}</td>
                        <td style="padding:8px;">${u.xhs_id || "-"}</td>
                        <td style="padding:8px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${u.profile_url ? `<a href="${u.profile_url}" target="_blank">${u.profile_url}</a>` : "-"}</td>
                    </tr>`;
                });
                html += `</tbody></table>`;
            } else if (p === "xiaohongshu") {
                html += `<h3 style="margin-top:24px;">🔍 小红书企业认证账号（粉丝排名前3）</h3>`;
                html += `<p style="color:var(--text-secondary);padding:8px 0;">无</p>`;
            }

            if (p === "baidu") {
                html += `<h3 style="margin-top:24px;">🔍 品牌匹配分析（百度）</h3>`;
                html += `<table style="width:100%; border-collapse:collapse;">
                    <thead><tr style="text-align:left; border-bottom:1px solid var(--border);"><th style="padding:8px;">平台</th><th style="padding:8px;">匹配得分</th><th style="padding:8px;">评价</th></tr></thead>
                    <tbody><tr><td>${r.platform}</td><td>${r.score ?? "-"}</td><td>${r.assessment_grade || "-"}</td></tr></tbody></table>`;
            }

            if (p === "jd") {
                html += `<h3 style="margin-top:24px;">🔍 京东官方旗舰店</h3>`;
                if (r.name) {
                    html += `<table style="width:100%; border-collapse:collapse;">
                        <thead><tr style="text-align:left; border-bottom:1px solid var(--border);"><th style="padding:8px;">店铺名称</th><th style="padding:8px;">店铺链接</th></tr></thead>
                        <tbody><tr>
                            <td style="padding:8px;">${r.name}</td>
                            <td style="padding:8px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${r.profile_url ? `<a href="${r.profile_url}" target="_blank">${r.profile_url}</a>` : "-"}</td>
                        </tr></tbody></table>`;
                } else {
                    html += `<p style="color:var(--text-secondary);padding:8px 0;">无</p>`;
                }
            }

            if (p === "taobao") {
                html += `<h3 style="margin-top:24px;">🔍 淘宝官方旗舰店</h3>`;
                if (r.name) {
                    html += `<table style="width:100%; border-collapse:collapse;">
                        <thead><tr style="text-align:left; border-bottom:1px solid var(--border);"><th style="padding:8px;">店铺名称</th><th style="padding:8px;">店铺链接</th></tr></thead>
                        <tbody><tr>
                            <td style="padding:8px;">${r.name}</td>
                            <td style="padding:8px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${r.profile_url ? `<a href="${r.profile_url}" target="_blank">${r.profile_url}</a>` : "-"}</td>
                        </tr></tbody></table>`;
                } else {
                    html += `<p style="color:var(--text-secondary);padding:8px 0;">无</p>`;
                }
            }
        }

        resultEl.innerHTML = html;
    } catch (e) {
        resultEl.innerHTML = `<p style="color:#e74c3c;">加载失败: ${e.message}</p>`;
    }
}