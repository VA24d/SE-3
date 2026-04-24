/**
 * SyncSpace-OT client: Operational Transformation without Yjs.
 *
 * Architecture contrast with Implementation 1 (CRDT):
 *  - No local-first replica. Edits are sent to the server and only reflected
 *    in the editor once the server ACKs them (or the inflight op is confirmed).
 *  - The server transforms ops against concurrent ops before broadcasting.
 *  - Wire: JSON text only (no binary framing, no CRDT update vectors).
 *
 * OT client state machine (simplified Jupiter protocol):
 *  inflight = op sent to server, awaiting ack
 *  buffer   = local ops accumulated while inflight is pending
 *  When ack arrives: promote buffer → inflight, send it.
 *  When server op arrives: transform inflight + buffer against it,
 *    transform it against inflight + buffer, apply result to editor.
 */

import { EditorState, Compartment } from '@codemirror/state';
import { EditorView, basicSetup } from 'codemirror';
import { keymap } from '@codemirror/view';
import { indentWithTab } from '@codemirror/commands';
import { python } from '@codemirror/lang-python';
import { java } from '@codemirror/lang-java';
import { cpp } from '@codemirror/lang-cpp';
import { oneDark } from '@codemirror/theme-one-dark';

// ── OT helpers ────────────────────────────────────────────────────────────────

/**
 * Transform op1 assuming op2 has already been applied to the document.
 * Returns the adjusted op1, or null if op1 becomes a no-op.
 * This runs on EVERY incoming server message — O(pending_ops) per message.
 */
function transformOp(op1, op2) {
  if (!op1 || !op2) return op1;
  const t1 = op1.type, t2 = op2.type;

  if (t1 === 'insert') {
    const pos1 = op1.pos;
    if (t2 === 'insert') {
      return op2.pos <= pos1
        ? { ...op1, pos: pos1 + op2.text.length }
        : op1;
    }
    // t2 === 'delete'
    const end2 = op2.pos + op2.length;
    if (end2 <= pos1) return { ...op1, pos: pos1 - op2.length };
    if (op2.pos < pos1) return { ...op1, pos: op2.pos };
    return op1;
  }

  // t1 === 'delete'
  const pos1 = op1.pos, len1 = op1.length;
  if (t2 === 'insert') {
    if (op2.pos <= pos1) return { ...op1, pos: pos1 + op2.text.length };
    if (op2.pos < pos1 + len1) return { ...op1, length: len1 + op2.text.length };
    return op1;
  }
  // t2 === 'delete'
  const end1 = pos1 + len1, end2 = op2.pos + op2.length;
  if (end2 <= pos1) return { ...op1, pos: pos1 - op2.length };
  if (op2.pos >= end1) return op1;
  // Overlap
  if (op2.pos <= pos1 && end2 >= end1) return null;
  if (op2.pos <= pos1) {
    const kept = Math.max(0, end1 - end2);
    return kept > 0 ? { ...op1, pos: op2.pos, length: kept } : null;
  }
  const kept = Math.max(0, len1 - (Math.min(end1, end2) - op2.pos));
  return kept > 0 ? { ...op1, length: kept } : null;
}

function transformOps(ops, against) {
  let result = [...ops];
  for (const sop of against) {
    result = result.map(op => transformOp(op, sop)).filter(Boolean);
  }
  return result;
}

// ── Session & state ───────────────────────────────────────────────────────────

const urlParams = new URLSearchParams(window.location.search);
let sessionId = urlParams.get('session') || 'demo-session';
if (!urlParams.get('session')) window.history.replaceState(null, '', `?session=${sessionId}`);

let myClientId = null;
let myColor = '#f59e0b';
let myName = localStorage.getItem('syncspace-ot-name') || '';

let serverRev = 0;
let inflight = null;   // {ops, rev} — sent, not yet acked
let buffer = [];       // local ops waiting to be sent
let applyingRemote = false;

const peers = new Map(); // clientId → {name, color, cursorPos}

// ── WebSocket ─────────────────────────────────────────────────────────────────

const wsProto = location.protocol === 'https:' ? 'wss:' : 'ws:';
const ws = new WebSocket(`${wsProto}//${location.host}/ws/${sessionId}`);
const statusText = document.getElementById('connection-status');
const statusDot  = document.getElementById('connection-dot');

ws.onopen  = () => { statusText.textContent = 'Connected';    statusDot.classList.add('connected'); };
ws.onclose = () => {
  statusText.textContent = 'Disconnected';
  statusDot.classList.remove('connected');
  setTimeout(() => location.reload(), 5000);
};

// ── Editor ────────────────────────────────────────────────────────────────────

const LS_LANG = 'syncspace-ot-language';
const LANG = { python: () => python(), cpp: () => cpp(), java: () => java() };
const languageConf = new Compartment();
const langSelect = document.getElementById('language-select');
const savedLang = localStorage.getItem(LS_LANG);
if (savedLang && LANG[savedLang]) langSelect.value = savedLang;
const langKey = langSelect.value in LANG ? langSelect.value : 'python';

let view = null;

function initEditor(initialDoc) {
  const state = EditorState.create({
    doc: initialDoc,
    extensions: [
      basicSetup,
      keymap.of([indentWithTab]),
      languageConf.of(LANG[langKey]()),
      oneDark,
      EditorView.updateListener.of(update => {
        if (!update.docChanged || applyingRemote) return;
        const ops = [];
        update.changes.iterChanges((fromA, toA, _fromB, _toB, inserted) => {
          if (toA > fromA) ops.push({ type: 'delete', pos: fromA, length: toA - fromA });
          if (inserted.length > 0) ops.push({ type: 'insert', pos: fromA, text: inserted.toString() });
        });
        if (ops.length) handleLocalOps(ops);
      }),
    ],
  });
  view = new EditorView({ state, parent: document.getElementById('editor') });
}

// ── OT send / receive ─────────────────────────────────────────────────────────

function handleLocalOps(ops) {
  buffer = buffer.concat(ops);
  if (!inflight) flushBuffer();
}

function flushBuffer() {
  if (!buffer.length || ws.readyState !== WebSocket.OPEN) return;
  inflight = { ops: buffer, rev: serverRev };
  buffer = [];
  ws.send(JSON.stringify({ type: 'op', rev: inflight.rev, ops: inflight.ops }));
}

function applyOpsToEditor(ops) {
  if (!view) return;
  applyingRemote = true;
  try {
    for (const op of ops) {
      const docLen = view.state.doc.length;
      if (op.type === 'insert') {
        const pos = Math.max(0, Math.min(op.pos, docLen));
        view.dispatch({ changes: { from: pos, insert: op.text } });
      } else if (op.type === 'delete') {
        const from = Math.max(0, Math.min(op.pos, docLen));
        const to   = Math.max(from, Math.min(op.pos + op.length, docLen));
        if (from < to) view.dispatch({ changes: { from, to } });
      }
    }
  } finally {
    applyingRemote = false;
  }
}

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);

  if (msg.type === 'init') {
    myClientId = msg.client_id;
    myColor    = msg.color;
    serverRev  = msg.rev;
    myName = myName || `User_${myClientId.slice(0, 4)}`;
    document.getElementById('display-name-input').value = myName;
    if (myName) ws.send(JSON.stringify({ type: 'rename', name: myName }));
    for (const c of (msg.clients || [])) {
      peers.set(c.client_id, { name: c.name, color: c.color, cursorPos: c.cursor_pos });
    }
    updateParticipantsList();
    initEditor(msg.doc);

  } else if (msg.type === 'ack') {
    serverRev = msg.rev;
    inflight  = null;
    flushBuffer();

  } else if (msg.type === 'op') {
    serverRev = msg.rev;
    const serverOps = msg.ops || [];

    // Transform server ops through client's pending state so they can be
    // applied on top of the editor (which already has inflight + buffer applied).
    let toApply = serverOps;
    if (inflight) toApply = transformOps(toApply, inflight.ops);
    toApply = transformOps(toApply, buffer);

    // Transform pending ops against server ops (update our pending state).
    if (inflight) inflight = { ...inflight, ops: transformOps(inflight.ops, serverOps) };
    buffer = transformOps(buffer, serverOps);

    applyOpsToEditor(toApply);

  } else if (msg.type === 'join') {
    peers.set(msg.client_id, { name: msg.name, color: msg.color, cursorPos: 0 });
    updateParticipantsList();
  } else if (msg.type === 'leave') {
    peers.delete(msg.client_id);
    updateParticipantsList();
  } else if (msg.type === 'rename') {
    if (peers.has(msg.client_id)) peers.get(msg.client_id).name = msg.name;
    updateParticipantsList();
  } else if (msg.type === 'cursor') {
    if (peers.has(msg.client_id)) peers.get(msg.client_id).cursorPos = msg.pos;
  }
};

// ── UI ────────────────────────────────────────────────────────────────────────

langSelect.addEventListener('change', () => {
  const key = langSelect.value;
  if (!LANG[key]) return;
  localStorage.setItem(LS_LANG, key);
  if (view) view.dispatch({ effects: languageConf.reconfigure(LANG[key]()) });
});

const participantsList = document.getElementById('participants-list');

function updateParticipantsList() {
  participantsList.innerHTML = '';
  const me = document.createElement('div');
  me.className = 'participant';
  const myAv = document.createElement('div');
  myAv.className = 'avatar';
  myAv.style.backgroundColor = myColor;
  myAv.textContent = (myName || 'Me').charAt(0).toUpperCase();
  const myLbl = document.createElement('span');
  myLbl.className = 'p-name';
  myLbl.textContent = (myName || 'Me') + ' (You)';
  me.append(myAv, myLbl);
  participantsList.appendChild(me);

  for (const [, p] of peers) {
    const item = document.createElement('div');
    item.className = 'participant';
    const av = document.createElement('div');
    av.className = 'avatar';
    av.style.backgroundColor = p.color;
    av.textContent = p.name.charAt(0).toUpperCase();
    const nm = document.createElement('span');
    nm.className = 'p-name';
    nm.textContent = p.name;
    item.append(av, nm);
    participantsList.appendChild(item);
  }
}

const displayNameInput = document.getElementById('display-name-input');
const renameBtn        = document.getElementById('rename-btn');
displayNameInput.value = myName;

renameBtn.addEventListener('click', () => {
  const n = displayNameInput.value.trim().slice(0, 24);
  if (!n) return;
  myName = n;
  localStorage.setItem('syncspace-ot-name', n);
  if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'rename', name: n }));
  showToast('Display name updated');
  updateParticipantsList();
});
displayNameInput.addEventListener('keydown', e => { if (e.key === 'Enter') renameBtn.click(); });

const shareBtn = document.getElementById('share-btn');
let shareUrl = location.href;

async function refreshShareUrl() {
  try {
    const res = await fetch(`/api/share-link?session=${encodeURIComponent(sessionId)}`);
    if (res.ok) { const d = await res.json(); if (d.url) shareUrl = d.url; }
  } catch { shareUrl = location.href; }
}
refreshShareUrl();

shareBtn.addEventListener('click', async () => {
  try {
    if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(shareUrl);
    else {
      const ta = document.createElement('textarea');
      ta.value = shareUrl;
      ta.style.cssText = 'position:fixed;opacity:0';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
    }
    showToast('Copied to clipboard!');
  } catch { window.prompt('Copy this link:', shareUrl); }
  refreshShareUrl();
});

const toast = document.getElementById('toast');
function showToast(msg, ms = 2000) {
  toast.textContent = msg;
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), ms);
}
