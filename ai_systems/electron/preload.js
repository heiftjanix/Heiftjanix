// Schmale, sichere Brücke fürs Einstellungsfenster (contextIsolation bleibt an).
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('aiSystems', {
  getSettings: () => ipcRenderer.invoke('settings:get'),
  setSettings: (settings) => ipcRenderer.invoke('settings:set', settings),
});
