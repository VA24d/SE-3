/**
 * SyncSpace client: Yjs + CodeMirror 6 with a minimal WebSocket provider.
 * Binary wire format: 0x00 + Yjs update, 0x01 + awareness update; JSON text for request_state.
 * See Technical report.md and README.md.
 */
import * as Y from 'yjs';
import { yCollab } from 'y-codemirror.next';
import * as awarenessProtocol from 'y-protocols/awareness';

import { EditorState } from '@codemirror/state';
import { EditorView, basicSetup } from 'codemirror';
import { javascript } from '@codemirror/lang-javascript';
import { oneDark } from '@codemirror/theme-one-dark';

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

    this.ws.onopen = () => {
      this.statusText.textContent = 'Connected';
      this.statusDot.classList.add('connected');
      
      // 1. Request the current document state from any existing peer
      this.ws.send(JSON.stringify({ type: 'request_state' }));

      // 2. Broadcast our own initial awareness state (prefix 1 = awareness)
      this._sendAwarenessUpdate(
        awarenessProtocol.encodeAwarenessUpdate(this.awareness, [this.doc.clientID])
      );
    };

    this.ws.onclose = () => {
      this.statusText.textContent = 'Disconnected';
      this.statusDot.classList.remove('connected');
      // Reconnect with backoff in a real app, keeping it simple here
      setTimeout(() => {
        window.location.reload();
      }, 5000);
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
const awareness = new awarenessProtocol.Awareness(ydoc);

// Generate random user info
const colors = ['#f87171', '#fb923c', '#fbbf24', '#34d399', '#38bdf8', '#818cf8', '#a78bfa', '#f472b6'];
const randomColor = colors[Math.floor(Math.random() * colors.length)];
const randomName = 'User_' + Math.floor(Math.random() * 1000);

awareness.setLocalStateField('user', {
  name: randomName,
  color: randomColor,
  colorLight: randomColor + '33'
});

// 2. Connect Provider
const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const wsUrl = `${wsProto}//${window.location.host}/ws/${sessionId}`;
const provider = new SimpleProvider(wsUrl, ydoc, awareness);

// 3. Initialize CodeMirror Editor
const state = EditorState.create({
  doc: ytext.toString(),
  extensions: [
    basicSetup,
    javascript(),
    oneDark,
    yCollab(ytext, provider.awareness, { undoManager: new Y.UndoManager(ytext) })
  ]
});

const view = new EditorView({
  state,
  parent: document.getElementById('editor')
});

// 4. Update UI Components
const shareBtn = document.getElementById('share-btn');
shareBtn.addEventListener('click', () => {
  navigator.clipboard.writeText(window.location.href);
  const toast = document.getElementById('toast');
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 2000);
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
