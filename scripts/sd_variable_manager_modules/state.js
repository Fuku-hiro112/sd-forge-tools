'use strict';
// ============================================================
//  state.js — AppState データ管理
// ============================================================

class AppState {
  constructor() {
    this.categories = [];
    this.selectedCategoryId = null;
    this.searchQuery = '';
    this.nextId = 1;
    this.lastCategoryId = null;
    // Undo/Redo（AppStateの変更に対してのみ）
    this._undoStack = [];
    this._redoStack = [];
  }

  // ---- 永続化 ----
  load() {
    try {
      const raw = localStorage.getItem('sd_variable_manager');
      if (!raw) return;
      const data = JSON.parse(raw);
      this.categories = data.categories || [];
      this.nextId = data.nextId || 1;
      this.lastCategoryId = data.lastCategoryId || null;
      // 一度きりの変数名マイグレーション（v2: SD構文と区別するため境界文字を _ に置換）
      if (!data._migratedNameV2) {
        const changed = this._migrateVariableNamesV2();
        if (changed.length) {
          console.warn('[VarManager] 変数名を自動リネームしました:', changed);
          alert(
            '【変数名の自動修正】\n'
            + 'SDプロンプト構文 (kw:1.4) [a:b:0.5] と区別するため、\n'
            + '半角 / ; { } : ( ) [ ] . , = | 空白 を _ に置換しました。\n\n'
            + '変更箇所:\n' + changed.slice(0, 20).map(c => `  ${c.from} → ${c.to}`).join('\n')
            + (changed.length > 20 ? `\n... 他 ${changed.length - 20} 件` : '')
            + '\n\n既存の生成リスト・プロンプト中の旧変数名は手動で書き換えてください。'
          );
        }
        this._migratedNameV2 = true;
        this.save();
      }
    } catch (e) {
      console.error('Load error:', e);
    }
  }

  _migrateVariableNamesV2() {
    // $ の後に来てはいけない文字（Forge expander の _DEF_RE 許容文字種と同期）.
    // ( ) : 、 は許容するので置換対象から外す。
    const FORBIDDEN = /[\/;{}\[\].,=|\s\$]+/g;
    const changed = [];
    for (const cat of this.categories) {
      if (!cat.variables) continue;
      for (const v of cat.variables) {
        if (!v.name || !v.name.startsWith('$')) continue;
        const isNeg = v.name.startsWith('$!');
        const prefix = isNeg ? '$!' : '$';
        const body = v.name.substring(prefix.length);
        const newBody = body.replace(FORBIDDEN, '_').replace(/_+/g, '_').replace(/^_|_$/g, '');
        if (newBody && newBody !== body) {
          const newName = prefix + newBody;
          changed.push({ from: v.name, to: newName });
          v.name = newName;
        }
      }
    }
    return changed;
  }

  save() {
    try {
      localStorage.setItem('sd_variable_manager', JSON.stringify({
        categories: this.categories,
        nextId: this.nextId,
        lastCategoryId: this.lastCategoryId,
        _migratedNameV2: this._migratedNameV2 === true,
      }));
    } catch (e) {
      console.error('Save error:', e);
    }
    // Phase A: Forge への自動同期（debounce 500ms）。
    // queueSyncToForge は forge.js で定義。Forge オフラインなら失敗してバッジ表示。
    if (typeof queueSyncToForge === 'function' && !this._suppressSync) {
      queueSyncToForge();
    }
  }

  // ---- Undo/Redo ----
  pushUndo() {
    const snap = JSON.stringify({
      categories: this.categories,
      nextId: this.nextId,
      lastCategoryId: this.lastCategoryId,
    });
    this._undoStack.push(snap);
    if (this._undoStack.length > 10) this._undoStack.shift();
    this._redoStack = [];
  }

  undo() {
    if (!this._undoStack.length) { toast('これ以上元に戻せません'); return false; }
    const current = JSON.stringify({ categories: this.categories, nextId: this.nextId, lastCategoryId: this.lastCategoryId });
    this._redoStack.push(current);
    const snap = JSON.parse(this._undoStack.pop());
    this.categories = snap.categories;
    this.nextId = snap.nextId;
    this.lastCategoryId = snap.lastCategoryId;
    this.save();
    return true;
  }

  redo() {
    if (!this._redoStack.length) { toast('これ以上やり直せません'); return false; }
    const current = JSON.stringify({ categories: this.categories, nextId: this.nextId, lastCategoryId: this.lastCategoryId });
    this._undoStack.push(current);
    const snap = JSON.parse(this._redoStack.pop());
    this.categories = snap.categories;
    this.nextId = snap.nextId;
    this.lastCategoryId = snap.lastCategoryId;
    this.save();
    return true;
  }

  // ---- ID管理 ----
  genId() { return this.nextId++; }

  recalcNextId() {
    let maxId = 0;
    const scan = (nodes) => {
      for (const n of nodes) {
        if (n.id > maxId) maxId = n.id;
        for (const v of (n.variables || [])) { if (v.id > maxId) maxId = v.id; }
        scan(n.children || []);
      }
    };
    scan(this.categories);
    this.nextId = maxId + 1;
  }

  // ---- 検索 ----
  findCat(id, nodes = this.categories) {
    for (const n of nodes) {
      if (n.id === id) return n;
      const found = this.findCat(id, n.children || []);
      if (found) return found;
    }
    return null;
  }

  findParent(id, nodes = this.categories, parent = null) {
    for (const n of nodes) {
      if (n.id === id) return parent;
      const found = this.findParent(id, n.children || [], n);
      if (found !== null) return found;
    }
    return null;
  }

  catPath(id) {
    const result = [];
    const search = (nodes, trail) => {
      for (const n of nodes) {
        const current = [...trail, n];
        if (n.id === id) { result.push(...current); return true; }
        if (search(n.children || [], current)) return true;
      }
      return false;
    };
    search(this.categories, []);
    return result;
  }

  allVars(nodes = this.categories) {
    const result = [];
    const collect = (ns) => {
      for (const n of ns) {
        const path = this.catPath(n.id).map(x => x.name).join(' > ');
        for (const v of (n.variables || [])) {
          result.push({ ...v, categoryId: n.id, categoryPath: path });
        }
        collect(n.children || []);
      }
    };
    collect(nodes);
    return result;
  }

  varsUnder(id) {
    const cat = this.findCat(id);
    if (!cat) return [];
    return this.allVars([cat]);
  }

  countVars(node) {
    let count = (node.variables || []).length;
    for (const ch of (node.children || [])) count += this.countVars(ch);
    return count;
  }

  findDup(name, excludeId = null) {
    return this.allVars().find(v => v.name === name && v.id !== excludeId);
  }

  findVarByName(name) {
    return this.allVars().find(v => v.name === name);
  }

  // ---- ツリー操作 ----
  detachNode(id) {
    const parent = this.findParent(id);
    if (parent === null) {
      const idx = this.categories.findIndex(c => c.id === id);
      if (idx >= 0) return this.categories.splice(idx, 1)[0];
      return null;
    }
    if (parent) {
      const idx = parent.children.findIndex(c => c.id === id);
      if (idx >= 0) return parent.children.splice(idx, 1)[0];
    }
    return null;
  }

  isDescendantOf(ancestorId, targetId) {
    const ancestor = this.findCat(ancestorId);
    if (!ancestor) return false;
    const check = (nodes) => {
      for (const n of nodes) {
        if (n.id === targetId) return true;
        if (check(n.children || [])) return true;
      }
      return false;
    };
    return check(ancestor.children || []);
  }

  // ---- 変数のカテゴリ間移動 ----
  moveVarToCategory(varId, newCatId) {
    const all = this.allVars();
    const varInfo = all.find(v => v.id === varId);
    if (!varInfo) return false;
    if (varInfo.categoryId === newCatId) return false;
    const oldCat = this.findCat(varInfo.categoryId);
    const newCat = this.findCat(newCatId);
    if (!oldCat || !newCat) return false;
    const varData = oldCat.variables.find(v => v.id === varId);
    if (!varData) return false;
    oldCat.variables = oldCat.variables.filter(v => v.id !== varId);
    if (!newCat.variables) newCat.variables = [];
    newCat.variables.push(varData);
    this.save();
    return true;
  }

  // ---- インポート検証 ----
  static validateImportData(data) {
    if (!data || typeof data !== 'object') return false;
    if (!Array.isArray(data.categories)) return false;
    const validateNode = (node) => {
      if (typeof node !== 'object' || node === null) return false;
      if (typeof node.id !== 'number' || typeof node.name !== 'string') return false;
      if (node.children && !Array.isArray(node.children)) return false;
      if (node.variables && !Array.isArray(node.variables)) return false;
      for (const ch of (node.children || [])) { if (!validateNode(ch)) return false; }
      for (const v of (node.variables || [])) {
        if (typeof v !== 'object' || typeof v.id !== 'number' || typeof v.name !== 'string') return false;
      }
      return true;
    };
    return data.categories.every(validateNode);
  }
}
