// AI-Systems Desktop — dünner Electron-Wrapper um die Web-App.
// Lädt die Server-URL aus einer kleinen Config-Datei im userData-Verzeichnis;
// „Einstellungen…" im Menü öffnet ein Formular zum Ändern der URL.
const { app, BrowserWindow, Menu, ipcMain } = require('electron');
const fs = require('fs');
const path = require('path');

const DEFAULT_URL = 'http://localhost:8010';
let mainWindow = null;
let settingsWindow = null;

function configPath() {
  return path.join(app.getPath('userData'), 'ai-systems.json');
}

function loadSettings() {
  try {
    return { serverUrl: DEFAULT_URL, ...JSON.parse(fs.readFileSync(configPath(), 'utf8')) };
  } catch {
    return { serverUrl: DEFAULT_URL };
  }
}

function saveSettings(settings) {
  fs.mkdirSync(app.getPath('userData'), { recursive: true });
  fs.writeFileSync(configPath(), JSON.stringify(settings, null, 2), 'utf8');
}

function showLoader(win) {
  if (!win || win.isDestroyed()) return;
  // setImmediate: nie synchron aus einem Navigations-Event heraus neu laden —
  // das ließ Electron segfaulten (App schloss sich beim Verbindungsversuch).
  setImmediate(() => {
    if (win.isDestroyed()) return;
    win.loadFile(path.join(__dirname, 'loader.html'),
      { query: { url: loadSettings().serverUrl } }).catch(() => {});
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
    width: 460,
    height: 240,
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
  const url = String(raw || '').trim() || DEFAULT_URL;
  return /^https?:\/\//i.test(url) ? url : 'http://' + url;
}

ipcMain.handle('settings:get', () => loadSettings());
ipcMain.handle('settings:set', (_event, settings) => {
  saveSettings({ serverUrl: normalizeUrl(settings.serverUrl) });
  showLoader(mainWindow);
  return loadSettings();
});

app.whenReady().then(() => {
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    {
      label: 'Datei',
      submenu: [
        { label: 'Einstellungen…', accelerator: 'CmdOrCtrl+,', click: openSettings },
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
  createMainWindow();
  app.on('activate', () => { if (!mainWindow) createMainWindow(); });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
