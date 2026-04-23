/**
 * SyncSpace client: Yjs + CodeMirror 6 with a minimal WebSocket provider.
 * Binary wire format: 0x00 + Yjs update, 0x01 + awareness update; JSON text for request_state.
 * See Technical report.md and README.md.
 */
import * as Y from 'yjs';
import { yCollab } from 'y-codemirror.next';
import * as awarenessProtocol from 'y-protocols/awareness';

import { EditorState, Compartment } from '@codemirror/state';
import { EditorView, basicSetup } from 'codemirror';
import { python } from '@codemirror/lang-python';
import { java } from '@codemirror/lang-java';
import { cpp } from '@codemirror/lang-cpp';
import { oneDark } from '@codemirror/theme-one-dark';

const LS_LANG = 'syncspace-language';
const LS_DISPLAY_NAME = 'syncspace-display-name';
const LS_SHOW_CURSOR_NAMES = 'syncspace-show-cursor-names';
const MAX_DISPLAY_NAME_LENGTH = 24;

const LANG = {
  python: () => python(),
  cpp: () => cpp(),
  java: () => java()
};

// Simple Custom WebSocket Provider to communicate with our stateless Python relay server
class SimpleProvider {
  constructor(url, doc, awareness) {
    this.doc = doc;
    this.awareness = awareness;
    this.ws = new WebSocket(url);
    this.ws.binaryType = 'arraybuffer';
    
    // UI Elements
    this.statusText = document.getElementById('connection-status');
    this.statusDot = document.getElementById('connection-dot');

    this._connected = false;

    this.ws.onopen = () => {
      this._connected = true;
      this.statusText.textContent = 'Connected';
      this.statusDot.classList.add('connected');
      
      // 1. Request the current document state from any existing peer
      this.ws.send(JSON.stringify({ type: 'request_state' }));

      // 2. Broadcast our own initial awareness state (prefix 1 = awareness)
      this._sendAwarenessUpdate(
        awarenessProtocol.encodeAwarenessUpdate(this.awareness, [this.doc.clientID])
      );
    };

    this.ws.onerror = () => {
      this.statusText.textContent = 'Connection error';
      this.statusDot.classList.remove('connected');
    };

    this.ws.onclose = () => {
      this.statusText.textContent = 'Disconnected';
      this.statusDot.classList.remove('connected');
      // Clean up awareness so other peers remove our cursor/name
      awarenessProtocol.removeAwarenessStates(this.awareness, [this.doc.clientID], this);
      // Only auto-reconnect if we were previously connected (prevents infinite reload loops)
      if (this._connected) {
        setTimeout(() => {
          window.location.reload();
        }, 5000);
      }
    };

    this._sendDocUpdate = (update) => {
      if (this.ws.readyState !== WebSocket.OPEN) return;
      const msg = new Uint8Array(update.length + 1);
      msg[0] = 0;
      msg.set(update, 1);
      this.ws.send(msg);
    };

    this._sendAwarenessUpdate = (update) => {
      if (this.ws.readyState !== WebSocket.OPEN) return;
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
            // A new peer joined. Send them the full state of our local document.
            // (In a real app, to prevent spike loads, you'd elect a single peer to respond, 
            // but for a small prototype, everyone sending it is fine because Yjs handles redundant updates optimally).
            this._sendDocUpdate(Y.encodeStateAsUpdate(this.doc));
            this._sendAwarenessUpdate(
              awarenessProtocol.encodeAwarenessUpdate(this.awareness, [this.doc.clientID])
            );
          }
        } catch (e) {
            console.error("Failed to parse JSON msg", event.data);
        }
      } else {
        // Binary messages could be CRDT Document updates OR Awareness updates
        // Since we combined them on the same connection indiscriminately, we could prefix them via bytes.
        // But let's build a simple prefix system natively:
        const data = new Uint8Array(event.data);
        if (data[0] === 0) {
          // Document Update
          const update = data.slice(1);
          Y.applyUpdate(this.doc, update, this);
        } else if (data[0] === 1) {
          // Awareness Update
          const update = data.slice(1);
          awarenessProtocol.applyAwarenessUpdate(this.awareness, update, this);
        }
      }
    };

    // Listen to local document changes and broadcast them
    doc.on('update', (update, origin) => {
      // Do not broadcast changes that came from the network (origin === this)
      if (origin !== this) {
        this._sendDocUpdate(update);
      }
    });

    // Listen to local awareness changes and broadcast them
    awareness.on('update', ({ added, updated, removed }) => {
      const changedClients = added.concat(updated, removed);
      this._sendAwarenessUpdate(
        awarenessProtocol.encodeAwarenessUpdate(this.awareness, changedClients)
      );
    });
  }
}

// Ensure session exists
const urlParams = new URLSearchParams(window.location.search);
let sessionId = urlParams.get('session');
if (!sessionId) {
  sessionId = 'demo-session';
  window.history.replaceState(null, '', `?session=${sessionId}`);
}

// 1. Initialize Yjs CRDT Document & Awareness
const ydoc = new Y.Doc();
const ytext = ydoc.getText('codemirror');
const ysettings = ydoc.getMap('settings');
const awareness = new awarenessProtocol.Awareness(ydoc);

// Generate random user info
const colors = ['#f87171', '#fb923c', '#fbbf24', '#34d399', '#38bdf8', '#818cf8', '#a78bfa', '#f472b6'];
const randomColor = colors[Math.floor(Math.random() * colors.length)];
const savedDisplayName = (localStorage.getItem(LS_DISPLAY_NAME) || '').trim();
const randomName = 'User_' + Math.floor(Math.random() * 1000);
const initialDisplayName = savedDisplayName || randomName;

function sanitizeDisplayName(raw) {
  const normalized = String(raw || '').trim().replace(/\s+/g, ' ');
  return normalized.slice(0, MAX_DISPLAY_NAME_LENGTH);
}

function getDefaultShareUrl() {
  const url = new URL(window.location.href);
  url.searchParams.set('session', sessionId);
  return url.toString();
}

awareness.setLocalStateField('user', {
  name: initialDisplayName,
  color: randomColor,
  colorLight: randomColor + '33'
});

// 2. Connect Provider
const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const wsUrl = `${wsProto}//${window.location.host}/ws/${sessionId}`;
const provider = new SimpleProvider(wsUrl, ydoc, awareness);

const languageConf = new Compartment();
const langSelect = document.getElementById('language-select');
const savedLang = localStorage.getItem(LS_LANG);
if (savedLang && LANG[savedLang]) {
  langSelect.value = savedLang;
}

// 3. Initialize CodeMirror Editor
const langKey = langSelect.value in LANG ? langSelect.value : 'python';
const state = EditorState.create({
  doc: ytext.toString(),
  extensions: [
    basicSetup,
    languageConf.of(LANG[langKey]()),
    oneDark,
    yCollab(ytext, provider.awareness, { undoManager: new Y.UndoManager(ytext) })
  ]
});

const view = new EditorView({
  state,
  parent: document.getElementById('editor')
});

// Helper to apply a language key to the editor + dropdown
let _currentLangKey = langKey;
function applyLanguage(key) {
  if (!LANG[key] || key === _currentLangKey) return;
  _currentLangKey = key;
  langSelect.value = key;
  localStorage.setItem(LS_LANG, key);
  view.dispatch({
    effects: languageConf.reconfigure(LANG[key]())
  });
}

// When the local user changes the dropdown, write to the shared Y.Map
langSelect.addEventListener('change', () => {
  const key = langSelect.value;
  if (!LANG[key]) return;
  ysettings.set('language', key);
});

// Observe the shared Y.Map so remote language changes are applied locally
ysettings.observe((event) => {
  if (event.keysChanged.has('language')) {
    const remoteLang = ysettings.get('language');
    if (remoteLang && LANG[remoteLang]) {
      applyLanguage(remoteLang);
    }
  }
});

// If the shared map already has a language (we joined an existing session), adopt it
const existingLang = ysettings.get('language');
if (existingLang && LANG[existingLang]) {
  applyLanguage(existingLang);
} else {
  // First user in the session — seed the shared language
  ysettings.set('language', langKey);
}

const toast = document.getElementById('toast');

function showToast(message, durationMs = 2000, restoreText = 'Copied to clipboard!') {
  toast.textContent = message;
  toast.classList.add('show');
  setTimeout(() => {
    toast.classList.remove('show');
    toast.textContent = restoreText;
  }, durationMs);
}

function setDisplayName(nextName) {
  const cleanName = sanitizeDisplayName(nextName);
  if (!cleanName) return false;
  const localState = awareness.getLocalState() || {};
  const user = localState.user || {};
  awareness.setLocalStateField('user', {
    ...user,
    name: cleanName
  });
  localStorage.setItem(LS_DISPLAY_NAME, cleanName);
  return true;
}

// Clipboard API only works in a secure context (https / localhost). LAN http://IP needs execCommand fallback.
function copyToClipboard(text) {
  if (window.isSecureContext && navigator.clipboard?.writeText) {
    return navigator.clipboard.writeText(text);
  }
  return new Promise((resolve, reject) => {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.cssText = 'position:fixed;left:0;top:0;width:2em;height:2em;opacity:0;';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    ta.setSelectionRange(0, text.length);
    let ok = false;
    try {
      ok = document.execCommand('copy');
    } finally {
      document.body.removeChild(ta);
    }
    if (ok) resolve();
    else reject(new Error('copy'));
  });
}

// 4. Update UI Components — share uses server-built URL (LAN IP + port + /app/?session=…) so 127.0.0.1 is not copied
const shareBtn = document.getElementById('share-btn');
let shareUrl = getDefaultShareUrl();

async function refreshShareUrl() {
  try {
    const res = await fetch(`/api/share-link?session=${encodeURIComponent(sessionId)}`);
    if (res.ok) {
      const data = await res.json();
      if (data.url) {
        shareUrl = data.url;
        return;
      }
    }
  } catch {
    // Keep the default URL.
  }
  shareUrl = getDefaultShareUrl();
}

// Resolve the server-built share URL up front so clipboard write stays in the click gesture path.
refreshShareUrl();

shareBtn.addEventListener('click', async () => {
  try {
    await copyToClipboard(shareUrl);
    showToast('Copied to clipboard!');
  } catch {
    window.prompt('Copy this link:', shareUrl);
    showToast('Copy failed. Link shown for manual copy.');
  }
  refreshShareUrl();
});

const displayNameInput = document.getElementById('display-name-input');
const renameBtn = document.getElementById('rename-btn');

displayNameInput.value = initialDisplayName;

renameBtn.addEventListener('click', () => {
  const nextValue = displayNameInput.value;
  if (setDisplayName(nextValue)) {
    displayNameInput.value = sanitizeDisplayName(nextValue);
    showToast('Display name updated');
    updateParticipantsList();
    return;
  }
  const currentName = awareness.getLocalState()?.user?.name || initialDisplayName;
  displayNameInput.value = currentName;
  showToast('Please enter a valid display name');
});

displayNameInput.addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    event.preventDefault();
    renameBtn.click();
  }
});

const showCursorNamesInput = document.getElementById('show-cursor-names');
const storedShowCursorNames = localStorage.getItem(LS_SHOW_CURSOR_NAMES);
const initialShowCursorNames = storedShowCursorNames === null
  ? true
  : storedShowCursorNames === '1';

function applyCursorNameVisibility(showNames) {
  document.body.classList.toggle('show-cursor-names', showNames);
  localStorage.setItem(LS_SHOW_CURSOR_NAMES, showNames ? '1' : '0');
}

showCursorNamesInput.checked = initialShowCursorNames;
applyCursorNameVisibility(initialShowCursorNames);

showCursorNamesInput.addEventListener('change', () => {
  applyCursorNameVisibility(showCursorNamesInput.checked);
});

// Participant List tracking
const participantsList = document.getElementById('participants-list');

function updateParticipantsList() {
  participantsList.innerHTML = '';
  
  // Get all states (including our own)
  const states = Array.from(awareness.getStates().entries());
  
  if(states.length === 0) {
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
      name.textContent = state.user.name + (clientId === ydoc.clientID ? ' (You)' : '');
      
      item.appendChild(avatar);
      item.appendChild(name);
      participantsList.appendChild(item);
    }
  });
}

awareness.on('change', updateParticipantsList);
updateParticipantsList();
