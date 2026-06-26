const { app, BrowserWindow, ipcMain } = require("electron"); // 移除了 globalShortcut
const path = require("path");
const fs = require("fs");
const http = require("http");
const { spawn } = require("child_process");

let pyProc = null;
let mainWindow = null;
let backendPort = null;

// ============================================================================
// 启动 Python 后端
// ============================================================================
function createPyProc(frontendPath) {
  let scriptPath;

  if (app.isPackaged) {
    scriptPath = path.join(process.resourcesPath, "backend-exe.exe");
  } else {
    scriptPath = "C:\\Users\\pyproject_ENV\\browser\\Scripts\\python.exe";
  }

  const projectRoot = app.isPackaged
    ? path.dirname(process.execPath)
    : frontendPath;

  const spawnArgs = app.isPackaged
    ? []
    : ["-u", path.join(frontendPath, "main.py")];

  // 数据目录：打包模式下放 %APPDATA%/detection/data/，登录态持久保留
  let dataDir;
  if (app.isPackaged) {
    const appDataBase = process.env.APPDATA || path.join(app.getPath("home"), "AppData", "Roaming");
    dataDir = path.join(appDataBase, "detection", "data");
  } else {
    dataDir = path.join(projectRoot, "data");
  }
  // 确保目录存在（首次启动自动创建）
  try { fs.mkdirSync(path.join(dataDir, "cookies"), { recursive: true }); } catch (_) {}
  try { fs.mkdirSync(path.join(dataDir, "results"), { recursive: true }); } catch (_) {}

  const env = { ...process.env, PROJECT_ROOT: projectRoot, DETECTION_DATA_DIR: dataDir };
  const spawnOpts = app.isPackaged
    ? { env, stdio: ["ignore", "pipe", "pipe"], detached: false, windowsHide: true }
    : { env, stdio: ["ignore", "pipe", "pipe"], detached: false };

  pyProc = spawn(scriptPath, spawnArgs, spawnOpts);
  console.log("[MAIN] Backend process spawned, PID:", pyProc.pid);

  pyProc.stdout.on("data", (data) => process.stdout.write(data));
  pyProc.stderr.on("data", (data) => process.stderr.write(data));

  pyProc.on("error", (err) => {
    console.error("[MAIN] Backend spawn error:", err.message);
  });

  pyProc.on("exit", (code, signal) => {
    console.log("[MAIN] Backend exited. Code:", code, "Signal:", signal);
    pyProc = null;
  });
}

// ============================================================================
// 创建窗口（等后端就绪后再加载页面，确保 origin 一致）
// ============================================================================
async function createWindow(frontendPath) {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      nodeIntegration: false,
      contextIsolation: true,
    },
    backgroundColor: "#0f1117",
    show: true,
  });

  mainWindow.setMenu(null);

  // ===== 阻止 <a target="_blank"> / window.open 开新 BrowserWindow =====
  // 点击搜索结果里的 profile 链接由前端拦截器转给后端 BrowserContext 处理，
  // 这里统一 deny，避免 Electron 默认开一个不带登录态的小窗口。
  mainWindow.webContents.setWindowOpenHandler(() => {
    return { action: "deny" };
  });
  // 兜底：旧式 new-window 事件
  mainWindow.webContents.on("new-window", (event) => {
    event.preventDefault();
  });

  // ===== 改动1：只在开发环境自动打开 DevTools =====
  if (!app.isPackaged) {
    mainWindow.webContents.openDevTools({ mode: "detach" });
  }

  // ===== 改动2：窗口内 F12 监听（替代 globalShortcut） =====
  mainWindow.webContents.on('before-input-event', (event, input) => {
    if (input.key === 'F12' && input.type === 'keyDown') {
      mainWindow.webContents.toggleDevTools();
      event.preventDefault(); // 阻止系统默认行为
      console.log('[MAIN] F12 pressed (window-internal)');
    }
  });

  // Ctrl+R / F5 强刷 webview（绕过缓存；注意：不会重启后端 Python 进程，
  // 如要重启后端请调 ipc 'reload-app' → app.relaunch）
  mainWindow.webContents.on('before-input-event', (event, input) => {
    if (input.type !== 'keyDown') return;
    const isReload = input.key === 'F5' || (input.key === 'r' && (input.control || input.meta));
    if (isReload) {
      mainWindow.webContents.reloadIgnoringCache();
      event.preventDefault();
      console.log('[MAIN] Reload (ignore cache)');
    }
  });

  mainWindow.once("ready-to-show", () => {
    mainWindow.show();
    console.log("[MAIN] Window ready to show");
  });

  // 等后端就绪后再加载页面，确保 origin 为 http://127.0.0.1:8000
  backendPort = await waitForBackend(60000);
  const pageUrl = `http://127.0.0.1:${backendPort}`;
  await mainWindow.loadURL(pageUrl);
  console.log("[MAIN] Loaded " + pageUrl);
}

// ============================================================================
// 等待后端端口就绪
// ============================================================================
function waitForBackend(maxWaitMs) {
  return new Promise((resolve, reject) => {
    const startTime = Date.now();
    const interval = 500;

    function tryPing() {
      const req = http.get("http://127.0.0.1:8000", (res) => {
        if (res.statusCode === 200) {
          console.log("[MAIN] Backend ready after ~" + Math.round((Date.now() - startTime) / 1000) + "s");
          resolve(8000);
        } else {
          scheduleNext();
        }
      });
      req.on("error", scheduleNext);
      req.setTimeout(1000, () => { req.destroy(); scheduleNext(); });
    }

    function scheduleNext() {
      if (Date.now() - startTime >= maxWaitMs) {
        reject(new Error("Backend did not become ready within " + maxWaitMs / 1000 + "s"));
        return;
      }
      setTimeout(tryPing, interval);
    }

    tryPing();
  });
}

// ============================================================================
// 完全重启 Electron（含 Python 后端子进程）：用于让 server.py 改动生效
// ============================================================================
ipcMain.handle("reload-app", async () => {
  console.log("[MAIN] reload-app requested, relaunching...");
  // 先杀后端，再让 before-quit 走 relaunch
  isQuitting = true;
  if (pyProc) {
    try {
      const { exec } = require("child_process");
      exec("taskkill /F /IM backend-exe.exe", () => {});
      if (pyProc.pid) {
        exec(`taskkill /F /T /PID ${pyProc.pid}`, () => {});
      }
    } catch (_) {}
  }
  app.relaunch();
  app.exit(0);
  return { ok: true };
});

// ============================================================================
// 转发前端 HTTP 请求到 Python 后端（loadURL 后仍走 IPC 转发以保持一致）
// ============================================================================
ipcMain.handle("api-fetch", async (event, url, options = {}) => {
  if (!backendPort) {
    throw new Error("Backend not ready");
  }
  return new Promise((resolve, reject) => {
    const urlObj = new URL(url, `http://127.0.0.1:${backendPort}`);
    const reqOptions = {
      hostname: "127.0.0.1",
      port: backendPort,
      path: urlObj.pathname + urlObj.search,
      method: options.method || "GET",
      headers: options.headers || {},
    };

    const req = http.request(reqOptions, (res) => {
      let body = "";
      res.on("data", (chunk) => { body += chunk; });
      res.on("end", () => {
        try {
          resolve({ ok: true, status: res.statusCode, data: JSON.parse(body) });
        } catch (_) {
          resolve({ ok: true, status: res.statusCode, data: body });
        }
      });
    });

    req.on("error", reject);

    if (options.timeout) {
      req.setTimeout(options.timeout, () => {
        req.destroy();
        reject(new Error("Request timeout"));
      });
    }

    if (options.body) {
      req.write(options.body);
    }
    req.end();
  });
});

// ============================================================================
// 关闭后端进程
// ============================================================================
function killBackendProcess(callback) {
  const { exec } = require("child_process");

  exec("taskkill /F /IM backend-exe.exe", (err) => {
    if (err) console.log("[MAIN] taskkill backend-exe.exe:", err.message);

    if (pyProc && pyProc.pid) {
      exec(`taskkill /F /T /PID ${pyProc.pid}`, (err2) => {
        if (err2) console.log("[MAIN] taskkill by PID:", err2.message);
        pyProc = null;
        if (callback) callback();
      });
    } else {
      pyProc = null;
      if (callback) callback();
    }
  });
}

// ============================================================================
// Electron 应用生命周期
// ============================================================================
app.on("ready", async () => {
  console.log("[MAIN] app.on(ready)");
  console.log("[MAIN] isPackaged:", app.isPackaged, "| appPath:", app.getAppPath());

  const frontendPath = app.getAppPath();

  createPyProc(frontendPath);
  await createWindow(frontendPath);

  // ===== 移除了 globalShortcut 注册 =====
});

let isQuitting = false;

app.on("before-quit", (event) => {
  if (isQuitting) return;
  isQuitting = true;

  // ===== 移除了 globalShortcut.unregisterAll() =====

  if (pyProc) {
    event.preventDefault();
    killBackendProcess(() => {
      console.log("[MAIN] Backend killed, quitting...");
      app.quit();
    });
    setTimeout(() => { app.exit(0); }, 5000);
  }
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("activate", async () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    const frontendPath = app.getAppPath();
    await createWindow(frontendPath);
  }
});