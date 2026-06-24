const { app, BrowserWindow, ipcMain, globalShortcut } = require("electron");
const path = require("path");
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
    scriptPath = "python";
  }

  const projectRoot = app.isPackaged
    ? path.dirname(process.execPath)
    : frontendPath;

  const spawnArgs = app.isPackaged
    ? []
    : ["-u", path.join(frontendPath, "main.py")];

  const env = { ...process.env, PROJECT_ROOT: projectRoot };
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

  mainWindow.once("ready-to-show", () => {
    mainWindow.show();
    console.log("[MAIN] Window ready to show");
  });

  // 等后端就绪后再加载页面，确保 origin 为 http://127.0.0.1:8000
  // 这样 /static/ 路径由 FastAPI 的 StaticFiles 正确托管
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

  globalShortcut.register("F12", () => {
    if (mainWindow) mainWindow.webContents.toggleDevTools();
  });
});

let isQuitting = false;

app.on("before-quit", (event) => {
  if (isQuitting) return;
  isQuitting = true;
  globalShortcut.unregisterAll();

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
