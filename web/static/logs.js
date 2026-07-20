// ---- 运行日志页 ----

let autoScroll = true;
let lastTotal = 0;       // 上次已知的总行数
let pollTimer = null;    // 自动轮询定时器
const POLL_INTERVAL = 2000; // 2 秒轮询一次

async function api(url, options = {}) {
    if (window.electronAPI && window.electronAPI.apiFetch) {
        return window.electronAPI.apiFetch(url, options);
    }
    const res = await fetch(url, options);
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok, status: res.status, data };
}

function escapeHtml(str) {
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

/**
 * 给日志行着色：根据关键词匹配不同颜色。
 */
function colorizeLine(line) {
    const escaped = escapeHtml(line);

    // 分隔线
    if (/^=+$/.test(line.trim())) {
        return `<span class="log-sep">${escaped}</span>`;
    }

    // 错误 / 异常
    if (/\b(异常|失败|错误|ERROR|Exception|Traceback|Error)\b/i.test(line)) {
        return `<span class="log-error">${escaped}</span>`;
    }

    // 成功 / 完成
    if (/\b(成功|完成|启动|命中|预热|已通过|succeed)\b/i.test(line)) {
        return `<span class="log-success">${escaped}</span>`;
    }

    // 警告 / 冷却 / 拦截
    if (/\b(警告|拦截|冷却|超时|跳过|重试|WARN|timeout|blocked)\b/i.test(line)) {
        return `<span class="log-warn">${escaped}</span>`;
    }

    // 平台标签
    if (/\[(Baidu|Bing|Bocha|Douyin|XHS|Taobao|JD|Brand|Search|Auth|Kafka|Consumption|Browser)\b/i.test(line)) {
        return `<span class="log-info">${escaped}</span>`;
    }

    return `<span>${escaped}</span>`;
}

/**
 * 全量渲染（首次加载或切换行数时用）。
 */
function renderLogs(lines, total) {
    const viewer = document.getElementById("log-viewer");
    const infoText = document.getElementById("log-info-text");

    if (!lines || lines.length === 0) {
        viewer.innerHTML = '<span style="color:var(--text-dim)">暂无日志</span>';
        infoText.textContent = "日志文件为空";
        lastTotal = 0;
        return;
    }

    // 最新日志在最上面
    const reversed = [...lines].reverse();
    const html = reversed.map(colorizeLine).join("\n");
    viewer.innerHTML = html;
    infoText.textContent = `共 ${total} 行，当前显示末尾 ${lines.length} 行（最新在上）`;
    lastTotal = total;

    viewer.scrollTop = 0;
}

/**
 * 增量追加新日志到顶部（轮询时用）。
 */
function prependNewLines(newLines) {
    if (!newLines || newLines.length === 0) return;

    const viewer = document.getElementById("log-viewer");
    const infoText = document.getElementById("log-info-text");

    // 新日志反转后拼到现有内容前面
    const reversed = [...newLines].reverse();
    const newHtml = reversed.map(colorizeLine).join("\n");

    if (viewer.textContent.trim() === "暂无日志") {
        viewer.innerHTML = newHtml;
    } else {
        viewer.innerHTML = newHtml + "\n" + viewer.innerHTML;
    }

    lastTotal += newLines.length;
    infoText.textContent = `共 ${lastTotal} 行（最新在上，自动刷新中）`;

    // 自动滚动模式下保持顶部
    if (autoScroll) {
        viewer.scrollTop = 0;
    }
}

/**
 * 首次全量加载。
 */
async function loadLogs() {
    stopPoll(); // 切换行数时先停掉旧轮询
    const select = document.getElementById("log-lines-select");
    const lines = parseInt(select.value, 10) || 500;

    const res = await api(`/api/logs?lines=${lines}`);
    if (res.data && res.data.lines) {
        renderLogs(res.data.lines, res.data.total);
        startPoll();
    } else if (res.data && res.data.error) {
        document.getElementById("log-viewer").innerHTML =
            `<span class="log-error">${escapeHtml(res.data.error)}</span>`;
    }
}

/**
 * 轮询增量更新：只拉取新增的行。
 */
async function pollNewLogs() {
    if (lastTotal <= 0) return;

    // 请求比上次多出的行数（多取一点防止边界问题）
    const fetchCount = Math.max(50, 200);
    const res = await api(`/api/logs?lines=${fetchCount}`);
    if (!res.data || !res.data.lines) return;

    const newTotal = res.data.total;
    if (newTotal <= lastTotal) return; // 没有新日志

    // 新增的行 = 返回的末尾 (newTotal - lastTotal) 条
    const newCount = newTotal - lastTotal;
    const newLines = res.data.lines.slice(-newCount);
    prependNewLines(newLines);
}

function startPoll() {
    if (pollTimer) return;
    pollTimer = setInterval(pollNewLogs, POLL_INTERVAL);
}

function stopPoll() {
    if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
    }
}

// ---- 事件绑定 ----

document.addEventListener("DOMContentLoaded", () => {
    loadLogs();

    document.getElementById("btn-refresh-logs").addEventListener("click", loadLogs);

    document.getElementById("log-lines-select").addEventListener("change", loadLogs);

    document.getElementById("btn-auto-scroll").addEventListener("click", () => {
        autoScroll = !autoScroll;
        const btn = document.getElementById("btn-auto-scroll");
        btn.textContent = `自动滚动: ${autoScroll ? "开" : "关"}`;
        if (autoScroll) {
            const viewer = document.getElementById("log-viewer");
            viewer.scrollTop = 0;
        }
    });

    // 用户手动滚动时暂时关闭自动滚动
    const viewer = document.getElementById("log-viewer");
    viewer.addEventListener("scroll", () => {
        const atTop = viewer.scrollTop < 30;
        if (!atTop && autoScroll) {
            autoScroll = false;
            document.getElementById("btn-auto-scroll").textContent = "自动滚动: 关";
        }
    });

    // 页面不可见时暂停轮询，恢复后继续
    document.addEventListener("visibilitychange", () => {
        if (document.hidden) {
            stopPoll();
        } else if (lastTotal > 0) {
            startPoll();
            pollNewLogs(); // 切回来立刻拉一次
        }
    });
});
