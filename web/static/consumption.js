// ---- 消费日志页 ----

let pollTimer = null;

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

function statusClass(status) {
    if (status === "成功") return "consumption-status-ok";
    if (status === "失败") return "consumption-status-fail";
    if (status === "入库") return "consumption-status-in";
    return "";
}

async function loadPollStatus() {
    const el = document.getElementById("consumption-status-text");
    if (!el) return;
    try {
        const result = await api("/api/consumption/status");
        const s = result.data || {};
        if (!s.configured) {
            el.textContent =
                "远端未配置：请设置 CONSUMPTION_FETCH_URL（拉取任务）、KAFKA_BOOTSTRAP_SERVERS、KAFKA_RESULT_TOPIC（Kafka 回传）。配置后后台将每 "
                + (s.poll_interval || 10)
                + " 秒自动拉取。";
            return;
        }
        const busyNote = s.local_busy ? " · 本地任务执行中，暂不向服务器拉取" : "";
        const pollNote = s.poll_in_progress ? " · 消费任务处理中，暂不再拉取" : "";
        const onOff = s.poll_enabled ? "已开启" : "已关闭";
        el.textContent =
            `轮询${onOff} · 间隔 ${s.poll_interval}s · 拉取: ${s.fetch_url} · Kafka: ${s.kafka_bootstrap}/${s.kafka_result_topic}${busyNote}${pollNote}`;
    } catch (e) {
        el.textContent = `配置加载失败: ${e.message}`;
    }
}

async function loadLogs() {
    const tbody = document.getElementById("consumption-tbody");
    try {
        const result = await api("/api/consumption/logs");
        const list = result.data?.list || [];
        if (!list.length) {
            tbody.innerHTML = '<tr><td colspan="3" class="task-empty">暂无消费日志</td></tr>';
            return;
        }
        tbody.innerHTML = list
            .map(
                (row) => `
            <tr>
                <td>${escapeHtml(row.time || "-")}</td>
                <td class="task-id-cell">${escapeHtml(row.task_id || "-")}</td>
                <td><span class="consumption-status ${statusClass(row.status)}">${escapeHtml(row.status || "-")}</span></td>
            </tr>`
            )
            .join("");
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="3" class="task-empty">加载失败: ${escapeHtml(e.message)}</td></tr>`;
    }
}

async function pollOnce() {
    const btn = document.getElementById("btn-poll-once");
    if (btn) {
        btn.disabled = true;
        btn.textContent = "拉取中…";
    }
    try {
        const result = await api("/api/consumption/poll", { method: "POST" });
        const data = result.data || {};
        if (data.fetched && data.task_id) {
            console.info("[消费拉取]", data);
        }
        await loadLogs();
    } catch (e) {
        console.error(e);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = "立即拉取";
        }
    }
}

function startPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(() => {
        loadLogs();
        loadPollStatus();
    }, 5000);
}

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("btn-poll-once").addEventListener("click", pollOnce);
    loadPollStatus();
    loadLogs();
    startPolling();
});
