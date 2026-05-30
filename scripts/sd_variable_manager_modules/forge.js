'use strict';
// ============================================================
//  forge.js — Forge API連携・Import/Export
// ============================================================

function getForgeUrl() {
  return localStorage.getItem(FORGE_URL_KEY) || 'http://127.0.0.1:7860';
}

function setForgeUrl(url) {
  localStorage.setItem(FORGE_URL_KEY, url);
}

// ============================================================
//  Phase A: vars/variables.json 自動同期 (state.save() から発火)
// ============================================================
let _syncTimer = null;
let _syncInFlight = false;
const SYNC_DEBOUNCE_MS = 500;

function queueSyncToForge() {
  clearTimeout(_syncTimer);
  _syncTimer = setTimeout(syncToForgeNow, SYNC_DEBOUNCE_MS);
}

async function syncToForgeNow() {
  if (_syncInFlight) {
    // 進行中ならもう一度キューする（最終状態を確実に送る）
    queueSyncToForge();
    return;
  }
  _syncInFlight = true;
  updateSyncBadge('syncing');
  try {
    const r = await fetch(`${getForgeUrl()}/vram_safe_batch/api/sync_variables`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: 'replace', categories: state.categories }),
    });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    if (data.status === 'ok') {
      updateSyncBadge('ok', data.variables_written);
      localStorage.removeItem('sd_vm_pending_sync');
    } else {
      throw new Error(data.message || 'unknown');
    }
  } catch (e) {
    const msg = (e && e.message) || String(e);
    if (msg.startsWith('HTTP')) {
      updateSyncBadge('error', msg);
    } else {
      updateSyncBadge('offline', msg);
    }
    localStorage.setItem('sd_vm_pending_sync', '1');
  } finally {
    _syncInFlight = false;
  }
}

function updateSyncBadge(status, detail) {
  const el = document.getElementById('syncBadge');
  if (!el) return;
  const map = {
    syncing: { txt: '🔵 同期中…', cls: 'sync-syncing', title: '' },
    ok:      { txt: `🟢 同期済${detail != null ? ' (' + detail + '件)' : ''}`,
               cls: 'sync-ok',     title: '最新が Forge に反映されています' },
    offline: { txt: '🟠 未同期 (Forge オフライン)',
               cls: 'sync-offline', title: 'Forge 起動後に再送されます: ' + (detail || '') },
    error:   { txt: '🔴 同期エラー', cls: 'sync-error',
               title: 'サーバエラー: ' + (detail || '') },
  };
  const m = map[status] || map.ok;
  el.textContent = m.txt;
  el.className = 'sync-badge ' + m.cls;
  el.title = m.title;
}

async function fetchForgeVariables() {
  try {
    const r = await fetch(`${getForgeUrl()}/vram_safe_batch/api/variables`);
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}

// ============================================================
//  Phase B: SSE (vars/variables.json 変更通知) リスナー + マージ
// ============================================================
let _eventSource = null;
let _eventSourceRetry = 0;

function startVariablesEventStream() {
  if (_eventSource) return;
  const url = `${getForgeUrl()}/vram_safe_batch/api/variables/events`;
  try {
    _eventSource = new EventSource(url);
  } catch (e) {
    console.warn('[VarManager] EventSource not available:', e);
    return;
  }

  _eventSource.addEventListener('ready', () => {
    _eventSourceRetry = 0;
    if (typeof updateSyncBadge === 'function') {
      // すでに ok 表示中なら維持。offline 中ならクリア
      const badge = document.getElementById('syncBadge');
      if (badge && badge.classList.contains('sync-offline')) {
        updateSyncBadge('ok');
      }
    }
  });

  _eventSource.onmessage = async (ev) => {
    // 外部編集による mtime 変化通知 → Forge から最新を取得してマージ
    try {
      const remote = await fetchForgeVariables();
      if (!remote || !Array.isArray(remote.categories)) return;
      const merged = mergeLocalRemoteByUpdatedAt(state.categories, remote.categories);
      if (JSON.stringify(merged) === JSON.stringify(state.categories)) return;  // 実質変化なし
      state._suppressSync = true;  // 取り込み中の自動再同期を抑止
      state.categories = merged;
      state.recalcNextId();
      state.save();
      state._suppressSync = false;
      if (typeof renderAll === 'function') renderAll();
      if (typeof toast === 'function') toast('🔄 Forge 側変更を取り込みました');
      updateSyncBadge('ok');
    } catch (e) {
      console.error('[VarManager] SSE merge failed:', e);
    }
  };

  _eventSource.onerror = () => {
    // EventSource は自動再接続するが、長時間切れたら badge で通知
    _eventSourceRetry++;
    if (_eventSourceRetry > 3) updateSyncBadge('offline', 'SSE 接続切れ');
  };
}

// 変数 name キーで last-write-wins マージ（Forge backend の merge_by_updated_at と同等）.
function mergeLocalRemoteByUpdatedAt(local, remote) {
  const seen = new Set();
  const merged = [];
  const localByName = new Map((local || []).map(n => [n && n.name, n]));
  const remoteByName = new Map((remote || []).map(n => [n && n.name, n]));
  for (const lnode of (local || [])) {
    if (!lnode || typeof lnode !== 'object') continue;
    seen.add(lnode.name);
    const rnode = remoteByName.get(lnode.name);
    if (!rnode) { merged.push(_deepCopyNode(lnode)); continue; }
    merged.push(_mergeOneNode(lnode, rnode));
  }
  for (const rnode of (remote || [])) {
    if (!rnode || typeof rnode !== 'object') continue;
    if (seen.has(rnode.name)) continue;
    merged.push(_deepCopyNode(rnode));
  }
  return merged;
}

function _mergeOneNode(lnode, rnode) {
  return {
    ...lnode,
    name: lnode.name,
    variables: _mergeVariables(lnode.variables || [], rnode.variables || []),
    children: mergeLocalRemoteByUpdatedAt(lnode.children || [], rnode.children || []),
  };
}

function _mergeVariables(lvars, rvars) {
  const remoteByName = new Map((rvars || []).map(v => [v && v.name, v]));
  const merged = [];
  const seen = new Set();
  for (const lv of lvars) {
    if (!lv || typeof lv !== 'object') continue;
    seen.add(lv.name);
    const rv = remoteByName.get(lv.name);
    if (!rv) { merged.push({ ...lv }); continue; }
    merged.push(_pickNewerVar(lv, rv));
  }
  for (const rv of rvars) {
    if (!rv || typeof rv !== 'object') continue;
    if (seen.has(rv.name)) continue;
    merged.push({ ...rv });
  }
  return merged;
}

function _pickNewerVar(lv, rv) {
  const lt = lv.updated_at || '';
  const rt = rv.updated_at || '';
  return rt > lt ? { ...rv } : { ...lv };
}

function _deepCopyNode(node) {
  return {
    ...node,
    variables: (node.variables || []).filter(v => v && typeof v === 'object').map(v => ({ ...v })),
    children: (node.children || []).filter(c => c && typeof c === 'object').map(_deepCopyNode),
  };
}

// Phase B: ツリー全変数に updated_at が無ければ現在時刻でスタンプ（Import 時等）.
function stampMissingUpdatedAt(categories) {
  const ts = (typeof nowUtcIso === 'function')
    ? nowUtcIso()
    : new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
  const walk = (nodes) => {
    for (const node of nodes || []) {
      for (const v of (node.variables || [])) {
        if (v && typeof v === 'object' && !v.updated_at) v.updated_at = ts;
      }
      walk(node.children);
    }
  };
  walk(categories);
  return categories;
}

async function sendToForge() {
  const text = builder.buildFull(state);
  if (!text) { toast('送信内容なし'); return; }
  const url = getForgeUrl();
  try {
    const res = await fetch(`${url}/vram_safe_batch/api/set_jobs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ group_list: text }),
    });
    if (!res.ok) { toast(`送信エラー: HTTP ${res.status}`); return; }
    const data = await res.json();
    if (data.status === 'ok') {
      toast('✓ Forgeに送信完了！「読み込み」ボタンを押してください');
    } else {
      toast('送信エラー: ' + (data.message || '不明'));
    }
  } catch (e) {
    toast('接続失敗: ' + url);
    const newUrl = prompt('Forge URLを入力:', url);
    if (newUrl) setForgeUrl(newUrl.replace(/\/+$/, ''));
  }
}

function exportJSON() {
  const data = {
    categories: state.categories,
    nextId: state.nextId,
    lastCategoryId: state.lastCategoryId,
    exportedAt: new Date().toISOString(),
  };
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `sd_variables_${new Date().toISOString().slice(0, 10)}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
  toast('Export完了');
}

// マージインポート: 既存変数を保持したまま、インポートしたカテゴリをトップレベルに追加
// ID は全て採番し直して衝突を回避する
function mergeImportJSON(event) {
  const file = event.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    try {
      const data = JSON.parse(e.target.result);
      if (!AppState.validateImportData(data)) { toast('無効なファイル形式です'); return; }
      if (!confirm('既存の変数は保持し、インポート分を追加します。よろしいですか？')) return;
      state.pushUndo();

      // ID を採番し直す
      const reassign = (nodes) => {
        for (const n of nodes) {
          n.id = state.genId();
          if (n.variables) for (const v of n.variables) v.id = state.genId();
          if (n.children) reassign(n.children);
        }
      };
      const imported = data.categories || [];
      reassign(imported);

      // 既存変数名と衝突する場合はスキップ（変更しない）
      const existingNames = new Set(state.allVars().map(v => v.name));
      const filterDup = (nodes) => {
        for (const n of nodes) {
          if (n.variables) n.variables = n.variables.filter(v => !existingNames.has(v.name));
          if (n.children) filterDup(n.children);
        }
      };
      filterDup(imported);

      stampMissingUpdatedAt(imported);
      state.categories.push(...imported);
      state.save();
      renderAll();
      toast(`Merge Import 完了 (${imported.length} カテゴリ追加)`);
    } catch (err) {
      console.error(err);
      toast('ファイルの読み込みに失敗');
    }
  };
  reader.readAsText(file);
  event.target.value = '';
}

function importJSON(event) {
  const file = event.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    try {
      const data = JSON.parse(e.target.result);
      if (!AppState.validateImportData(data)) { toast('無効なファイル形式です'); return; }
      if (!confirm('上書きインポート？')) return;
      state.pushUndo();
      stampMissingUpdatedAt(data.categories);
      state.categories = data.categories;
      state.lastCategoryId = data.lastCategoryId || null;
      state.selectedCategoryId = null;
      state.recalcNextId();
      state.save();
      renderAll();
      toast('Import完了');
    } catch {
      toast('ファイルの読み込みに失敗');
    }
  };
  reader.readAsText(file);
  event.target.value = '';
}
