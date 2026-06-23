// ---- 初始化 ----
let searchResults = [];

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

// Toast提示
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
        const res = await fetch(url);
        const data = await res.json();
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
}

// 页面加载时拉一次后端状态（lifespan 启动检测已写入 _auth_status_cache，这里是"无脑读缓存"，不启浏览器）
async function loadInitialAuthStatus() {
    try {
        const res = await fetch("/api/auth/status");
        const platforms = await res.json();
        renderPlatformCards(platforms);
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
    const card = document.getElementById("platform-card-" + key);
    if (card) {
        card.querySelector(".platform-status").innerHTML = '<span class="spinner"></span> 等待登录...';
    }

    // 兜底：30 秒内后端没回也强制结束 spinner，避免用户关掉浏览器后无限转圈
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 30000);

    try {
        const res = await fetch("/api/auth/login/" + key, { method: "POST", signal: controller.signal });
        clearTimeout(timeoutId);
        const data = await res.json();
        const pname = data.platform_name || key;
        if (data.success) {
            // 登录成功 → 服务端 __cloak_saved=true 时已 close() 浏览器
            // 这里不再触发检测，直接把卡片切到"已登录"（保底零延迟）
            updatePlatformCard({
                platform: key,
                platform_name: pname,
                isLoggedIn: true,
            });
            toast(`${pname} 登录成功！`);
        } else {
            // 失败：不展示技术异常给用户。
            // Playwright 在浏览器被关时抛 "Target page, context or browser has been closed"，
            // 识别为"用户主动取消"，其他归为"登录未完成"。
            const errStr = (data.error || "").toLowerCase();
            const cancelled = errStr.includes("closed") || errStr.includes("cancel");
            toast(`${pname} ${cancelled ? "浏览器已关闭" : "登录未完成"}`, "warn");
            // 浏览器已关闭：用户可能已经保存了 profile，去后端确认一下真实状态
            if (cancelled) {
                checkAuth(key);
            }
        }
    } catch (e) {
        clearTimeout(timeoutId);
        const isAbort = e && e.name === "AbortError";
        toast(`登录请求${isAbort ? "超时（30 秒）" : "失败"}: ${isAbort ? "请刷新页面查看实际状态" : e.message}`, "error");
        checkAuth(key);
    }
}

// ---- 搜索 ----
async function startSearch() {
    const keyword = document.getElementById("keyword").value.trim();
    if (!keyword) { toast("请输入品牌关键词", "error"); return; }

    const progressEl = document.getElementById("search-progress");
    const resultSection = document.getElementById("result-section");
    const analyzeRow = document.getElementById("analyze-row");

    progressEl.style.display = "block";
    progressEl.innerHTML = '<span class="loading"><span class="spinner"></span>正在打开浏览器搜索，请稍候...</span>';
    resultSection.style.display = "none";
    document.getElementById("report-section").style.display = "none";
    document.getElementById("analyze-progress").style.display = "none";
    analyzeRow.style.display = "none";
    searchResults = [];

    try {
        const selectedPlatforms = getSelectedPlatforms();
        if (!selectedPlatforms.length) { toast("请至少选择一个平台", "error"); return; }
        const res = await fetch("/api/search", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ keyword: keyword, platforms: selectedPlatforms }),
        });
        const data = await res.json();

        progressEl.style.display = "none";
        searchResults = Array.isArray(data) ? data : [data];
        renderResults(searchResults);
        resultSection.style.display = "block";
        analyzeRow.style.display = "block";
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
        const res = await fetch("/api/analyze_brand");
        const data = await res.json();
        if (Object.keys(data).length === 0) {
            resultEl.innerHTML = '<p style="color:var(--text-secondary)">暂无分析结果，请先进行搜索。</p>';
            return;
        }
        let html = "";

        if (data.baidu) {
            html += `
                <h3>🔍 品牌匹配分析（百度）</h3>
                <table style="width:100%; border-collapse:collapse;">
                    <thead><tr style="text-align:left; border-bottom:1px solid var(--border);"><th style="padding:8px;">平台</th><th style="padding:8px;">匹配得分</th><th style="padding:8px;">认证等级</th></tr></thead>
                    <tbody><tr><td>${data.baidu.platform || "baidu"}</td><td>${data.baidu.score ?? "-"}</td><td>${data.baidu.assessment_grade || "-"}</td></tr></tbody>
                </table>`;
        }

        if (data.douyin && data.douyin.blue_v_users && data.douyin.blue_v_users.length > 0) {
            html += `<h3 style="margin-top:24px;">🔍 抖音蓝V账号（粉丝排名前3）</h3>`;
            html += `<table style="width:100%; border-collapse:collapse;">
                <thead><tr style="text-align:left; border-bottom:1px solid var(--border);"><th style="padding:8px;">#</th><th style="padding:8px;">名称</th><th style="padding:8px;">抖音号</th><th style="padding:8px;">主页链接</th></tr></thead>
                <tbody>`;
            data.douyin.blue_v_users.forEach((u, i) => {
                html += `<tr>
                    <td style="padding:8px;">${i + 1}</td>
                    <td style="padding:8px;">${u.name || "-"}</td>
                    <td style="padding:8px;">${u.douyin_id || "-"}</td>
                    <td style="padding:8px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${u.profile_url ? `<a href="${u.profile_url}" target="_blank">${u.profile_url}</a>` : "-"}</td>
                </tr>`;
            });
            html += `</tbody></table>`;
        }

        if (data.xiaohongshu && data.xiaohongshu.enterprise_users && data.xiaohongshu.enterprise_users.length > 0) {
            html += `<h3 style="margin-top:24px;">🔍 小红书企业认证账号（粉丝排名前3）</h3>`;
            html += `<table style="width:100%; border-collapse:collapse;">
                <thead><tr style="text-align:left; border-bottom:1px solid var(--border);"><th style="padding:8px;">#</th><th style="padding:8px;">名称</th><th style="padding:8px;">小红书号</th><th style="padding:8px;">主页链接</th></tr></thead>
                <tbody>`;
            data.xiaohongshu.enterprise_users.forEach((u, i) => {
                html += `<tr>
                    <td style="padding:8px;">${i + 1}</td>
                    <td style="padding:8px;">${u.name || "-"}</td>
                    <td style="padding:8px;">${u.xhs_id || "-"}</td>
                    <td style="padding:8px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${u.profile_url ? `<a href="${u.profile_url}" target="_blank">${u.profile_url}</a>` : "-"}</td>
                </tr>`;
            });
            html += `</tbody></table>`;
        }

        if (data.jd) {
            html += `<h3 style="margin-top:24px;">🔍 京东官方旗舰店</h3>`;
            if (data.jd.name) {
                html += `<table style="width:100%; border-collapse:collapse;">
                    <thead><tr style="text-align:left; border-bottom:1px solid var(--border);"><th style="padding:8px;">店铺名称</th><th style="padding:8px;">店铺链接</th></tr></thead>
                    <tbody><tr>
                        <td style="padding:8px;">${data.jd.name}</td>
                        <td style="padding:8px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${data.jd.profile_url ? `<a href="${data.jd.profile_url}" target="_blank">${data.jd.profile_url}</a>` : "-"}</td>
                    </tr></tbody></table>`;
            } else {
                html += `<p style="color:var(--text-secondary);padding:8px 0;">无</p>`;
            }
        }

        if (data.taobao) {
            html += `<h3 style="margin-top:24px;">🔍 淘宝官方旗舰店</h3>`;
            if (data.taobao.name) {
                html += `<table style="width:100%; border-collapse:collapse;">
                    <thead><tr style="text-align:left; border-bottom:1px solid var(--border);"><th style="padding:8px;">店铺名称</th><th style="padding:8px;">店铺链接</th></tr></thead>
                    <tbody><tr>
                        <td style="padding:8px;">${data.taobao.name}</td>
                        <td style="padding:8px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${data.taobao.profile_url ? `<a href="${data.taobao.profile_url}" target="_blank">${data.taobao.profile_url}</a>` : "-"}</td>
                    </tr></tbody></table>`;
            } else {
                html += `<p style="color:var(--text-secondary);padding:8px 0;">无</p>`;
            }
        }

        resultEl.innerHTML = html;
    } catch (e) {
        resultEl.innerHTML = `<p style="color:#e74c3c;">加载失败: ${e.message}</p>`;
    }
}

// ---- AI 分析 ----
async function startAnalysis() {
    const keyword = document.getElementById("keyword").value.trim();
    if (!searchResults.length) { toast("请先搜索品牌", "error"); return; }

    const progressEl = document.getElementById("analyze-progress");
    const reportSection = document.getElementById("report-section");
    const reportContent = document.getElementById("report-content");

    progressEl.style.display = "block";
    progressEl.innerHTML = '<span class="loading"><span class="spinner"></span>AI正在分析...</span>';
    reportSection.style.display = "none";

    try {
        const res = await fetch("/api/analyze", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ brand: keyword, results: searchResults }),
        });
        const data = await res.json();

        progressEl.style.display = "none";
        reportSection.style.display = "block";

        if (data.success) {
            reportContent.innerHTML = markdownToHtml(data.report);
            reportSection.scrollIntoView({ behavior: "smooth" });
        } else {
            reportContent.innerHTML = `<div style="color:var(--red)">AI分析失败: ${data.error}</div>`;
        }
    } catch (e) {
        progressEl.style.display = "none";
        reportSection.style.display = "block";
        reportContent.innerHTML = `<div style="color:var(--red)">请求失败: ${e.message}</div>`;
    }
}

// 简单的 Markdown → HTML
function markdownToHtml(md) {
    return md
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/^### (.+)$/gm, "<h3>$1</h3>")
        .replace(/^## (.+)$/gm, "<h2>$1</h2>")
        .replace(/^# (.+)$/gm, "<h1>$1</h1>")
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        .replace(/- (.+)/g, "• $1")
        .replace(/\n/g, "<br>");
}