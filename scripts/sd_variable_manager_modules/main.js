'use strict';
// ============================================================
//  main.js — 初期化
// ============================================================

state.load();
builder.loadPresets();
initTheme();
initDnD();
initEventListeners();

restoreBuilderHeight();

renderAll();

// ============================================================
//  Phase A: 起動時に Forge と疎通確認 + 取り込み判定
// ============================================================
(async () => {
  updateSyncBadge('syncing');
  const remote = await fetchForgeVariables();
  if (!remote) {
    updateSyncBadge('offline', 'Forge 接続不可');
    return;
  }
  const remoteCategories = remote.categories || [];
  const localEmpty = (state.categories || []).length === 0;
  const remoteHasData = remoteCategories.length > 0;

  // Manager 側が空 & Forge 側にデータがある → 黙って取り込み
  if (localEmpty && remoteHasData) {
    state._suppressSync = true;
    state.categories = remoteCategories;
    state.recalcNextId();
    state.save();
    state._suppressSync = false;
    renderAll();
    updateSyncBadge('ok', countAllVars(remoteCategories));
    return;
  }

  // Phase B: 内容が異なる場合は updated_at マージで自動統合（ダイアログ無し）.
  const localJson = JSON.stringify(state.categories);
  const remoteJson = JSON.stringify(remoteCategories);
  if (remoteHasData && localJson !== remoteJson) {
    const merged = mergeLocalRemoteByUpdatedAt(state.categories, remoteCategories);
    state._suppressSync = true;
    state.categories = merged;
    state.recalcNextId();
    state.save();
    state._suppressSync = false;
    renderAll();
    // マージ結果を Forge にも書き戻して両側を一致させる
    syncToForgeNow();
    return;
  }

  // 一致 or Forge 側空 で Manager 側にデータあり → 同期実行（書き出し）
  if (!localEmpty) {
    syncToForgeNow();
  } else {
    updateSyncBadge('ok', 0);
  }
})();

// Phase B: SSE で variables.json 変更通知を購読（外部エディタによる手動編集を即反映）
startVariablesEventStream();

function countAllVars(categories) {
  let n = 0;
  const walk = (nodes) => {
    for (const node of nodes) {
      n += (node.variables || []).length;
      walk(node.children || []);
    }
  };
  walk(categories || []);
  return n;
}

// Forge 起動検知用: window focus 時に pending_sync があれば再送
window.addEventListener('focus', () => {
  if (localStorage.getItem('sd_vm_pending_sync') === '1') {
    syncToForgeNow();
  }
});
