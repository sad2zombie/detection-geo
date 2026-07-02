// ── 单例限制：在加载 Electron 模块之前用文件锁检查，避免第二个实例有任何窗口闪烁 ──
const _lockFile = require("path").join(
  require("os").tmpdir(),
  "detection-app-single.lock"
);
try {
  const _fs = require("fs");
  // 检查是否已有实例在运行
  try {
    const existingPid = parseInt(_fs.readFileSync(_lockFile, "utf8"), 10);
    // 检查 PID 是否仍然存活
    process.kill(existingPid, 0);  // 信号 0 = 不实际发信号，只检查是否存在
    // PID 存活，已有实例在运行 → 写信号文件通知第一个实例聚焦窗口，然后立即退出
    const _signalFile = _lockFile + ".focus";
    _fs.writeFileSync(_signalFile, String(Date.now()));
    process.exit(0);
  } catch (_) {
    // PID 不存在（进程已死）或文件不存在，清理旧锁文件
    try { _fs.unlinkSync(_lockFile); } catch (__) {}
  }
  // 创建新锁文件
  const fd = _fs.openSync(_lockFile, "wx");
  _fs.writeSync(fd, String(process.pid));
  _fs.closeSync(fd);
  // 进程退出时清理锁文件
  process.on("exit", () => { try { _fs.unlinkSync(_lockFile); } catch (_) {} });
  process.on("SIGINT", () => { try { _fs.unlinkSync(_lockFile); } catch (_) {} process.exit(); });
  process.on("SIGTERM", () => { try { _fs.unlinkSync(_lockFile); } catch (_) {} process.exit(); });
} catch (_) {
  // 其他异常情况不影响正常启动
}

const { app, BrowserWindow, ipcMain } = require("electron"); // 移除了 globalShortcut
const path = require("path");
const fs = require("fs");
const http = require("http");
const { spawn, exec } = require("child_process");

let pyProc = null;
let mainWindow = null;
let backendPort = null;

// ============================================================================
// Windows 控制台直接写 UTF-8（绕过 console.log 的系统代码页限制）
// ============================================================================
let _consoleWrite;
if (process.platform === "win32") {
  _consoleWrite = (text, isError) => {
    try {
      // CONOUT$ 以 UTF-8 编码打开
      const fd = isError ? 2 : 1;
      require("fs").writeSync(fd, Buffer.from(text, "utf8"));
    } catch (_) {
      if (isError) process.stderr.write(text);
      else process.stdout.write(text);
    }
  };
} else {
  _consoleWrite = (text, isError) => {
    if (isError) process.stderr.write(text);
    else process.stdout.write(text);
  };
}

const _log  = (text) => _consoleWrite(text + "\n", false);
const _elog = (text) => _consoleWrite(text + "\n", true);

// ============================================================================
// 打包内置 .env — 构建时打入安装包，启动时注入后端进程（目标机开箱即用）
// ============================================================================
function parseEnvFile(text) {
  const out = {};
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq <= 0) continue;
    const key = trimmed.slice(0, eq).trim();
    let val = trimmed.slice(eq + 1).trim();
    if (
      (val.startsWith('"') && val.endsWith('"'))
      || (val.startsWith("'") && val.endsWith("'"))
    ) {
      val = val.slice(1, -1);
    }
    if (key) out[key] = val;
  }
  return out;
}

function getBundledEnvPath() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "packaged.env");
  }
  return path.join(__dirname, "config", "packaged.env");
}

function ensureAppDataEnvFile(sourcePath) {
  const appDataBase = process.env.APPDATA
    || path.join(app.getPath("home"), "AppData", "Roaming");
  const targetDir = path.join(appDataBase, "detection");
  const targetFile = path.join(targetDir, ".env");
  try {
    fs.mkdirSync(targetDir, { recursive: true });
    if (!fs.existsSync(targetFile) && fs.existsSync(sourcePath)) {
      fs.copyFileSync(sourcePath, targetFile);
      _log("[MAIN] Initialized user .env from packaged template: " + targetFile);
    }
  } catch (e) {
    _elog("[MAIN] Failed to initialize user .env: " + e.message);
  }
}

function loadPackagedEnv() {
  const envPath = getBundledEnvPath();
  ensureAppDataEnvFile(envPath);
  if (!fs.existsSync(envPath)) {
    _log("[MAIN] No packaged.env at: " + envPath);
    return {};
  }
  try {
    const parsed = parseEnvFile(fs.readFileSync(envPath, "utf8"));
    const keys = Object.keys(parsed);
    _log("[MAIN] Loaded packaged.env (" + keys.length + " keys) from: " + envPath);
    return parsed;
  } catch (e) {
    _elog("[MAIN] Failed to read packaged.env: " + e.message);
    return {};
  }
}

// ============================================================================
// 启动 Python 后端
// ============================================================================
function createPyProc(frontendPath) {
  let scriptPath;

  if (app.isPackaged) {
    scriptPath = path.join(process.resourcesPath, "detection-backend-exe.exe");
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

  const env = {
    ...process.env,
    PYTHONIOENCODING: "utf-8",
    PYTHONUTF8: "1",
    PROJECT_ROOT: projectRoot,
    DETECTION_DATA_DIR: dataDir,
    DETECTION_APP_VERSION: require("./package.json").version || "1.0.0",
    ...loadPackagedEnv(),
  };
  const spawnOpts = app.isPackaged
    ? { env, stdio: ["ignore", "pipe", "pipe"], detached: false, windowsHide: true }
    : { env, stdio: ["ignore", "pipe", "pipe"], detached: false };

  pyProc = spawn(scriptPath, spawnArgs, spawnOpts);
  _log("[MAIN] Backend process spawned, PID: " + pyProc.pid);

  pyProc.stdout.on("data", (data) => _log(data.toString("utf8").trimEnd()));
  pyProc.stderr.on("data", (data) => _elog(data.toString("utf8").trimEnd()));

  pyProc.on("error", (err) => {
    _elog("[MAIN] Backend spawn error: " + err.message);
  });

  pyProc.on("exit", (code, signal) => {
    _log("[MAIN] Backend exited. Code: " + code + " Signal: " + signal);
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
  // 外部链接用系统浏览器打开，内部链接 deny
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    // http/https 外部链接 → 系统浏览器打开
    if (url.startsWith("http://") || url.startsWith("https://")) {
      require("electron").shell.openExternal(url);
    }
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
      event.preventDefault();
      _log('[MAIN] F12 pressed (window-internal)');
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
      _log('[MAIN] Reload (ignore cache)');
    }
  });

  mainWindow.once("ready-to-show", () => {
    mainWindow.show();
    _log("[MAIN] Window ready to show");
  });

  // 等后端就绪后再加载页面，确保 origin 为 http://127.0.0.1:8000
  backendPort = await waitForBackend(60000);
  const pageUrl = `http://127.0.0.1:${backendPort}`;
  await mainWindow.loadURL(pageUrl);
  _log("[MAIN] Loaded " + pageUrl);
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
          _log("[MAIN] Backend ready after ~" + Math.round((Date.now() - startTime) / 1000) + "s");
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
  _log("[MAIN] reload-app requested, relaunching...");
  // 先杀后端，再让 before-quit 走 relaunch
  isQuitting = true;
  if (pyProc) {
    try {
      exec("taskkill /F /IM detection-backend-exe.exe", () => {});
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
  exec("taskkill /F /IM detection-backend-exe.exe", (err) => {
    // taskkill 找不到进程时的 GBK 乱码无需显示，静默忽略

    if (pyProc && pyProc.pid) {
      exec(`taskkill /F /T /PID ${pyProc.pid}`, (err2) => {
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
// 单例限制：只允许运行一个实例
// ============================================================================
const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  app.quit();
  process.exit(0);
} else {
  app.on("second-instance", (event, commandLine, workingDirectory) => {
    // 有人尝试启动第二个实例，聚焦已有窗口
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });
}

// ============================================================================
// Electron 应用生命周期
// ============================================================================
app.on("ready", async () => {
  if (!gotTheLock) return;  // 第二个实例直接跳过，不创建窗口
  _log("[MAIN] app.on(ready)");
  _log("[MAIN] isPackaged: " + app.isPackaged + " | appPath: " + app.getAppPath());

  const frontendPath = app.getAppPath();

  createPyProc(frontendPath);
  await createWindow(frontendPath);

  // ===== 监听第二个实例的聚焦信号 =====
  const _signalFile = _lockFile + ".focus";
  _log("[MAIN] Watching signal file: " + _signalFile);
  setInterval(() => {
    try {
      if (fs.existsSync(_signalFile)) {
        fs.unlinkSync(_signalFile);
        _log("[MAIN] Second instance detected, focusing window");
        if (mainWindow) {
          if (mainWindow.isMinimized()) mainWindow.restore();
          mainWindow.show();
          mainWindow.moveTop();
          mainWindow.focus();
        }
      }
    } catch (e) {
      _log("[MAIN] Signal watcher error: " + e.message);
    }
  }, 500);

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
      _log("[MAIN] Backend killed, quitting...");
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