// AI-Systems Desktop — startet beim Öffnen automatisch den eingebetteten
// AI-Systems-Server (mitgeliefertes Python unter resources/runtime/) und lädt
// dann die Oberfläche. Alternativ verbindet sich die App mit einem externen
// Server („Datei → Einstellungen…"). Ein Doppelklick startet wirklich alles.
const { app, BrowserWindow, Menu, ipcMain, shell } = require('electron');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const EMBEDDED_PORT = 8010;
const EMBEDDED_URL = `http://127.0.0.1:${EMBEDDED_PORT}`;
let mainWindow = null;
let settingsWindow = null;
let serverProcess = null;

function configPath() {
  return path.join(app.getPath('userData'), 'ai-systems.json');
}

function loadSettings() {
  const defaults = { useEmbedded: true, serverUrl: EMBEDDED_URL };
  try {
    return { ...defaults, ...JSON.parse(fs.readFileSync(configPath(), 'utf8')) };
  } catch {
    return defaults;
  }
}

function saveSettings(settings) {
  fs.mkdirSync(app.getPath('userData'), { recursive: true });
  fs.writeFileSync(configPath(), JSON.stringify(settings, null, 2), 'utf8');
}

function effectiveUrl() {
  const s = loadSettings();
  return s.useEmbedded ? EMBEDDED_URL : s.serverUrl;
}

/* --- Eingebetteter Server --------------------------------------------------- */

// Optionale Server-Konfiguration (N8N_URL, ANTHROPIC_API_KEY, …) als KEY=VALUE-
// Zeilen; ohne Einträge läuft der Server automatisch im Demo-Modus.
function envFilePath() {
  return path.join(app.getPath('userData'), 'ai-systems.env');
}

function ensureEnvFile() {
  if (fs.existsSync(envFilePath())) return;
  fs.mkdirSync(app.getPath('userData'), { recursive: true });
  fs.writeFileSync(envFilePath(), [
    '# AI-Systems Server-Konfiguration (KEY=VALUE pro Zeile).',
    '# Ohne Eintraege laeuft der eingebettete Server im DEMO-Modus.',
    '# Fuer den echten Betrieb z. B.:',
    '# N8N_URL=https://n8n.example.com',
    '# N8N_API_KEY=...',
    '# ANTHROPIC_API_KEY=...',
    '# Claude-Modell (Standard: claude-fable-5). Falls dein API-Key ein anderes',
    '# Modell verlangt, hier umstellen, z. B.:',
    '# AI_SYSTEMS_MODEL=claude-sonnet-4-20250514',
    '# ERPNEXT_URL=... / ERPNEXT_API_KEY=... / ERPNEXT_API_SECRET=...',
    '# AZURE_CLIENT_ID=... / AZURE_CLIENT_SECRET=... / AZURE_TENANT_ID=...',
    '# GITHUB_TOKEN=... / UPS_CLIENT_ID=... / UPS_CLIENT_SECRET=...',
    '',
  ].join('\r\n'), 'utf8');
}

function readEnvFile() {
  const env = {};
  try {
    for (const line of fs.readFileSync(envFilePath(), 'utf8').split(/\r?\n/)) {
      const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/);
      if (m && !line.trim().startsWith('#')) env[m[1]] = m[2];
    }
  } catch { /* keine Datei -> Demo-Modus */ }
  return env;
}

// Runtime-Verzeichnis: im Installationspaket unter resources/runtime, bei
// "npm start" (Entwicklung) lokal unter electron/runtime.
function runtimeDir() {
  const packaged = path.join(process.resourcesPath || '', 'runtime');
  if (fs.existsSync(packaged)) return packaged;
  const dev = path.join(__dirname, 'runtime');
  return fs.existsSync(dev) ? dev : null;
}

function startEmbeddedServer() {
  if (serverProcess) return;
  const rt = runtimeDir();
  const appDir = rt ? path.join(rt, 'app') : path.join(__dirname, '..', '..');
  const winPython = rt ? path.join(rt, 'python', 'python.exe') : null;
  // Windows: mitgeliefertes Python. Entwicklung auf Linux/macOS: System-Python.
  const [cmd, baseArgs] = process.platform === 'win32' && winPython && fs.existsSync(winPython)
    ? [winPython, ['-X', 'utf8']]
    : ['python3', []];

  ensureEnvFile();
  const logFile = path.join(app.getPath('userData'), 'server.log');
  const log = fs.openSync(logFile, 'a');
  fs.writeSync(log, `\n--- Serverstart ${new Date().toISOString()} (${cmd}) ---\n`);

  try {
    serverProcess = spawn(cmd, [...baseArgs, '-m', 'uvicorn', 'ai_systems.app:app',
      '--host', '127.0.0.1', '--port', String(EMBEDDED_PORT), '--log-level', 'warning'], {
      cwd: appDir,
      env: {
        ...process.env,
        ...readEnvFile(),
        AI_SYSTEMS_DB: path.join(app.getPath('userData'), 'ai_systems.db'),
        PYTHONUNBUFFERED: '1',
      },
      stdio: ['ignore', log, log],
      windowsHide: true,
    });
    serverProcess.on('exit', (code) => {
      fs.writeSync(log, `--- Server beendet (Code ${code}) ---\n`);
      serverProcess = null;
    });
    serverProcess.on('error', (err) => {
      fs.writeSync(log, `--- Serverstart fehlgeschlagen: ${err.message} ---\n`);
      serverProcess = null;
    });
  } catch (err) {
    fs.writeSync(log, `--- Serverstart fehlgeschlagen: ${err.message} ---\n`);
    serverProcess = null;
  }
}

function stopEmbeddedServer() {
  if (!serverProcess) return;
  try { serverProcess.kill(); } catch { /* schon beendet */ }
  serverProcess = null;
}

function syncEmbeddedServer() {
  if (loadSettings().useEmbedded) startEmbeddedServer();
  else stopEmbeddedServer();
}

/* --- Fenster ----------------------------------------------------------------- */

function showLoader(win) {
  if (!win || win.isDestroyed()) return;
  // setImmediate: nie synchron aus einem Navigations-Event heraus neu laden —
  // das ließ Electron segfaulten (App schloss sich beim Verbindungsversuch).
  setImmediate(() => {
    if (win.isDestroyed()) return;
    win.loadFile(path.join(__dirname, 'loader.html'),
      { query: { url: effectiveUrl() } }).catch(() => {});
  });
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    title: 'AI-Systems',
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  // Start IMMER über die lokale Loader-Seite: sie pingt den Server per fetch()
  // und leitet erst bei Erfolg weiter. So schlägt die Fenster-Navigation im
  // Normalfall nie fehl. Falls doch (Server stirbt später), zurück zum Loader —
  // errorCode -3 (ERR_ABORTED) sind eigene Navigationen und werden ignoriert.
  mainWindow.webContents.on('did-fail-load', (_e, errorCode, _desc, _url, isMainFrame) => {
    if (!isMainFrame || errorCode === -3) return;
    showLoader(mainWindow);
  });
  showLoader(mainWindow);
  mainWindow.on('closed', () => { mainWindow = null; });
}

function openSettings() {
  if (settingsWindow) { settingsWindow.focus(); return; }
  settingsWindow = new BrowserWindow({
    width: 480,
    height: 320,
    title: 'Einstellungen',
    parent: mainWindow || undefined,
    resizable: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, 'preload.js'),
    },
  });
  settingsWindow.setMenuBarVisibility(false);
  settingsWindow.loadFile(path.join(__dirname, 'settings.html'));
  settingsWindow.on('closed', () => { settingsWindow = null; });
}

function normalizeUrl(raw) {
  const url = String(raw || '').trim() || EMBEDDED_URL;
  return /^https?:\/\//i.test(url) ? url : 'http://' + url;
}

ipcMain.handle('settings:get', () => loadSettings());
ipcMain.handle('settings:set', (_event, settings) => {
  saveSettings({
    useEmbedded: settings.useEmbedded !== false,
    serverUrl: normalizeUrl(settings.serverUrl),
  });
  syncEmbeddedServer();
  showLoader(mainWindow);
  return loadSettings();
});

app.whenReady().then(() => {
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    {
      label: 'Datei',
      submenu: [
        { label: 'Einstellungen…', accelerator: 'CmdOrCtrl+,', click: openSettings },
        {
          label: 'Server-Konfiguration (.env) öffnen',
          click: () => { ensureEnvFile(); shell.showItemInFolder(envFilePath()); },
        },
        {
          label: 'Server-Protokoll öffnen',
          click: () => shell.openPath(path.join(app.getPath('userData'), 'server.log')),
        },
        { type: 'separator' },
        { label: 'Neu laden', accelerator: 'CmdOrCtrl+R', click: () => mainWindow && mainWindow.reload() },
        { type: 'separator' },
        { role: 'quit', label: 'Beenden' },
      ],
    },
    {
      label: 'Ansicht',
      submenu: [
        { role: 'zoomIn', label: 'Vergrößern' },
        { role: 'zoomOut', label: 'Verkleinern' },
        { role: 'resetZoom', label: 'Standardgröße' },
        { type: 'separator' },
        { role: 'togglefullscreen', label: 'Vollbild' },
      ],
    },
  ]));
  syncEmbeddedServer();
  createMainWindow();
  app.on('activate', () => { if (!mainWindow) createMainWindow(); });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('will-quit', stopEmbeddedServer);
