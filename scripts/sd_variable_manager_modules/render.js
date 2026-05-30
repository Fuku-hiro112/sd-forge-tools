'use strict';
// ============================================================
//  render.js — レンダリング関数
// ============================================================

// ---- Tree ----
function renderTree() {
  document.getElementById('treeContainer').innerHTML = renderTreeNodes(state.categories);
}

function renderTreeNodes(nodes) {
  if (!nodes || !nodes.length) return '';
  return nodes.map(n => {
    const hasChildren = n.children && n.children.length;
    const isSelected  = n.id === state.selectedCategoryId;
    const count = state.countVars(n);
    return `<div class="tree-node" data-cat-id="${n.id}">
      <div class="tree-node-header ${isSelected?'selected':''}" draggable="true" data-cat-id="${n.id}">
        <span class="arrow ${n._open?'open':''} ${!hasChildren?'leaf':''}" data-action="toggle" data-id="${n.id}">▶</span>
        <span class="node-icon">${hasChildren?'📁':'📂'}</span>
        <span class="node-label">${esc(n.name)}</span>
        ${count?`<span class="node-count">${count}</span>`:''}
      </div>
      <div class="tree-children ${n._open?'open':''}">
        ${renderTreeNodes(n.children||[])}
      </div>
    </div>`;
  }).join('');
}

// ---- Variable List ----
function renderVars() {
  const el = document.getElementById('variableList');
  let vars;
  if (state.searchQuery) {
    const q = state.searchQuery.toLowerCase();
    vars = state.allVars().filter(v =>
      v.name.toLowerCase().includes(q) ||
      (v.positive||'').toLowerCase().includes(q) ||
      (v.negative||'').toLowerCase().includes(q)
    );
  } else if (state.selectedCategoryId) {
    vars = state.varsUnder(state.selectedCategoryId);
  } else {
    vars = state.allVars();
  }

  if (!vars.length) {
    el.innerHTML = `<div class="empty-state">
      <div class="icon">${state.searchQuery?'🔍':'📂'}</div>
      <p>${state.searchQuery?'一致する変数がありません':'カテゴリを選択するか変数を追加'}</p>
    </div>`;
    return;
  }

  const colIdx = builder.activeRow()?.columns.findIndex(c => c.id === builder.activeColId) + 1 || 1;
  el.innerHTML = vars.map(v => {
    const preview = (v.positive||'').substring(0,40) + ((v.positive||'').length > 40 ? '…' : '');
    return `<div class="variable-card" data-var-id="${v.id}" data-cat-id="${v.categoryId}" draggable="true">
      <div class="variable-card-header">
        <span class="var-drag-handle">⠿</span>
        <span class="var-name">${esc(v.name)}</span>
        <span class="var-preview">${esc(preview)}</span>
        <div class="var-actions">
          <button class="btn-add-builder" data-action="add-to-builder" data-name="${escAttr(v.name)}">＋列${colIdx}</button>
          <button class="btn-icon" data-action="edit-var" data-vid="${v.id}" data-cid="${v.categoryId}">✏️</button>
          <button class="btn-icon" data-action="delete-var" data-vid="${v.id}" data-cid="${v.categoryId}">🗑</button>
          <button class="btn-icon" data-action="copy-name" data-name="${escAttr(v.name)}">📋</button>
        </div>
      </div>
      <div class="variable-card-body" id="vb-${v.id}">
        <div class="value-section">
          <div class="value-label positive">ポジティブ</div>
          <div class="value-content positive">${esc(v.positive||'(未設定)')}</div>
        </div>
        ${v.negative?`<div class="value-section">
          <div class="value-label negative">ネガティブ</div>
          <div class="value-content negative">${esc(v.negative)}</div>
        </div>`:''}
      </div>
    </div>`;
  }).join('');
}

// ---- Breadcrumb ----
function renderBreadcrumb() {
  const el = document.getElementById('breadcrumb');
  if (!state.selectedCategoryId) { el.innerHTML = 'すべての変数'; return; }
  const path = state.catPath(state.selectedCategoryId);
  el.innerHTML = [
    '<span data-action="select-cat" data-id="">すべて</span>',
    ...path.map(n=>`<span data-action="select-cat" data-id="${n.id}">${esc(n.name)}</span>`)
  ].join(' &gt; ');
}

// ---- Chip レンダリング（グループ対応）----
function renderChip(group, groupIdx, colId, rowId) {
  const isGroup = group.length > 1;
  let inner = group.map((name, elemIdx) =>
    `<span class="chip-var${elemIdx>0?' has-comma':''}"
       data-action="chip-hover" data-var-name="${escAttr(name)}"
       data-elem-idx="${elemIdx}">${elemIdx>0?'<span class="chip-comma">,</span>':''}${esc(name)}</span>`
  ).join('');

  const splitBtn = isGroup
    ? `<span class="chip-split" data-action="chip-split"
         data-col-id="${colId}" data-row-id="${rowId}" data-group-idx="${groupIdx}" title="分割">⊣</span>`
    : '';
  const removeBtn = `<span class="chip-remove" data-action="remove-chip"
    data-col-id="${colId}" data-row-id="${rowId}" data-group-idx="${groupIdx}" title="削除">✕</span>`;

  return `<span class="col-var-chip${isGroup?' comma-group':''}" draggable="true"
    data-group-idx="${groupIdx}" data-col-id="${colId}" data-row-id="${rowId}"
    data-var-name0="${escAttr(group[0])}"
    title="${esc(group.join(','))}"
  >${inner}${splitBtn}${removeBtn}</span>`;
}

// ---- Builder ----
function renderBuilder() {
  const activeRow = builder.activeRow();

  // ── 行タブ ──
  const rowTabs = document.getElementById('rowTabs');
  if (rowTabs) {
    const rowHtmls = builder.rows.map((row, i) => {
      const isActive = row.id === builder.activeRowId;
      const labelText = row.label || `行${i+1}`;
      const closBtn = builder.rows.length > 1
        ? `<span class="row-tab-close" data-action="remove-row" data-rid="${row.id}">✕</span>` : '';
      return `<span class="col-tab row-tab ${isActive?'active':''}"
        draggable="true" data-row-idx="${i}" data-row-id="${row.id}"
      ><span class="col-tab-label row-tab-label">${esc(labelText)}</span>${closBtn}</span>`;
    });
    const withRowSeps = [];
    rowHtmls.forEach((h, i) => {
      withRowSeps.push(`<span class="row-tab-drop" data-row-drop="${i}"></span>`);
      withRowSeps.push(h);
    });
    withRowSeps.push(`<span class="row-tab-drop" data-row-drop="${builder.rows.length}"></span>`);
    rowTabs.innerHTML = withRowSeps.join('');
  }

  // ── 列タブ ──
  const colTabs = document.getElementById('colTabs');
  if (colTabs && activeRow) {
    const tabHtmls = activeRow.columns.map((col, i) => {
      const isActive = col.id === builder.activeColId;
      const labelText = col.label || `列${i+1}`;
      const varCount  = col.vars.length;
      const closeBtn  = activeRow.columns.length > 1
        ? `<span class="col-tab-close" data-action="remove-col" data-cid="${col.id}">✕</span>` : '';
      return `<div class="col-tab${isActive?' active':''}${col.shuffle?' shuffle-group':''}"
        draggable="true" data-col-idx="${i}" data-col-id="${col.id}" data-row-id="${activeRow.id}">
        <span class="col-tab-label">${esc(labelText)}</span>
        ${col.shuffle?'<span class="col-tab-shuffle"> {…}</span>':''}
        ${varCount?`<span class="col-tab-count"> (${varCount})</span>`:''}
        ${closeBtn}
      </div>`;
    });
    const withSeps = [];
    tabHtmls.forEach((h, i) => {
      withSeps.push(`<span class="col-tab-drop" data-col-drop="${i}" data-row-id="${activeRow.id}"></span>`);
      if (i > 0) withSeps.push('<span class="col-sep">//</span>');
      withSeps.push(h);
    });
    withSeps.push(`<span class="col-tab-drop" data-col-drop="${activeRow.columns.length}" data-row-id="${activeRow.id}"></span>`);
    colTabs.innerHTML = withSeps.join('');
  }

  // ── チップ ──
  const cc = document.getElementById('colContent');
  const col = builder.activeCol();
  if (!col || !col.vars.length) {
    const idx = col && activeRow ? activeRow.columns.indexOf(col) + 1 : 1;
    cc.innerHTML = `<div class="builder-col-empty">変数カードの「＋列${idx}」をクリックして追加</div>
      <input type="text" id="quickVarInput" class="quick-var-input" placeholder="$変数名を直接入力..." autocomplete="off" spellcheck="false">`;
  } else {
    let html = '';
    col.vars.forEach((group, gIdx) => {
      html += `<span class="chip-drop-zone" data-drop-idx="${gIdx}" data-col-id="${col.id}" data-row-id="${activeRow.id}"></span>`;
      html += renderChip(group, gIdx, col.id, activeRow.id);
    });
    html += `<span class="chip-drop-zone" data-drop-idx="${col.vars.length}" data-col-id="${col.id}" data-row-id="${activeRow.id}"></span>`;
    html += `<input type="text" id="quickVarInput" class="quick-var-input" placeholder="$変数名…" autocomplete="off" spellcheck="false">`;
    cc.innerHTML = html;
  }

  // quickVarInput イベント（毎レンダリング後に再バインド）
  const qi = document.getElementById('quickVarInput');
  if (qi) {
    qi.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter') return;
      let name = qi.value.trim();
      if (!name) return;
      if (!name.startsWith('$')) name = '$' + name;
      builder.addVar(name);
      renderBuilder();
      toast(`「${name}」を追加`);
    });
  }


  // ── 出力テキスト ──
  const ta   = document.getElementById('outputText');
  const hint = document.getElementById('outputHint');
  if (!builder.userEdited) {
    const generated = builder.buildFromColumns(state);
    builder.outputText = generated;
    if (document.activeElement !== ta) ta.value = generated;
    hint.textContent = 'ビルダーと同期中';
    hint.style.color = 'var(--text-muted)';
  } else {
    hint.textContent = '✏️ 編集中（フォーカスを外すとビルダーに反映）';
    hint.style.color = 'var(--warning)';
  }

  // Undo/Redo ボタン活性
  const btnUndo = document.getElementById('btnUndo');
  const btnRedo = document.getElementById('btnRedo');
  if (btnUndo) btnUndo.style.opacity = state._undoStack.length ? '1' : '0.3';
  if (btnRedo) btnRedo.style.opacity = state._redoStack.length ? '1' : '0.3';
}

function renderAll() {
  renderTree();
  renderVars();
  renderBreadcrumb();
  renderBuilder();
}

// ---- チップホバープレビュー ----
let _tooltipTimer = null;

function showChipTooltip(el, varName) {
  clearTimeout(_tooltipTimer);
  _tooltipTimer = setTimeout(() => {
    const v = state.findVarByName(varName);
    const tip = document.getElementById('chipTooltip');
    if (!tip) return;
    if (!v) { tip.innerHTML = `<span style="color:var(--warning)">${esc(varName)} — 未定義</span>`; }
    else {
      tip.innerHTML =
        `<div style="font-weight:700;color:var(--accent);margin-bottom:4px;">${esc(v.name)}</div>` +
        `<div style="color:var(--positive);font-size:10px;margin-bottom:2px;">POS</div>` +
        `<div style="word-break:break-all;">${esc(v.positive||'(未設定)')}</div>` +
        (v.negative ? `<div style="color:var(--negative);font-size:10px;margin:4px 0 2px;">NEG</div><div>${esc(v.negative)}</div>` : '');
    }
    const rect = el.getBoundingClientRect();
    tip.style.display = 'block';
    const tipW = 260;
    let left = rect.left;
    if (left + tipW > window.innerWidth) left = window.innerWidth - tipW - 8;
    tip.style.left = left + 'px';
    tip.style.top  = (rect.bottom + 4) + 'px';
  }, 300);
}

function hideChipTooltip() {
  clearTimeout(_tooltipTimer);
  const tip = document.getElementById('chipTooltip');
  if (tip) tip.style.display = 'none';
}

// ---- 分割メニュー ----
function showSplitMenu(btn, colId, rowId, groupIdx) {
  const col = builder.findCol(colId);
  if (!col) return;
  const group = col.vars[groupIdx];
  if (!group || group.length < 2) return;

  hideSplitMenu();

  if (group.length === 2) {
    builder.splitVar(colId, groupIdx, 0);
    renderBuilder();
    return;
  }

  const menu = document.createElement('div');
  menu.className = 'split-menu';
  menu.id = 'splitMenu';
  group.forEach((name, elemIdx) => {
    const item = document.createElement('div');
    item.className = 'split-menu-item';
    item.textContent = `⊣ ${name} を分割`;
    item.onclick = (e) => {
      e.stopPropagation();
      builder.splitVar(colId, groupIdx, elemIdx);
      hideSplitMenu();
      renderBuilder();
    };
    menu.appendChild(item);
  });

  const rect = btn.getBoundingClientRect();
  let left = rect.left, top = rect.bottom + 2;
  if (left + 160 > window.innerWidth) left = window.innerWidth - 164;
  if (top + 160 > window.innerHeight) top = rect.top - 162;
  menu.style.cssText = `position:fixed;left:${left}px;top:${top}px;z-index:3000;`;
  document.body.appendChild(menu);

  setTimeout(() => document.addEventListener('click', hideSplitMenu, { once: true }), 0);
}

function hideSplitMenu() {
  document.getElementById('splitMenu')?.remove();
}

// ---- テーマピッカー表示 ----
// .app は display:grid + z-index:1 で grid 兄弟 (.main 等) のペイントが
// 内部の position:fixed 要素を z-index に関わらず覆い隠す挙動があるため、
// 初回オープン時に themePicker を body 直下に portal する。
function toggleThemePicker() {
  const p = document.getElementById('themePicker');
  if (!p) return;
  if (p.parentElement !== document.body) {
    document.body.appendChild(p);
  }
  const isOpen = p.style.display !== 'none' && p.style.display !== '';
  if (isOpen) {
    p.style.display = 'none';
    return;
  }
  const btn = document.getElementById('btnTheme');
  const r = btn.getBoundingClientRect();
  p.style.position = 'fixed';
  p.style.top = (r.bottom + 10) + 'px';
  p.style.right = (window.innerWidth - r.right) + 'px';
  p.style.left = 'auto';
  p.style.zIndex = '2500';
  p.style.display = 'block';
  setTimeout(() => document.addEventListener('click', () => {
    if (p) p.style.display = 'none';
  }, { once: true }), 0);
}

// ---- プリセットパネル ----
function renderPresetPanel() {
  const panel = document.getElementById('presetPanel');
  if (!panel) return;
  if (!builder._presets.length) {
    panel.innerHTML = '<div style="font-size:11px;color:var(--text-muted);padding:6px 8px;">保存済みプリセットなし</div>';
    return;
  }
  panel.innerHTML = builder._presets.map(p =>
    `<div class="preset-item" data-preset-name="${escAttr(p.name)}">
      <span class="preset-name">${esc(p.name)}</span>
      <button class="btn-icon preset-del" data-action="delete-preset" data-name="${escAttr(p.name)}" title="削除">🗑</button>
    </div>`
  ).join('');
}

function togglePresetPanel() {
  const p = document.getElementById('presetPanel');
  if (!p) return;
  const isOpen = p.style.display !== 'none';
  p.style.display = isOpen ? 'none' : 'block';
  if (!isOpen) {
    renderPresetPanel();
    setTimeout(() => document.addEventListener('click', (e) => {
      if (!e.target.closest('#presetPanel') && !e.target.closest('#btnLoadPreset')) {
        p.style.display = 'none';
      }
    }, { once: true }), 0);
  }
}
