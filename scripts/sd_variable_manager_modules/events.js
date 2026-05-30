'use strict';
// ============================================================
//  events.js — 全イベントリスナー
// ============================================================

const SYM_MAP = {
  'sep':   ' // ', 'semi': ';', 'open': '{ ',
  'close': ' }',   'neg':  ' !! ', 'div': '\n---\n',
};

function initEventListeners() {

  // ---- Header ----
  document.getElementById('btnForgeUrl').onclick = () => {
    const url = prompt('Forge URL:', getForgeUrl());
    if (url) setForgeUrl(url.replace(/\/+$/, ''));
  };
  document.getElementById('btnExport').onclick = exportJSON;
  document.getElementById('btnImportTrigger').onclick = () => document.getElementById('importFile').click();
  document.getElementById('importFile').onchange = importJSON;
  document.getElementById('btnMergeImportTrigger').onclick = () => document.getElementById('mergeImportFile').click();
  document.getElementById('mergeImportFile').onchange = mergeImportJSON;

  // Undo/Redo
  document.getElementById('btnUndo').onclick = () => { if (state.undo()) renderAll(); };
  document.getElementById('btnRedo').onclick = () => { if (state.redo()) renderAll(); };
  document.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
      e.preventDefault();
      if (state.undo()) { renderAll(); toast('元に戻しました'); }
    }
    if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || (e.shiftKey && e.key === 'z'))) {
      e.preventDefault();
      if (state.redo()) { renderAll(); toast('やり直しました'); }
    }
  });

  // テーマピッカー
  document.getElementById('btnTheme').onclick = (e) => { e.stopPropagation(); toggleThemePicker(); };
  document.getElementById('themePicker').addEventListener('click', (e) => {
    const btn = e.target.closest('.theme-opt');
    if (!btn) return;
    applyTheme(btn.dataset.theme);
    document.getElementById('themePicker').style.display = 'none';
  });

  // ---- Sidebar ----
  document.getElementById('btnExpandAll').onclick   = () => { setOpenAll(state.categories, true); renderTree(); };
  document.getElementById('btnCollapseAll').onclick = () => { setOpenAll(state.categories, false); renderTree(); };
  document.getElementById('btnAddRootCat').onclick  = () => showAddCategoryModal(null);

  // Tree
  document.getElementById('treeContainer').addEventListener('click', (e) => {
    const header = e.target.closest('.tree-node-header');
    if (!header) return;
    if (e.target.dataset.action === 'toggle') { e.stopPropagation(); toggleNode(parseInt(e.target.dataset.id)); return; }
    selectCat(parseInt(header.dataset.catId));
  });
  document.getElementById('treeContainer').addEventListener('dblclick', (e) => {
    const header = e.target.closest('.tree-node-header');
    if (header) toggleNode(parseInt(header.dataset.catId));
  });
  document.getElementById('treeContainer').addEventListener('contextmenu', (e) => {
    const header = e.target.closest('.tree-node-header');
    if (header) showContextMenu(e, parseInt(header.dataset.catId));
  });

  // ---- Main toolbar ----
  document.getElementById('searchInput').oninput = (e) => { state.searchQuery = e.target.value; renderVars(); };
  document.getElementById('btnAddVar').onclick = showAddVariableModal;

  // Breadcrumb
  document.getElementById('breadcrumb').addEventListener('click', (e) => {
    if (e.target.dataset.action === 'select-cat') selectCat(parseInt(e.target.dataset.id) || null);
  });

  // Variable list
  document.getElementById('variableList').addEventListener('click', (e) => {
    const action = e.target.dataset.action;
    if (action === 'add-to-builder') {
      e.stopPropagation();
      builder.addVar(e.target.dataset.name);
      renderAll(); toast(`「${e.target.dataset.name}」を追加`);
      return;
    }
    if (action === 'edit-var')   { e.stopPropagation(); showEditVarModal(parseInt(e.target.dataset.vid), parseInt(e.target.dataset.cid)); return; }
    if (action === 'delete-var') { e.stopPropagation(); delVar(parseInt(e.target.dataset.vid), parseInt(e.target.dataset.cid)); return; }
    if (action === 'copy-name')  { e.stopPropagation(); copyToClipboard(e.target.dataset.name, `「${e.target.dataset.name}」`); return; }
    const header = e.target.closest('.variable-card-header');
    if (header) {
      const body = header.closest('.variable-card')?.querySelector('.variable-card-body');
      if (body) body.classList.toggle('open');
    }
  });

  // ---- Builder header (collapse toggle) ----
  document.getElementById('builderHeader').onclick = (e) => {
    if (e.target.closest('.builder-header-right')) return;
    builder.collapsed = !builder.collapsed;
    document.getElementById('builderPanel').classList.toggle('collapsed', builder.collapsed);
  };

  // ドラッグリサイズ
  const resizeHandle = document.getElementById('builderResizeHandle');
  resizeHandle.addEventListener('mousedown', (e) => {
    e.preventDefault();
    resizeDragging = true;
    resizeStartY = e.clientY;
    resizeStartH = document.getElementById('builderPanel').offsetHeight;
    resizeHandle.classList.add('active');
    document.body.style.userSelect = 'none';
    document.body.style.cursor = 'row-resize';
    document.getElementById('builderPanel').style.transition = 'none';
  });
  document.addEventListener('mousemove', (e) => {
    if (!resizeDragging) return;
    const newH = Math.max(80, Math.min(window.innerHeight * 0.7, resizeStartH + (resizeStartY - e.clientY)));
    const panel = document.getElementById('builderPanel');
    panel.style.setProperty('--builder-height', newH + 'px');
  });
  document.addEventListener('mouseup', () => {
    if (!resizeDragging) return;
    resizeDragging = false;
    resizeHandle.classList.remove('active');
    document.body.style.userSelect = '';
    document.body.style.cursor = '';
    document.getElementById('builderPanel').style.transition = '';
    const h = document.getElementById('builderPanel').style.getPropertyValue('--builder-height');
    if (h) localStorage.setItem('sd_vm_builder_height_custom', h);
  });

  // ---- 行タブ ----
  document.getElementById('rowTabs').addEventListener('click', (e) => {
    if (e.target.dataset.action === 'remove-row') {
      e.stopPropagation();
      builder.removeRow(parseInt(e.target.dataset.rid));
      renderAll();
      return;
    }
    const tab = e.target.closest('.row-tab');
    if (tab) {
      const rowId = parseInt(tab.dataset.rowId);
      builder.activeRowId = rowId;
      const row = builder.rows.find(r => r.id === rowId);
      if (row) builder.activeColId = row.columns[0]?.id ?? 1;
      renderAll();
    }
  });
  document.getElementById('rowTabs').addEventListener('dblclick', (e) => {
    const tab = e.target.closest('.row-tab');
    if (!tab) return;
    e.stopPropagation();
    const rowId = parseInt(tab.dataset.rowId);
    const row = builder.rows.find(r => r.id === rowId);
    if (!row) return;
    const labelSpan = tab.querySelector('.row-tab-label');
    if (!labelSpan) return;
    const input = document.createElement('input');
    input.value = row.label || '';
    input.placeholder = `行${builder.rows.indexOf(row)+1}`;
    input.style.cssText = 'background:transparent;border:none;border-bottom:1px solid var(--accent);color:inherit;font-size:11px;width:70px;outline:none;font-family:inherit;';
    labelSpan.replaceWith(input);
    input.focus(); input.select();
    const finish = () => { row.label = input.value.trim(); renderBuilder(); };
    input.addEventListener('blur', finish);
    input.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); finish(); } if (ev.key === 'Escape') renderBuilder(); });
  });
  document.getElementById('btnAddRow').onclick = () => { builder.addRow(); renderAll(); };

  // プリセット
  document.getElementById('btnSavePreset').onclick = (e) => {
    e.stopPropagation();
    const name = prompt('プリセット名:', `プリセット${builder._presets.length + 1}`);
    if (!name) return;
    builder.savePreset(name);
    toast(`「${name}」を保存`);
  };
  document.getElementById('btnLoadPreset').onclick = (e) => { e.stopPropagation(); togglePresetPanel(); };
  document.getElementById('presetPanel').addEventListener('click', (e) => {
    const action = e.target.dataset.action;
    if (action === 'delete-preset') {
      e.stopPropagation();
      if (!confirm(`「${e.target.dataset.name}」を削除？`)) return;
      builder.deletePreset(e.target.dataset.name);
      renderPresetPanel();
      return;
    }
    const item = e.target.closest('.preset-item');
    if (item) {
      builder.applyPreset(item.dataset.presetName);
      document.getElementById('presetPanel').style.display = 'none';
      renderAll();
      toast(`「${item.dataset.presetName}」を適用`);
    }
  });

  // ---- 列タブ ----
  document.getElementById('btnAddCol').onclick = () => {
    builder.addCol(builder.activeRowId);
    renderAll();
  };
  document.getElementById('colTabs').addEventListener('click', (e) => {
    if (e.target.dataset.action === 'remove-col') {
      e.stopPropagation();
      builder.removeCol(parseInt(e.target.dataset.cid));
      renderAll();
      return;
    }
    const tab = e.target.closest('.col-tab:not(.row-tab)');
    if (tab) { builder.activeColId = parseInt(tab.dataset.colId); renderAll(); }
  });
  document.getElementById('colTabs').addEventListener('dblclick', (e) => {
    const tab = e.target.closest('.col-tab:not(.row-tab)');
    if (!tab) return;
    e.stopPropagation();
    const colId = parseInt(tab.dataset.colId);
    const col = builder.findCol(colId);
    if (!col) return;
    const labelSpan = tab.querySelector('.col-tab-label');
    if (!labelSpan) return;
    const input = document.createElement('input');
    input.value = col.label || '';
    input.placeholder = `列${builder.activeRow()?.columns.indexOf(col)+1}`;
    input.style.cssText = 'background:transparent;border:none;border-bottom:1px solid var(--accent);color:inherit;font-size:11px;width:60px;outline:none;font-family:inherit;';
    labelSpan.replaceWith(input);
    input.focus(); input.select();
    const finish = () => { col.label = input.value.trim(); renderBuilder(); };
    input.addEventListener('blur', finish);
    input.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); finish(); } if (ev.key === 'Escape') renderBuilder(); });
  });

  // ---- 記号パレット ----
  document.getElementById('symbolPalette').addEventListener('mousedown', (e) => {
    if (e.target.closest('.sym-btn')) e.preventDefault();
  });
  document.getElementById('symbolPalette').addEventListener('click', (e) => {
    const btn = e.target.closest('.sym-btn');
    if (!btn) return;
    const sym = SYM_MAP[btn.dataset.sym] ?? btn.dataset.sym;
    const ta = document.getElementById('outputText');
    const start = ta.selectionStart, end = ta.selectionEnd;
    ta.value = ta.value.slice(0, start) + sym + ta.value.slice(end);
    ta.selectionStart = ta.selectionEnd = start + sym.length;
    ta.focus();
    builder.userEdited = true;
    builder.outputText = ta.value;
    document.getElementById('outputHint').textContent = '✏️ 編集中（フォーカスを外すとビルダーに反映）';
    document.getElementById('outputHint').style.color = 'var(--warning)';
  });

  // ---- Output textarea ----
  document.getElementById('outputText').oninput = () => {
    builder.userEdited = true;
    builder.outputText = document.getElementById('outputText').value;
    document.getElementById('outputHint').textContent = '✏️ 編集中（フォーカスを外すとビルダーに反映）';
    document.getElementById('outputHint').style.color = 'var(--warning)';
  };
  document.getElementById('outputText').addEventListener('blur', (e) => {
    if (e.relatedTarget && e.relatedTarget.closest('#builderPanel')) return;
    if (!builder.userEdited) return;
    if (parseImplLine(document.getElementById('outputText').value)) {
      renderBuilder();
      toast('テキストをビルダーに反映しました');
    } else {
      toast('⚠ パース失敗 — ビルダーは変更されませんでした');
    }
  });
  document.getElementById('btnResetText').onclick = () => { builder.userEdited = false; renderBuilder(); toast('ビルダーから再生成'); };
  document.getElementById('btnBuilderClear').onclick = () => { if (!confirm('ビルダーをクリア？')) return; builder.clear(); renderAll(); toast('クリア'); };

  // Copy/Send
  document.getElementById('btnCopyDefs').onclick = () => { const t = builder.buildDefs(state); if (!t) { toast('変数未設定'); return; } copyToClipboard(t, '変数定義'); };
  document.getElementById('btnCopyImpl').onclick = () => { const t = builder.buildImplLine(); if (!t) { toast('列が空'); return; } copyToClipboard(t, '実装行'); };
  document.getElementById('btnCopyAll').onclick  = () => { const t = builder.buildFull(state); if (!t) { toast('内容なし'); return; } copyToClipboard(t, '全体'); };
  document.getElementById('btnSendForge').onclick = sendToForge;

  // Context menu
  document.getElementById('ctxAddChild').onclick = () => { hideContextMenu(); showAddCategoryModal(ctxTargetId); };
  document.getElementById('ctxAddVar').onclick   = () => { hideContextMenu(); state.selectedCategoryId = ctxTargetId; showAddVariableModal(); };
  document.getElementById('ctxRename').onclick   = () => { hideContextMenu(); showRenameCatModal(ctxTargetId); };
  document.getElementById('ctxDelete').onclick   = () => { hideContextMenu(); deleteCat(ctxTargetId); };
  document.addEventListener('click', (e) => {
    hideContextMenu();
    if (!e.target.closest('#splitMenu')) hideSplitMenu();
  });

  // Modal overlay
  document.getElementById('modalOverlay').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) hideModal();
  });
}
