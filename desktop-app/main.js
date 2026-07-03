/**
 * JARVIS Desktop App (Electron)
 *
 * A standalone desktop application that connects to your JARVIS cloud server.
 * Features:
 * - Always-on-top floating window
 * - Global hotkey (Ctrl+Shift+J) to invoke JARVIS
 * - System tray icon
 * - Voice conversation
 * - Runs as a native desktop app
 */

const { app, BrowserWindow, globalShortcut, Tray, Menu, nativeImage } = require('electron');
const path = require('path');

// ====== CONFIGURE YOUR SERVER URL ======
// After deploying to Render.com, replace this with your Render URL
// Example: https://jarvis-ai-xxxx.onrender.com
const SERVER_URL = process.env.JARVIS_URL || 'http://localhost:3000';
// =======================================

let mainWindow = null;
let tray = null;
let isQuitting = false;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 420,
    height: 600,
    frame: false,
    transparent: true,
    resizable: true,
    alwaysOnTop: false,
    skipTaskbar: false,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
    icon: path.join(__dirname, 'icon.png'),
    show: false,
  });

  mainWindow.loadURL(SERVER_URL);

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  mainWindow.on('close', (event) => {
    if (!isQuitting) {
      event.preventDefault();
      mainWindow.hide();
    }
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

function createTray() {
  // Create a simple tray icon
  const icon = nativeImage.createFromDataURL(
    'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAAJcEhZcwAADsMAAA7DAcdvqGQAAAGdSURBVFhH7ZY/SwMxGMbvWv+hdnMQHBwcxE0U3NwcXAQnwU9Q+gXsIjj5BdxEFxcXF/0KDi6Cg4ObIFJba3t5Xt6Qlzb3l9Kh/uBHkuTN87xJ7m7GADBgMIP/AcRvF0yUKaVvn3l/Bs8mMBZNwqF4uL5oFSY3+l0ksnMVLdbP+p0u/diKXrUbDTaw2bzKDsIfj4lR4xR9SIJPzI8DkbqVQCAzH+YRwHLBeSVZrNZJ5VA3J7TH+D7i5XNrpL3RqNRL1NRbrdbt6enp3UxdnxJjhlr1MtIRO9L8nNycoJS8Xj4A0ej0ZwlEEtWKhWfpVJ/ZjY7UzKNDofD4PX19cYRy60Sfl+cn6NUSPgtl8sLdm9F/CfGxdmZwKMY6bvdrmeKxYXDOBbvFDZ9f3q64hTi+cnJQaVWu7J3dqTP7GmxNJxMp08TU+mDWCJeolqphjOZ9EI0FuuQiEfhpFhc9Pv9w/+z2UGcCKRHM1kMj7KM/gQBp6KHEnCj4RCEQ+s/4b+hED/SkCC4EUH2gAAAABJRU5ErkJggg=='
  );

  tray = new Tray(icon);
  const contextMenu = Menu.buildFromTemplate([
    { label: 'Show JARVIS', click: () => mainWindow.show() },
    { label: 'Always on Top', type: 'checkbox', checked: false, click: (item) => { mainWindow.setAlwaysOnTop(item.checked); } },
    { type: 'separator' },
    { label: 'Quit', click: () => { isQuitting = true; app.quit(); } },
  ]);

  tray.setToolTip('JARVIS - Personal AI Assistant');
  tray.setContextMenu(contextMenu);

  tray.on('click', () => {
    if (mainWindow.isVisible()) {
      mainWindow.hide();
    } else {
      mainWindow.show();
      mainWindow.focus();
    }
  });
}

app.whenReady().then(() => {
  createWindow();
  createTray();

  // Global hotkey: Ctrl+Shift+J to toggle JARVIS
  globalShortcut.register('Control+Shift+J', () => {
    if (mainWindow.isVisible()) {
      mainWindow.hide();
    } else {
      mainWindow.show();
      mainWindow.focus();
    }
  });
});

app.on('before-quit', () => {
  isQuitting = true;
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('activate', () => {
  if (mainWindow === null) createWindow();
  else mainWindow.show();
});

app.on('will-quit', () => {
  globalShortcut.unregisterAll();
});
