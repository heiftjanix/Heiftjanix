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

function errorPage(url) {
  const html = `<!doctype html><html lang="de"><meta charset="utf-8">
    <body style="font-family:system-ui;background:#12181f;color:#e8edf2;
      display:flex;align-items:center;justify-content:center;height:95vh;text-align:center">
    <div><h2>Server nicht erreichbar</h2>
    <p>AI-Systems unter <code>${url}</code> antwortet nicht.<br>
    Bitte die Server-URL im Menü unter „Datei → Einstellungen…" prüfen.</p></div></body></html>`;
  return 'data:text/html;charset=utf-8,' + encodeURIComponent(html);
}

function createMainWindow() {
  const { serverUrl } = loadSettings();
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    title: 'AI-Systems',
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  mainWindow.loadURL(serverUrl).catch(() => mainWindow.loadURL(errorPage(serverUrl)));
  mainWindow.webContents.on('did-fail-load', () => mainWindow.loadURL(errorPage(serverUrl)));
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

ipcMain.handle('settings:get', () => loadSettings());
ipcMain.handle('settings:set', (_event, settings) => {
  saveSettings({ serverUrl: String(settings.serverUrl || DEFAULT_URL) });
  if (mainWindow) {
    const { serverUrl } = loadSettings();
    mainWindow.loadURL(serverUrl).catch(() => mainWindow.loadURL(errorPage(serverUrl)));
  }
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
