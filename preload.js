const { contextBridge, ipcRenderer } = require("electron");

// 暴露给前端的安全 API
contextBridge.exposeInMainWorld("electronAPI", {
  // 当前 Electron 环境版本号（未来扩展用）
  getVersion: () => require("electron").app.getVersion(),

  // 通过主进程转发 HTTP 请求到 Python 后端（loadFile 后无法直接 fetch）
  apiFetch: (url, options = {}) => ipcRenderer.invoke("api-fetch", url, options),

  // 监听后端就绪事件（后台轮询成功后触发）
  onBackendReady: (callback) => {
    ipcRenderer.on("backend-ready", callback);
    return () => ipcRenderer.removeListener("backend-ready", callback);
  },

  // 完全重启 Electron + Python 后端（让 server.py 改动生效）
  reloadApp: () => ipcRenderer.invoke("reload-app"),
});
