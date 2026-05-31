'use strict';
// ============================================================
//  dnd.js — ドラッグ＆ドロップ（全4システム）
// ============================================================

function initDnD() {
  const treeContainer = document.getElementById('treeContainer');
  const colTabs       = document.getElementById('colTabs');
  const colContent    = document.getElementById('colContent');
  const variableList  = document.getElementById('variableList');
  const rowTabs       = document.getElementById('rowTabs');

  // ================================================================
  //  A. カテゴリツリー D&D（カテゴリ移動 / 変数→カテゴリ移動）
  // ================================================================
  treeContainer.addEventListener('dragstart', (e) => {
    const header = e.target.closest('.tree-node-header');
    if (header) { catDragId = parseInt(header.dataset.catId); e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', 'cat'); }
  });

  treeContainer.addEventListener('dragend', () => {
    catDragId = null;
    treeContainer.querySelectorAll('.tree-node-header').forEach(el =>
      el.classList.remove('drag-over-above', 'drag-over-below', 'drag-over-into'));
  });

  treeContainer.addEventListener('dragover', (e) => {
    const header = e.target.closest('.tree-node-header');
    if (!header) return;
    const targetId = parseInt(header.dataset.catId);

    if (catDragId !== null) {
      if (catDragId === targetId) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      const rect = header.getBoundingClientRect();
      const y = e.clientY - rect.top;
      const zone = y < rect.height * 0.25 ? 'above' : y > rect.height * 0.75 ? 'below' : 'into';
      header.classList.remove('drag-over-above', 'drag-over-below', 'drag-over-into');
      header.classList.add('drag-over-' + zone);
      header.dataset.dropZone = zone;
    } else if (varDragId !== null) {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      treeContainer.querySelectorAll('.tree-node-header').forEach(el => el.classList.remove('drag-over-into'));
      header.classList.add('drag-over-into');
    }
  });

  treeContainer.addEventListener('dragleave', (e) => {
    const header = e.target.closest('.tree-node-header');
    if (header) header.classList.remove('drag-over-above', 'drag-over-below', 'drag-over-into');
  });

  treeContainer.addEventListener('drop', (e) => {
    e.preventDefault();
    const header = e.target.closest('.tree-node-header');
    if (!header) return;
    const targetId = parseInt(header.dataset.catId);
    header.classList.remove('drag-over-above', 'drag-over-below', 'drag-over-into');

    if (catDragId !== null) {
      const zone = header.dataset.dropZone || 'into';
      if (catDragId === targetId) { catDragId = null; return; }
      if (state.isDescendantOf(catDragId, targetId)) { toast('子孫カテゴリには移動できません'); catDragId = null; return; }
      const dragNode = state.detachNode(catDragId);
      if (!dragNode) { catDragId = null; return; }
      state.pushUndo();
      if (zone === 'into') {
        const target = state.findCat(targetId);
        if (target) { if (!target.children) target.children = []; target.children.push(dragNode); target._open = true; }
      } else {
        const targetParent = state.findParent(targetId);
        const siblings = targetParent === null ? state.categories : (targetParent ? targetParent.children : state.categories);
        const targetIdx = siblings.findIndex(c => c.id === targetId);
        siblings.splice(zone === 'above' ? targetIdx : targetIdx + 1, 0, dragNode);
      }
      catDragId = null;
      state.save(); renderAll(); toast(`「${dragNode.name}」を移動`);
    } else if (varDragId !== null) {
      const targetCatName = state.findCat(targetId)?.name || '';
      if (varDragCatId === targetId) { varDragId = null; varDragCatId = null; return; }
      state.pushUndo();
      if (state.moveVarToCategory(varDragId, targetId)) { toast(`変数を「${targetCatName}」に移動`); renderAll(); }
      varDragId = null; varDragCatId = null;
    }
  });

  // ================================================================
  //  B. 変数カード D&D（変数リスト → カテゴリ）
  // ================================================================
  variableList.addEventListener('dragstart', (e) => {
    const card = e.target.closest('.variable-card');
    if (!card) return;
    if (e.target.closest('.var-actions')) { e.preventDefault(); return; }
    varDragId   = parseInt(card.dataset.varId);
    varDragCatId = parseInt(card.dataset.catId);
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', 'var');
    card.classList.add('dragging');
    setTimeout(() => {
      treeContainer.querySelectorAll('.tree-node-header').forEach(el => el.classList.add('var-drop-hint'));
    }, 0);
  });
  variableList.addEventListener('dragend', () => {
    document.querySelectorAll('.variable-card.dragging').forEach(el => el.classList.remove('dragging'));
    treeContainer.querySelectorAll('.tree-node-header').forEach(el =>
      el.classList.remove('var-drop-hint', 'drag-over-into'));
    varDragId = null; varDragCatId = null;
  });

  // ================================================================
  //  C. 行タブ D&D（行の並び替え）
  // ================================================================
  document.getElementById('builderColumns').addEventListener('dragstart', (e) => {
    const tab = e.target.closest('.row-tab');
    if (tab) {
      rowDragIdx = parseInt(tab.dataset.rowIdx);
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', 'row');
      tab.classList.add('dragging');
    }
  });
  document.getElementById('builderColumns').addEventListener('dragend', (e) => {
    const tab = e.target.closest('.row-tab');
    if (tab) tab.classList.remove('dragging');
    rowDragIdx = -1;
    document.querySelectorAll('.row-tab-drop').forEach(z => z.classList.remove('drag-over'));
  });
  document.getElementById('rowTabs').addEventListener('dragover', (e) => {
    const drop = e.target.closest('.row-tab-drop');
    if (drop && rowDragIdx >= 0) { e.preventDefault(); drop.classList.add('drag-over'); }
  });
  document.getElementById('rowTabs').addEventListener('dragleave', (e) => {
    const drop = e.target.closest('.row-tab-drop');
    if (drop) drop.classList.remove('drag-over');
  });
  document.getElementById('rowTabs').addEventListener('drop', (e) => {
    e.preventDefault();
    const drop = e.target.closest('.row-tab-drop');
    if (drop && rowDragIdx >= 0) {
      drop.classList.remove('drag-over');
      builder.moveRow(rowDragIdx, parseInt(drop.dataset.rowDrop));
      rowDragIdx = -1;
      renderBuilder();
    }
  });

  // ================================================================
  //  D. 列タブ D&D（列の並び替え）+ チップを列タブにドロップで列移動
  // ================================================================
  colTabs.addEventListener('dragstart', (e) => {
    const tab = e.target.closest('.col-tab:not(.row-tab)');
    if (tab) {
      colDragIdx   = parseInt(tab.dataset.colIdx);
      colDragRowId = parseInt(tab.dataset.rowId);
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', 'col');
      tab.classList.add('dragging');
    }
  });
  colTabs.addEventListener('dragend', (e) => {
    const tab = e.target.closest('.col-tab');
    if (tab) tab.classList.remove('dragging');
    colDragIdx = -1; colDragRowId = null;
    colTabs.querySelectorAll('.col-tab-drop').forEach(z => z.classList.remove('drag-over'));
    colTabs.querySelectorAll('.col-tab').forEach(t => t.classList.remove('chip-drop-target'));
  });
  colTabs.addEventListener('dragover', (e) => {
    // 列タブのD&D（列並び替え）
    if (colDragIdx >= 0) {
      const drop = e.target.closest('.col-tab-drop');
      if (drop) { e.preventDefault(); drop.classList.add('drag-over'); }
      return;
    }
    // チップを別の列タブにドロップ
    if (chipDragGroupIdx >= 0) {
      const tab = e.target.closest('.col-tab:not(.row-tab)');
      if (!tab) return;
      const targetColId = parseInt(tab.dataset.colId);
      if (targetColId === chipDragColId) return;
      e.preventDefault();
      colTabs.querySelectorAll('.col-tab').forEach(t => t.classList.remove('chip-drop-target'));
      tab.classList.add('chip-drop-target');
    }
  });
  colTabs.addEventListener('dragleave', (e) => {
    const drop = e.target.closest('.col-tab-drop');
    if (drop) drop.classList.remove('drag-over');
    const tab = e.target.closest('.col-tab');
    if (tab && !e.relatedTarget?.closest('.col-tab[data-col-id="' + tab.dataset.colId + '"]')) {
      tab.classList.remove('chip-drop-target');
    }
  });
  colTabs.addEventListener('drop', (e) => {
    e.preventDefault();
    // 列並び替え
    if (colDragIdx >= 0) {
      const drop = e.target.closest('.col-tab-drop');
      if (drop) {
        drop.classList.remove('drag-over');
        const row = builder.rows.find(r => r.id === colDragRowId) ?? builder.activeRow();
        builder.moveCol(row.id, colDragIdx, row.id, parseInt(drop.dataset.colDrop));
        renderBuilder();
      }
      colDragIdx = -1; colDragRowId = null;
      return;
    }
    // チップを別の列に移動
    if (chipDragGroupIdx >= 0) {
      const tab = e.target.closest('.col-tab:not(.row-tab)');
      if (!tab) return;
      tab.classList.remove('chip-drop-target');
      const targetColId = parseInt(tab.dataset.colId);
      if (targetColId === chipDragColId) return;
      const targetCol = builder.findCol(targetColId);
      builder.moveGroup(chipDragColId, chipDragGroupIdx, targetColId, targetCol ? targetCol.vars.length : 0);
      builder.activeColId = targetColId;
      chipDragGroupIdx = -1; chipDragColId = null;
      renderBuilder();
    }
  });

  // ================================================================
  //  E. チップ D&D（;並び替え・列またぎ・,合体）
  // ================================================================
  colContent.addEventListener('dragstart', (e) => {
    const chip = e.target.closest('.col-var-chip');
    if (!chip) return;
    chipDragColId    = parseInt(chip.dataset.colId);
    chipDragRowId    = parseInt(chip.dataset.rowId);
    chipDragGroupIdx = parseInt(chip.dataset.groupIdx);
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', 'chip');
    chip.classList.add('dragging');
  });
  colContent.addEventListener('dragend', () => {
    document.querySelectorAll('.col-var-chip.dragging').forEach(el => el.classList.remove('dragging'));
    document.querySelectorAll('.col-var-chip.merge-target').forEach(el => el.classList.remove('merge-target'));
    document.querySelectorAll('.chip-drop-zone.drag-over').forEach(el => el.classList.remove('drag-over'));
    document.querySelectorAll('.col-tab.chip-drop-target').forEach(el => el.classList.remove('chip-drop-target'));
    chipDragColId = null; chipDragRowId = null; chipDragGroupIdx = -1;
  });
  colContent.addEventListener('dragover', (e) => {
    if (chipDragGroupIdx < 0) return;

    const dropZone = e.target.closest('.chip-drop-zone');
    const targetChip = e.target.closest('.col-var-chip');

    if (dropZone) {
      // 通常の;単位移動
      e.preventDefault();
      document.querySelectorAll('.col-var-chip.merge-target').forEach(el => el.classList.remove('merge-target'));
      document.querySelectorAll('.chip-drop-zone.drag-over').forEach(el => el.classList.remove('drag-over'));
      dropZone.classList.add('drag-over');
    } else if (targetChip) {
      // チップの上にドロップ → 合体対象
      const tColId    = parseInt(targetChip.dataset.colId);
      const tGroupIdx = parseInt(targetChip.dataset.groupIdx);
      // 自分自身は除外
      if (tColId === chipDragColId && tGroupIdx === chipDragGroupIdx) return;
      e.preventDefault();
      document.querySelectorAll('.chip-drop-zone.drag-over').forEach(el => el.classList.remove('drag-over'));
      document.querySelectorAll('.col-var-chip.merge-target').forEach(el => el.classList.remove('merge-target'));
      targetChip.classList.add('merge-target');
    }
  });
  colContent.addEventListener('dragleave', (e) => {
    const drop = e.target.closest('.chip-drop-zone');
    if (drop) drop.classList.remove('drag-over');
    const chip = e.target.closest('.col-var-chip');
    if (chip) chip.classList.remove('merge-target');
  });
  colContent.addEventListener('drop', (e) => {
    e.preventDefault();
    if (chipDragGroupIdx < 0) return;

    const dropZone   = e.target.closest('.chip-drop-zone');
    const targetChip = e.target.closest('.col-var-chip');

    if (dropZone) {
      // ;単位の並び替え（同列 / 別列）
      dropZone.classList.remove('drag-over');
      const toColId   = parseInt(dropZone.dataset.colId);
      const toDropIdx = parseInt(dropZone.dataset.dropIdx);
      builder.moveGroup(chipDragColId, chipDragGroupIdx, toColId, toDropIdx);
      chipDragGroupIdx = -1; chipDragColId = null;
      renderAll();
    } else if (targetChip) {
      // ,合体
      targetChip.classList.remove('merge-target');
      const toColId    = parseInt(targetChip.dataset.colId);
      const toGroupIdx = parseInt(targetChip.dataset.groupIdx);
      if (toColId === chipDragColId && toGroupIdx === chipDragGroupIdx) return;
      builder.mergeGroup(chipDragColId, chipDragGroupIdx, toColId, toGroupIdx);
      chipDragGroupIdx = -1; chipDragColId = null;
      renderAll();
    }
    document.querySelectorAll('.chip-drop-zone.drag-over').forEach(el => el.classList.remove('drag-over'));
    document.querySelectorAll('.col-var-chip.merge-target').forEach(el => el.classList.remove('merge-target'));
  });

  // チップクリック（削除・分割）
  colContent.addEventListener('click', (e) => {
    const action = e.target.dataset.action || e.target.closest('[data-action]')?.dataset.action;
    if (action === 'remove-chip') {
      const el = e.target.closest('[data-action="remove-chip"]') || e.target;
      builder.removeGroup(parseInt(el.dataset.colId), parseInt(el.dataset.groupIdx));
      renderAll();
    }
    if (action === 'chip-split') {
      e.stopPropagation();
      const el = e.target.closest('[data-action="chip-split"]') || e.target;
      showSplitMenu(el, parseInt(el.dataset.colId), parseInt(el.dataset.rowId), parseInt(el.dataset.groupIdx));
    }
  });

  // チップホバー（プレビュー）
  colContent.addEventListener('mouseover', (e) => {
    const chipVar = e.target.closest('.chip-var');
    if (chipVar) showChipTooltip(chipVar, chipVar.dataset.varName);
  });
  colContent.addEventListener('mouseout', (e) => {
    if (e.target.closest('.chip-var')) hideChipTooltip();
  });
}
