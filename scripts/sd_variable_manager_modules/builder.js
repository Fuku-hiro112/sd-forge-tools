'use strict';
// ============================================================
//  builder.js — BuilderState（多行・カンマグループ対応）
//
//  データモデル:
//    rows: [{ id, label, columns: [{ id, vars: string[][], shuffle, label }] }]
//    vars の各要素 = ;区切りのスロット = カンマグループ
//    例: [['$A'], ['$B','$C'], ['$D']]  → $A;$B,$C;$D
// ============================================================

class BuilderState {
  constructor() {
    this.rows = [{ id:1, label:'', columns:[{ id:1, vars:[], shuffle:false, label:'' }] }];
    this.activeRowId = 1;
    this.activeColId = 1;
    this.nextRowId = 2;
    this.nextColId = 2;
    this.collapsed = false;
    this.userEdited = false;
    this.outputText = '';
    this._presets = [];
  }

  // ---- Row / Col ヘルパ ----
  activeRow() {
    return this.rows.find(r => r.id === this.activeRowId) ?? this.rows[0];
  }

  activeCol() {
    const row = this.activeRow();
    return row?.columns.find(c => c.id === this.activeColId) ?? row?.columns[0];
  }

  findCol(colId) {
    for (const row of this.rows) {
      const c = row.columns.find(c => c.id === colId);
      if (c) return c;
    }
    return null;
  }

  findRowByColId(colId) {
    return this.rows.find(r => r.columns.some(c => c.id === colId));
  }

  // ---- Row 操作 ----
  addRow() {
    const row = { id: this.nextRowId++, label:'', columns:[{ id: this.nextColId++, vars:[], shuffle:false, label:'' }] };
    this.rows.push(row);
    this.activeRowId = row.id;
    this.activeColId = row.columns[0].id;
    return row;
  }

  removeRow(rowId) {
    this.rows = this.rows.filter(r => r.id !== rowId);
    if (!this.rows.length) this.addRow();
    if (this.activeRowId === rowId) {
      this.activeRowId = this.rows[0].id;
      this.activeColId = this.rows[0].columns[0]?.id ?? 1;
    }
  }

  moveRow(fromIdx, toIdx) {
    if (fromIdx === toIdx || fromIdx < 0 || toIdx < 0) return;
    const item = this.rows.splice(fromIdx, 1)[0];
    this.rows.splice(toIdx > fromIdx ? toIdx - 1 : toIdx, 0, item);
  }

  // ---- Col 操作 ----
  addCol(rowId) {
    const row = this.rows.find(r => r.id === rowId) ?? this.activeRow();
    const col = { id: this.nextColId++, vars:[], shuffle:false, label:'' };
    row.columns.push(col);
    this.activeColId = col.id;
    this.userEdited = false;
    return col;
  }

  removeCol(colId) {
    const row = this.findRowByColId(colId);
    if (!row) return;
    row.columns = row.columns.filter(c => c.id !== colId);
    if (!row.columns.length) row.columns.push({ id: this.nextColId++, vars:[], shuffle:false, label:'' });
    if (this.activeColId === colId) this.activeColId = row.columns[0].id;
    this.userEdited = false;
  }

  moveCol(fromRowId, fromIdx, toRowId, toIdx) {
    const fromRow = this.rows.find(r => r.id === fromRowId);
    const toRow   = this.rows.find(r => r.id === toRowId);
    if (!fromRow || !toRow) return;
    const col = fromRow.columns.splice(fromIdx, 1)[0];
    if (fromRowId === toRowId && fromIdx < toIdx) toIdx--;
    toRow.columns.splice(toIdx, 0, col);
    this.userEdited = false;
  }

  // ---- Var(グループ)操作 ----
  // vars: string[][] — 各要素が;スロット、内部が,グループ
  addVar(name) {
    const col = this.activeCol();
    if (!col) return;
    if (col.vars.some(g => g.includes(name))) return;
    col.vars.push([name]);
    this.userEdited = false;
  }

  removeGroup(colId, groupIdx) {
    const col = this.findCol(colId);
    if (col) { col.vars.splice(groupIdx, 1); this.userEdited = false; }
  }

  /** groupIdx の;スロットから elemIdx の変数を独立した;スロットとして分割 */
  splitVar(colId, groupIdx, elemIdx) {
    const col = this.findCol(colId);
    if (!col) return;
    const group = col.vars[groupIdx];
    if (!group || group.length <= 1) return;
    const extracted = group.splice(elemIdx, 1)[0];
    col.vars.splice(groupIdx + 1, 0, [extracted]);
    this.userEdited = false;
  }

  /** fromGroupIdx を toGroupIdx の先頭に合体（,グループ化）*/
  mergeGroup(fromColId, fromGroupIdx, toColId, toGroupIdx) {
    const fromCol = this.findCol(fromColId);
    const toCol   = this.findCol(toColId);
    if (!fromCol || !toCol) return;
    const dragged = fromCol.vars.splice(fromGroupIdx, 1)[0];
    // 同列でインデックスがずれる補正
    let adj = toGroupIdx;
    if (fromColId === toColId && fromGroupIdx < toGroupIdx) adj--;
    if (adj < 0 || adj >= toCol.vars.length) { toCol.vars.push(dragged); return; }
    toCol.vars[adj] = [...dragged, ...toCol.vars[adj]];
    this.userEdited = false;
  }

  /** グループを別の位置へ移動（;単位の並び替え・列をまたぐ移動） */
  moveGroup(fromColId, fromGroupIdx, toColId, toDropIdx) {
    const fromCol = this.findCol(fromColId);
    const toCol   = this.findCol(toColId);
    if (!fromCol || !toCol) return;
    const group = fromCol.vars.splice(fromGroupIdx, 1)[0];
    let insertIdx = toDropIdx;
    if (fromColId === toColId && fromGroupIdx < toDropIdx) insertIdx--;
    toCol.vars.splice(Math.max(0, insertIdx), 0, group);
    this.userEdited = false;
  }

  // ---- Build ----
  _buildColPart(col) {
    const nonEmpty = col.vars.filter(g => g.length > 0);
    return nonEmpty.map(g => g.join(',')).join(';');
  }

  buildRowLine(row) {
    const parts = [];
    const shuffleIdx = [];
    for (const col of row.columns) {
      const part = this._buildColPart(col);
      if (!part) continue;
      if (col.shuffle) shuffleIdx.push(parts.length);
      parts.push(part);
    }
    if (!parts.length) return '';
    if (shuffleIdx.length >= 2) {
      const result = [];
      let inShuffle = false;
      for (let i = 0; i < parts.length; i++) {
        const isShuffle = shuffleIdx.includes(i);
        if (isShuffle && !inShuffle)       { inShuffle = true;  result.push('{ ' + parts[i]); }
        else if (isShuffle)                { result.push(parts[i]); }
        else if (!isShuffle && inShuffle)  { result[result.length-1] += ' }'; inShuffle = false; result.push(parts[i]); }
        else                               { result.push(parts[i]); }
      }
      if (inShuffle) result[result.length-1] += ' }';
      return result.join(' // ');
    }
    return parts.join(' // ');
  }

  buildImplLine() {
    return this.rows.map(r => this.buildRowLine(r)).filter(l => l).join('\n');
  }

  buildDefs(appState) {
    const used = new Set();
    for (const row of this.rows)
      for (const col of row.columns)
        for (const group of col.vars)
          for (const name of group) used.add(name);
    const lines = [];
    for (const name of used) {
      const v = appState.findVarByName(name);
      if (!v) continue;
      lines.push(v.negative ? `${name}=${v.positive} !! ${v.negative}` : `${name}=${v.positive||''}`);
    }
    return lines.join('\n');
  }

  buildFromColumns(appState) {
    const defs = this.buildDefs(appState);
    const impl = this.buildImplLine();
    if (!defs && !impl) return '';
    if (!defs) return impl;
    if (!impl) return defs;
    return defs + '\n---\n' + impl;
  }

  buildFull(appState) {
    return this.userEdited ? this.outputText : this.buildFromColumns(appState);
  }

  clear() {
    this.rows = [{ id:1, label:'', columns:[{ id:1, vars:[], shuffle:false, label:'' }] }];
    this.activeRowId = 1;
    this.activeColId = 1;
    this.nextRowId = 2;
    this.nextColId = 2;
    this.userEdited = false;
    this.outputText = '';
  }

  // ---- プリセット ----
  loadPresets() {
    try {
      const raw = localStorage.getItem('sd_vm_presets');
      if (raw) this._presets = JSON.parse(raw);
    } catch {}
  }

  savePreset(name) {
    const preset = { name, rows: JSON.parse(JSON.stringify(this.rows)) };
    const idx = this._presets.findIndex(p => p.name === name);
    if (idx >= 0) this._presets[idx] = preset; else this._presets.push(preset);
    localStorage.setItem('sd_vm_presets', JSON.stringify(this._presets));
  }

  deletePreset(name) {
    this._presets = this._presets.filter(p => p.name !== name);
    localStorage.setItem('sd_vm_presets', JSON.stringify(this._presets));
  }

  applyPreset(name) {
    const preset = this._presets.find(p => p.name === name);
    if (!preset) return;
    this.rows = JSON.parse(JSON.stringify(preset.rows));
    // nextId 再計算
    let maxRow = 0, maxCol = 0;
    for (const r of this.rows) {
      if (r.id > maxRow) maxRow = r.id;
      for (const c of r.columns) { if (c.id > maxCol) maxCol = c.id; }
    }
    this.nextRowId = maxRow + 1;
    this.nextColId = maxCol + 1;
    this.activeRowId = this.rows[0]?.id ?? 1;
    this.activeColId = this.rows[0]?.columns[0]?.id ?? 1;
    this.userEdited = false;
  }
}

// ============================================================
//  parseImplLine — テキスト → 複数行・グループ構造に逆変換
// ============================================================
function parseImplLine(text) {
  let implPart = text.trim();
  if (implPart.includes('---')) {
    implPart = implPart.slice(implPart.lastIndexOf('---') + 3).trim();
  }
  if (!implPart) return false;

  const lines = implPart.split('\n').map(l => l.trim()).filter(l => l);
  if (!lines.length) return false;

  const oldRows = builder.rows;
  let nextColLocal = builder.nextColId;
  let nextRowLocal = builder.nextRowId;

  const newRows = lines.map((line, i) => {
    const oldRow = oldRows[i];
    const rawParts = line.split('//').map(s => s.trim());
    const cols = [];
    let inShuffle = false;

    for (let part of rawParts) {
      if (part.startsWith('{')) { inShuffle = true; part = part.slice(1).trim(); }
      let endsGroup = false;
      if (part.endsWith('}')) { endsGroup = true; part = part.slice(0,-1).trim(); }
      const isShuffle = inShuffle;
      if (endsGroup) inShuffle = false;

      // ;区切りでスロット、,区切りでグループ
      const groups = part.split(';')
        .map(g => g.split(',').map(v => v.trim()).filter(v => v))
        .filter(g => g.length > 0);

      if (groups.length > 0) {
        const existingCol = oldRow?.columns[cols.length];
        cols.push({
          id: existingCol?.id ?? nextColLocal++,
          vars: groups,
          shuffle: isShuffle,
          label: existingCol?.label ?? '',
        });
      }
    }

    return {
      id: oldRow?.id ?? nextRowLocal++,
      label: oldRow?.label ?? '',
      columns: cols.length ? cols : [{ id: nextColLocal++, vars:[], shuffle:false, label:'' }],
    };
  });

  if (!newRows.length) return false;

  builder.rows = newRows;
  builder.nextColId = nextColLocal;
  builder.nextRowId = nextRowLocal;
  builder.activeRowId = newRows[0].id;
  builder.activeColId = newRows[0].columns[0]?.id ?? 1;
  builder.userEdited = false;
  return true;
}
