/**
 * SyncSpace client: Yjs + CodeMirror 6 with a minimal WebSocket provider.
 * Multi-file: Y.Map "files" maps path strings → Y.Text (paths may include folders: src/a.py).
 * Binary wire format: 0x00 + Yjs update, 0x01 + awareness update; JSON text for request_state.
 */
import * as Y from 'yjs';
import { yCollab } from 'y-codemirror.next';
import * as awarenessProtocol from 'y-protocols/awareness';

import { EditorState } from '@codemirror/state';
import { EditorView, basicSetup } from 'codemirror';
import { python } from '@codemirror/lang-python';
import { java } from '@codemirror/lang-java';
import { cpp } from '@codemirror/lang-cpp';
import { oneDark } from '@codemirror/theme-one-dark';

const LS_NAME = 'syncspace-display-name';
const LS_LANG = 'syncspace-language';
const LS_CURSOR_NAMES = 'syncspace-show-cursor-names';
const LS_ACTIVE_FILE = 'syncspace-active-file';

const LANG = {
  python: () => python(),
  java: () => java(),
  c: () => cpp()
};

// Simple Custom WebSocket Provider to communicate with our stateless Python relay server
class SimpleProvider {
  constructor(url, doc, awareness) {
    this.doc = doc;
    this.awareness = awareness;
    this.ws = new WebSocket(url);
    this.ws.binaryType = 'arraybuffer';
    
    this.statusText = document.getElementById('connection-status');
    this.statusDot = document.getElementById('connection-dot');

    this.ws.onopen = () => {
      this.statusText.textContent = 'Connected';
      this.statusDot.classList.add('connected');
      this.ws.send(JSON.stringify({ type: 'request_state' }));
      this._sendAwarenessUpdate(
        awarenessProtocol.encodeAwarenessUpdate(this.awareness, [this.doc.clientID])
      );
    };

    this.ws.onclose = () => {
      this.statusText.textContent = 'Disconnected';
      this.statusDot.classList.remove('connected');
      setTimeout(() => window.location.reload(), 5000);
    };

    this._sendDocUpdate = (update) => {
      const msg = new Uint8Array(update.length + 1);
      msg[0] = 0;
      msg.set(update, 1);
      this.ws.send(msg);
    };

    this._sendAwarenessUpdate = (update) => {
      const msg = new Uint8Array(update.length + 1);
      msg[0] = 1;
      msg.set(update, 1);
      this.ws.send(msg);
    };

    this.ws.onmessage = (event) => {
      if (typeof event.data === 'string') {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'request_state') {
            this._sendDocUpdate(Y.encodeStateAsUpdate(this.doc));
            this._sendAwarenessUpdate(
              awarenessProtocol.encodeAwarenessUpdate(this.awareness, [this.doc.clientID])
            );
          }
        } catch (e) {
          console.error('Failed to parse JSON msg', event.data);
        }
      } else {
        const data = new Uint8Array(event.data);
        if (data[0] === 0) {
          Y.applyUpdate(this.doc, data.slice(1), this);
        } else if (data[0] === 1) {
          awarenessProtocol.applyAwarenessUpdate(this.awareness, data.slice(1), this);
        }
      }
    };

    doc.on('update', (update, origin) => {
      if (origin !== this) {
        this._sendDocUpdate(update);
      }
    });

    awareness.on('update', ({ added, updated, removed }) => {
      const changedClients = added.concat(updated, removed);
      this._sendAwarenessUpdate(
        awarenessProtocol.encodeAwarenessUpdate(this.awareness, changedClients)
      );
    });
  }
}

async function copyTextToClipboard(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (_) { /* fall through */ }
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    if (ok) return true;
  } catch (_) { /* fall through */ }
  window.prompt('Copy this session link:', text);
  return false;
}

function showToast(message, isError = false) {
  const toast = document.getElementById('toast');
  toast.textContent = message;
  toast.classList.toggle('toast-error', isError);
  toast.classList.add('show');
  setTimeout(() => {
    toast.classList.remove('show');
    toast.classList.remove('toast-error');
  }, 2500);
}

const urlParams = new URLSearchParams(window.location.search);
let sessionId = urlParams.get('session');
if (!sessionId) {
  sessionId = 'demo-session';
  window.history.replaceState(null, '', `?session=${sessionId}`);
}

const ydoc = new Y.Doc();
const filesMap = ydoc.getMap('files');

function bootstrapFiles() {
  ydoc.transact(() => {
    if (filesMap.size > 0) return;
    const nt = new Y.Text();
    const legacy = ydoc.getText('codemirror');
    if (legacy && legacy.length > 0) {
      nt.insert(0, legacy.toString());
    }
    filesMap.set('main.py', nt);
  });
}
bootstrapFiles();

const awareness = new awarenessProtocol.Awareness(ydoc);

const colors = ['#f87171', '#fb923c', '#fbbf24', '#34d399', '#38bdf8', '#818cf8', '#a78bfa', '#f472b6'];
const randomColor = colors[Math.floor(Math.random() * colors.length)];

const nameInput = document.getElementById('display-name');
const storedName = localStorage.getItem(LS_NAME);
const randomName = 'User_' + Math.floor(Math.random() * 1000);
const initialName = (storedName && storedName.trim()) ? storedName.trim() : randomName;
nameInput.value = initialName;

awareness.setLocalStateField('user', {
  name: initialName,
  color: randomColor,
  colorLight: randomColor + '33'
});

function persistDisplayName() {
  let name = nameInput.value.trim();
  if (!name) {
    name = 'User_' + Math.floor(Math.random() * 1000);
    nameInput.value = name;
  }
  localStorage.setItem(LS_NAME, name);
  const u = awareness.getLocalState()?.user || {};
  awareness.setLocalStateField('user', {
    ...u,
    name,
    color: u.color || randomColor,
    colorLight: (u.color || randomColor) + '33'
  });
}

nameInput.addEventListener('change', persistDisplayName);
nameInput.addEventListener('blur', persistDisplayName);
nameInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    e.preventDefault();
    nameInput.blur();
  }
});

const showCursorNamesEl = document.getElementById('show-cursor-names');
const savedShowNames = localStorage.getItem(LS_CURSOR_NAMES);
showCursorNamesEl.checked = savedShowNames === null ? true : savedShowNames === 'true';

function applyCursorNameVisibility() {
  document.body.classList.toggle('show-cursor-names', showCursorNamesEl.checked);
  localStorage.setItem(LS_CURSOR_NAMES, String(showCursorNamesEl.checked));
}
showCursorNamesEl.addEventListener('change', applyCursorNameVisibility);
applyCursorNameVisibility();

const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const wsUrl = `${wsProto}//${window.location.host}/ws/${sessionId}`;
const provider = new SimpleProvider(wsUrl, ydoc, awareness);

const langSelect = document.getElementById('language-select');
const savedLang = localStorage.getItem(LS_LANG);
if (savedLang && LANG[savedLang]) {
  langSelect.value = savedLang;
}

const undoByPath = new Map();
let currentPath = null;
let view;

function sortedPaths() {
  return Array.from(filesMap.keys()).sort();
}

function langKeyForPath(path) {
  const lower = path.toLowerCase();
  if (lower.endsWith('.py')) return 'python';
  if (lower.endsWith('.java')) return 'java';
  if (lower.endsWith('.c') || lower.endsWith('.h') || lower.endsWith('.cpp') || lower.endsWith('.cc')) return 'c';
  return null;
}

function buildEditorState(ytext, path) {
  let langKey = langSelect.value;
  if (!LANG[langKey]) langKey = 'python';
  if (!undoByPath.has(path)) {
    undoByPath.set(path, new Y.UndoManager(ytext));
  }
  return EditorState.create({
    doc: ytext.toString(),
    extensions: [
      basicSetup,
      LANG[langKey](),
      oneDark,
      yCollab(ytext, awareness, { undoManager: undoByPath.get(path) })
    ]
  });
}

function pickInitialPath() {
  const saved = localStorage.getItem(LS_ACTIVE_FILE);
  if (saved && filesMap.has(saved)) return saved;
  return sortedPaths()[0] || 'main.py';
}

function openFile(path) {
  if (!filesMap.has(path)) return;
  const ytext = filesMap.get(path);
  currentPath = path;
  localStorage.setItem(LS_ACTIVE_FILE, path);

  const inferred = langKeyForPath(path);
  if (inferred) {
    langSelect.value = inferred;
    localStorage.setItem(LS_LANG, inferred);
  }

  awareness.setLocalStateField('activeFile', path);
  view.setState(buildEditorState(ytext, path));
  renderFileList();
}

function removeFile(path) {
  if (filesMap.size <= 1) {
    showToast('Keep at least one file', true);
    return;
  }
  ydoc.transact(() => filesMap.delete(path));
  undoByPath.delete(path);
  if (currentPath === path) {
    const next = sortedPaths()[0];
    if (next) openFile(next);
  }
  renderFileList();
}

function renderFileList() {
  const el = document.getElementById('file-list');
  el.innerHTML = '';
  sortedPaths().forEach((path) => {
    const row = document.createElement('div');
    row.className = 'file-row' + (path === currentPath ? ' active' : '');
    const nm = document.createElement('span');
    nm.className = 'file-name';
    nm.textContent = path;
    nm.title = path;
    row.appendChild(nm);
    if (filesMap.size > 1) {
      const del = document.createElement('button');
      del.type = 'button';
      del.className = 'file-del';
      del.textContent = '×';
      del.title = 'Remove file';
      del.addEventListener('click', (e) => {
        e.stopPropagation();
        removeFile(path);
      });
      row.appendChild(del);
    }
    row.addEventListener('click', () => openFile(path));
    el.appendChild(row);
  });
}

const initialPath = pickInitialPath();
const initialYText = filesMap.get(initialPath);
currentPath = initialPath;
awareness.setLocalStateField('activeFile', initialPath);

if (langKeyForPath(initialPath)) {
  langSelect.value = langKeyForPath(initialPath);
  localStorage.setItem(LS_LANG, langSelect.value);
}

view = new EditorView({
  state: buildEditorState(initialYText, initialPath),
  parent: document.getElementById('editor')
});

renderFileList();

filesMap.observe((event) => {
  if (!filesMap.has(currentPath)) {
    const next = sortedPaths()[0];
    if (next) openFile(next);
  }
  renderFileList();
});

langSelect.addEventListener('change', () => {
  const ytext = filesMap.get(currentPath);
  if (!ytext) return;
  localStorage.setItem(LS_LANG, langSelect.value);
  if (currentPath) {
    localStorage.setItem(LS_LANG + ':override', currentPath);
  }
  view.setState(buildEditorState(ytext, currentPath));
});

document.getElementById('add-file-btn').addEventListener('click', () => {
  const name = window.prompt(
    'File path (folders ok: src/main.c, docs/notes.py)',
    'untitled.py'
  );
  if (!name || !name.trim()) return;
  const path = name.trim().replace(/^\/+/, '');
  if (filesMap.has(path)) {
    openFile(path);
    return;
  }
  ydoc.transact(() => {
    filesMap.set(path, new Y.Text());
  });
  openFile(path);
});

document.getElementById('share-btn').addEventListener('click', async () => {
  const url = window.location.href;
  try {
    const ok = await copyTextToClipboard(url);
    if (ok) {
      showToast('Copied to clipboard!');
    } else {
      showToast('Use the dialog to copy the link');
    }
  } catch (e) {
    console.error(e);
    showToast('Could not copy — try copying from the address bar', true);
  }
});

const participantsList = document.getElementById('participants-list');

function updateParticipantsList() {
  participantsList.innerHTML = '';
  const states = Array.from(awareness.getStates().entries());
  if (states.length === 0) {
    participantsList.innerHTML = '<div style="color:var(--text-secondary);font-size:0.875rem;">Only you</div>';
    return;
  }
  states.forEach(([clientId, state]) => {
    if (state.user) {
      const item = document.createElement('div');
      item.className = 'participant';
      const avatar = document.createElement('div');
      avatar.className = 'avatar';
      avatar.style.backgroundColor = state.user.color;
      avatar.textContent = state.user.name.charAt(0).toUpperCase();
      const name = document.createElement('span');
      name.className = 'p-name';
      let label = state.user.name + (clientId === ydoc.clientID ? ' (You)' : '');
      if (state.activeFile && typeof state.activeFile === 'string') {
        label += ` · ${state.activeFile}`;
      }
      name.textContent = label;
      item.appendChild(avatar);
      item.appendChild(name);
      participantsList.appendChild(item);
    }
  });
}

awareness.on('change', updateParticipantsList);
updateParticipantsList();
