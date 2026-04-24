/**
 * SyncSpace — Implementation 3: Yjs + CodeMirror with HTTP Pub-Sub (POST + SSE).
 *
 * Pattern swap vs Implementation 1:
 *   Impl 1 uses a WebSocket Mediator (duplex star): one socket, binary frames.
 *   Impl 3 uses Publish-Subscribe: POST to publish an envelope, SSE stream to subscribe.
 *   Same wire semantics: doc + awareness + JSON control (request_state), base64 for binary.
 */
import * as Y from 'yjs';
import { yCollab } from 'y-codemirror.next';
import * as awarenessProtocol from 'y-protocols/awareness';

import { EditorState, Compartment } from '@codemirror/state';
import { EditorView, basicSetup } from 'codemirror';
import { keymap } from '@codemirror/view';
import { indentWithTab } from '@codemirror/commands';
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

function u8ToB64(u8) {
  let s = '';
  u8.forEach((b) => {
    s += String.fromCharCode(b);
  });
  return btoa(s);
}

function b64ToU8(b64) {
  const raw = atob(b64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

class PubSubProvider {
  /**
   * @param {string} baseUrl — '' for same origin
   * @param {string} sessionId
   * @param {string} connectionId — unique per tab (UUID); drives server fan-out exclude
   * @param {Y.Doc} doc
   * @param {import('y-protocols/awareness').Awareness} awareness
   */
  constructor(baseUrl, sessionId, connectionId, doc, awareness) {
    this.baseUrl = baseUrl.replace(/\/$/, '');
    this.sessionId = sessionId;
    this.connectionId = connectionId;
    this.doc = doc;
    this.awareness = awareness;
    this.canPublish = false;
    /** Serialize POSTs so Yjs update frames stay in order for this tab. */
    this._outbox = Promise.resolve();

    this.statusText = document.getElementById('connection-status');
    this.statusDot = document.getElementById('connection-dot');

    const q = new URLSearchParams();
    q.set('connection_id', connectionId);
    q.set('client_id', String(doc.clientID));
    const streamPath = `${this.baseUrl}/api/sessions/${encodeURIComponent(sessionId)}/stream?${q.toString()}`;
    this.es = new EventSource(streamPath);

    this.es.onopen = () => {
      this.statusText.textContent = 'Connected (Pub-Sub)';
      this.statusDot.classList.add('connected');
      this.canPublish = true;
      this._publish({ kind: 'json', text: JSON.stringify({ type: 'request_state' }) });
      this._sendAwarenessUpdate(
        awarenessProtocol.encodeAwarenessUpdate(this.awareness, [this.doc.clientID])
      );
    };

    this.es.onerror = () => {
      this.statusText.textContent = 'Disconnected';
      this.statusDot.classList.remove('connected');
      this.canPublish = false;
      setTimeout(() => {
        window.location.reload();
      }, 5000);
    };

    this.es.onmessage = (event) => {
      let env;
      try {
        env = JSON.parse(event.data);
      } catch (e) {
        console.error('bad SSE data', e);
        return;
      }
      if (env.kind === 'json') {
        const msg = JSON.parse(env.text);
        if (msg.type === 'request_state') {
          this._sendDocUpdate(Y.encodeStateAsUpdate(this.doc));
          this._sendAwarenessUpdate(
            awarenessProtocol.encodeAwarenessUpdate(this.awareness, [this.doc.clientID])
          );
        }
        return;
      }
      if (env.kind === 'doc') {
        const update = b64ToU8(env.b64);
        Y.applyUpdate(this.doc, update, this);
        return;
      }
      if (env.kind === 'awareness') {
        const u = b64ToU8(env.b64);
        awarenessProtocol.applyAwarenessUpdate(this.awareness, u, this);
      }
    };

    doc.on('update', (update, origin) => {
      if (origin !== this) {
        this._sendDocUpdate(update);
      }
    });

    awareness.on('update', ({ added, updated, removed }) => {
      const changed = added.concat(updated, removed);
      this._sendAwarenessUpdate(
        awarenessProtocol.encodeAwarenessUpdate(this.awareness, changed)
      );
    });

    window.addEventListener('beforeunload', () => {
      awarenessProtocol.removeAwarenessStates(this.awareness, [this.doc.clientID], 'window unload');
    });

    this._heartbeat = setInterval(() => {
      if (this.canPublish && this.es.readyState === 1) {
        this._sendAwarenessUpdate(
          awarenessProtocol.encodeAwarenessUpdate(this.awareness, [this.doc.clientID])
        );
      }
    }, 15000);
  }

  _publishUrl() {
    return `${this.baseUrl}/api/sessions/${encodeURIComponent(this.sessionId)}/publish`;
  }

  /**
   * @param {object} envelope
   */
  _publish(envelope) {
    if (!this.canPublish) return;
    const body = JSON.stringify({
      from_connection: this.connectionId,
      envelope
    });
    this._outbox = this._outbox.then(() =>
      fetch(this._publishUrl(), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body,
        keepalive: true
      })
    );
  }

  _sendDocUpdate(update) {
    this._publish({ kind: 'doc', b64: u8ToB64(update) });
  }

  _sendAwarenessUpdate(update) {
    this._publish({ kind: 'awareness', b64: u8ToB64(update) });
  }
}

const urlParams = new URLSearchParams(window.location.search);
let sessionId = urlParams.get('session');
if (!sessionId) {
  sessionId = 'demo-session';
  window.history.replaceState(null, '', `?session=${sessionId}`);
}

const SS_CLIENT_ID = 'syncspace-clientid';
let storedClientId = Number(sessionStorage.getItem(SS_CLIENT_ID));
if (!storedClientId || storedClientId <= 0) {
  storedClientId = Math.floor(Math.random() * 2147483647);
  sessionStorage.setItem(SS_CLIENT_ID, storedClientId);
}
const ydoc = new Y.Doc({ clientID: storedClientId });
const ytext = ydoc.getText('codemirror');
const awareness = new awarenessProtocol.Awareness(ydoc);

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

const connectionId =
  (typeof crypto !== 'undefined' && crypto.randomUUID && crypto.randomUUID()) ||
  `c-${Date.now()}-${Math.random().toString(16).slice(2)}`;
const provider = new PubSubProvider('', sessionId, connectionId, ydoc, awareness);

const languageConf = new Compartment();
const langSelect = document.getElementById('language-select');
const savedLang = localStorage.getItem(LS_LANG);
if (savedLang && LANG[savedLang]) {
  langSelect.value = savedLang;
}

const langKey = langSelect.value in LANG ? langSelect.value : 'python';
const state = EditorState.create({
  doc: ytext.toString(),
  extensions: [
    basicSetup,
    keymap.of([indentWithTab]),
    languageConf.of(LANG[langKey]()),
    oneDark,
    yCollab(ytext, provider.awareness, { undoManager: new Y.UndoManager(ytext) })
  ]
});

const view = new EditorView({
  state,
  parent: document.getElementById('editor')
});

langSelect.addEventListener('change', () => {
  const key = langSelect.value;
  if (!LANG[key]) return;
  localStorage.setItem(LS_LANG, key);
  view.dispatch({
    effects: languageConf.reconfigure(LANG[key]())
  });
});

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
    // keep default
  }
  shareUrl = getDefaultShareUrl();
}

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

const participantsList = document.getElementById('participants-list');

function updateParticipantsList() {
  participantsList.innerHTML = '';

  const states = Array.from(awareness.getStates().entries());

  if (states.length === 0) {
    participantsList.innerHTML = '<div style="color:var(--text-secondary);font-size:0.875rem;">Only you</div>';
    return;
  }

  states.forEach(([clientId, st]) => {
    if (st.user) {
      const item = document.createElement('div');
      item.className = 'participant';

      const avatar = document.createElement('div');
      avatar.className = 'avatar';
      avatar.style.backgroundColor = st.user.color;
      avatar.textContent = st.user.name.charAt(0).toUpperCase();

      const name = document.createElement('span');
      name.className = 'p-name';
      name.textContent = st.user.name + (clientId === ydoc.clientID ? ' (You)' : '');

      item.appendChild(avatar);
      item.appendChild(name);
      participantsList.appendChild(item);
    }
  });
}

awareness.on('change', updateParticipantsList);
updateParticipantsList();
