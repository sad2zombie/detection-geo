// ---- 终端信息页 ----

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

function showDeviceNameMsg(text, type) {
    const el = document.getElementById("device-name-msg");
    if (!el) return;
    el.style.display = "block";
    el.className = `terminal-inline-msg ${type}`;
    el.textContent = text;
}

function hideDeviceNameMsg() {
    const el = document.getElementById("device-name-msg");
    if (el) el.style.display = "none";
}

function renderTerminalInfo(info) {
    document.getElementById("terminal-id").textContent = info.terminal_id || "-";
    document.getElementById("app-version").textContent = info.version || "-";
    const input = document.getElementById("device-name-input");
    if (input) input.value = info.device_name || "";
}

async function loadTerminalInfo() {
    const loading = document.getElementById("terminal-loading");
    const content = document.getElementById("terminal-content");

    try {
        const result = await api("/api/terminal");
        if (!result.ok) {
            loading.innerHTML = `<span style="color:var(--danger);">加载失败</span>`;
            return;
        }
        renderTerminalInfo(result.data || {});
        loading.style.display = "none";
        content.style.display = "block";
    } catch (e) {
        loading.innerHTML = `<span style="color:var(--danger);">加载失败: ${escapeHtml(e.message)}</span>`;
    }
}

async function saveDeviceName() {
    const input = document.getElementById("device-name-input");
    const btn = document.getElementById("btn-save-device-name");
    const name = (input?.value || "").trim();

    if (!name) {
        showDeviceNameMsg("设备名称不能为空", "error");
        return;
    }

    hideDeviceNameMsg();
    if (btn) {
        btn.disabled = true;
        btn.textContent = "保存中…";
    }

    try {
        const result = await api("/api/terminal", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ device_name: name }),
        });

        if (!result.ok) {
            showDeviceNameMsg(result.data?.error || "保存失败", "error");
            return;
        }

        renderTerminalInfo(result.data || {});
        showDeviceNameMsg("设备名称已保存", "success");
    } catch (e) {
        showDeviceNameMsg(e.message || "网络请求失败", "error");
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = "保存";
        }
    }
}

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("btn-save-device-name").addEventListener("click", saveDeviceName);
    document.getElementById("device-name-input").addEventListener("keydown", (e) => {
        if (e.key === "Enter") saveDeviceName();
    });
    loadTerminalInfo();
});
