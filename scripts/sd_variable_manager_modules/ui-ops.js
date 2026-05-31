'use strict';
// ============================================================
//  ui-ops.js — カテゴリ/変数操作・モーダル・コンテキストメニュー
// ============================================================

// ---- カテゴリ操作 ----
function selectCat(id) {
  state.selectedCategoryId = id || null;
  state.searchQuery = '';
  document.getElementById('searchInput').value = '';
  renderAll();
}

function toggleNode(id) {
  const n = state.findCat(id);
  if (n && n.children && n.children.length) { n._open = !n._open; renderTree(); }
}

function setOpenAll(nodes, open) {
  for (const n of nodes) {
    if (n.children && n.children.length) { n._open = open; setOpenAll(n.children, open); }
  }
}

function addCat(parentId, name) {
  state.pushUndo();
  const cat = { id: state.genId(), name, children: [], variables: [] };
  if (parentId === null) {
    state.categories.push(cat);
  } else {
    const parent = state.findCat(parentId);
    if (parent) {
      if (!parent.children) parent.children = [];
      parent.children.push(cat);
      parent._open = true;
    }
  }
  state.save();
  renderAll();
  toast(`「${name}」作成`);
}

function renameCat(id, name) {
  state.pushUndo();
  const cat = state.findCat(id);
  if (cat) { cat.name = name; state.save(); renderAll(); }
}

function deleteCat(id) {
  const cat = state.findCat(id);
  if (!cat) return;
  const count = state.countVars(cat);
  const msg = count ? `「${cat.name}」と${count}件の変数を削除？` : `「${cat.name}」を削除？`;
  if (!confirm(msg)) return;
  state.pushUndo();
  state.detachNode(id);
  if (state.selectedCategoryId === id) state.selectedCategoryId = null;
  state.save();
  renderAll();
  toast(`「${cat.name}」削除`);
}

// ---- 変数操作 ----
function addVar(catId, name, positive, negative) {
  const cat = state.findCat(catId);
  if (!cat) return;
  const dup = state.findDup(name);
  if (dup && !confirm(`「${name}」は「${dup.categoryPath}」に存在。上書き？`)) return;
  state.pushUndo();
  if (dup) delVarSilent(dup.id, dup.categoryId);
  if (!cat.variables) cat.variables = [];
  cat.variables.push({ id: state.genId(), name, positive, negative, updated_at: nowUtcIso() });
  state.lastCategoryId = catId;
  state.save();
  renderAll();
  toast(`「${name}」追加`);
}

// Phase B: 変数編集時刻スタンプ（ISO8601 UTC、秒精度 + Z）.
function nowUtcIso() {
  return new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
}

function updVar(varId, oldCatId, newCatId, name, positive, negative) {
  const oldCat = state.findCat(oldCatId);
  if (!oldCat) return;
  const v = oldCat.variables.find(x => x.id === varId);
  if (!v) return;
  const dup = state.findDup(name, varId);
  if (dup && !confirm(`「${name}」は「${dup.categoryPath}」に存在。上書き？`)) return;
  state.pushUndo();
  if (dup) delVarSilent(dup.id, dup.categoryId);
  const ts = nowUtcIso();
  if (newCatId !== oldCatId) {
    const newCat = state.findCat(newCatId);
    if (!newCat) return;
    oldCat.variables = oldCat.variables.filter(x => x.id !== varId);
    if (!newCat.variables) newCat.variables = [];
    newCat.variables.push({ id: varId, name, positive, negative, updated_at: ts });
  } else {
    v.name = name; v.positive = positive; v.negative = negative; v.updated_at = ts;
  }
  state.save();
  renderAll();
  toast(`「${name}」更新`);
}

function delVar(varId, catId) {
  const cat = state.findCat(catId);
  if (!cat) return;
  const v = cat.variables.find(x => x.id === varId);
  if (!v || !confirm(`「${v.name}」を削除？`)) return;
  state.pushUndo();
  cat.variables = cat.variables.filter(x => x.id !== varId);
  state.save();
  renderAll();
  toast(`「${v.name}」削除`);
}

function delVarSilent(varId, catId) {
  const cat = state.findCat(catId);
  if (cat) cat.variables = cat.variables.filter(x => x.id !== varId);
}

// ---- ビルダー高さ復元（ドラッグハンドルでカスタム化された高さを復元） ----
function restoreBuilderHeight() {
  const h = localStorage.getItem('sd_vm_builder_height_custom');
  if (h) {
    document.getElementById('builderPanel').style.setProperty('--builder-height', h);
  }
}

// ---- モーダル ----
function showModal(html) {
  document.getElementById('modalContent').innerHTML = html;
  document.getElementById('modalOverlay').classList.add('active');
  setTimeout(() => {
    const first = document.querySelector('#modalContent input,#modalContent textarea,#modalContent select');
    if (first) first.focus();
  }, 100);
}

function hideModal() {
  document.getElementById('modalOverlay').classList.remove('active');
}

function showAddCategoryModal(parentId) {
  const parentName = parentId ? state.findCat(parentId)?.name : 'ルート';
  showModal(`<h3>カテゴリ追加</h3>
    <div class="form-group"><label>親</label><input value="${escAttr(parentName)}" disabled></div>
    <div class="form-group"><label>名前</label>
      <input id="mN" placeholder="例: よう実">
    </div>
    <div class="modal-actions">
      <button class="btn" id="mCancel">キャンセル</button>
      <button class="btn btn-primary" id="mSubmit">作成</button>
    </div>`);
  document.getElementById('mCancel').onclick = hideModal;
  document.getElementById('mSubmit').onclick = () => {
    const name = document.getElementById('mN').value.trim();
    if (!name) return;
    addCat(parentId, name);
    hideModal();
  };
  document.getElementById('mN').onkeydown = (e) => { if (e.key === 'Enter') document.getElementById('mSubmit').click(); };
}

function showRenameCatModal(id) {
  const cat = state.findCat(id);
  if (!cat) return;
  showModal(`<h3>名前変更</h3>
    <div class="form-group"><label>新しい名前</label>
      <input id="mN" value="${escAttr(cat.name)}">
    </div>
    <div class="modal-actions">
      <button class="btn" id="mCancel">キャンセル</button>
      <button class="btn btn-primary" id="mSubmit">変更</button>
    </div>`);
  document.getElementById('mCancel').onclick = hideModal;
  document.getElementById('mSubmit').onclick = () => {
    const name = document.getElementById('mN').value.trim();
    if (!name) return;
    renameCat(id, name);
    hideModal();
  };
  document.getElementById('mN').onkeydown = (e) => { if (e.key === 'Enter') document.getElementById('mSubmit').click(); };
}

function buildCatOpts(nodes = state.categories, depth = 0) {
  let html = depth === 0 ? '<option value="">-- 選択 --</option>' : '';
  for (const n of nodes) {
    html += `<option value="${n.id}">${'　'.repeat(depth)}${esc(n.name)}</option>`;
    html += buildCatOpts(n.children || [], depth + 1);
  }
  return html;
}

// 変数名の禁止文字フィルタ（Forge expander の許容文字種と一致させる）.
// 許容: 英字 / 数字 / ひらがな / カタカナ / 漢字 / _ / ( ) : 、
// 禁止: 半角スペース / 改行 / / / ; / , / = / | / $ / { } / [ ] / .
// 禁止文字は入力時に自動削除し、トランジェント警告を表示。
const _FORBIDDEN_VAR_CHARS = /[\/;{}\[\].,=|\s\$]/g;

function setupNameValidation(inputEl) {
  const warn = inputEl.parentElement.querySelector('.var-name-warning')
    || (() => {
      const d = document.createElement('div');
      d.className = 'var-name-warning';
      inputEl.closest('.form-group').appendChild(d);
      return d;
    })();
  let warnTimer = null;
  inputEl.addEventListener('input', () => {
    const before = inputEl.value;
    const after = before.replace(_FORBIDDEN_VAR_CHARS, '');
    if (after !== before) {
      // 自動削除した文字を表示
      const stripped = [...before].filter(c => _FORBIDDEN_VAR_CHARS.test(c)).join('');
      inputEl.value = after;
      warn.textContent = `⚠ 使えない文字を除去: ${stripped}（禁止: 半角スペース / ; , = | $ / { } [ ] . 改行）`;
      warn.style.display = '';
      inputEl.style.borderColor = 'var(--warning)';
      clearTimeout(warnTimer);
      warnTimer = setTimeout(() => {
        warn.style.display = 'none';
        inputEl.style.borderColor = '';
      }, 2500);
    }
  });
}

function showAddVariableModal() {
  const defCat = state.selectedCategoryId || state.lastCategoryId || '';
  showModal(`<h3>変数追加</h3>
    <div class="form-group"><label>カテゴリ</label><select id="mC">${buildCatOpts()}</select></div>
    <div class="form-group"><label>変数名</label>
      <div class="dollar-input"><span class="dollar-prefix">$</span><input id="mN" placeholder="ナンジャモ(ジム:雷)"></div>
      <div class="var-name-warning" style="display:none"></div>
      <div class="hint">$は自動付与。ナンジャモ(ジム:雷) と入力 → $ナンジャモ(ジム:雷)<br>
        使えない文字: 半角 <code>/ ; { } [ ] . , = | $ 空白 改行</code>（入力時に自動除去）<br>
        使える文字: 英字 / 数字 / かな / 漢字 / <code>_ ( ) : 、</code> </div>
    </div>
    <div class="form-group"><label>ポジティブ値</label>
      <textarea id="mP" rows="3" placeholder="<lora:cote:0.8>, suzune horikita"></textarea>
      <div class="hint">; で複数値</div>
    </div>
    <div class="form-group"><label>ネガティブ値（任意）</label>
      <textarea id="mNG" rows="2" placeholder="large breasts"></textarea>
    </div>
    <div class="modal-actions">
      <button class="btn" id="mCancel">キャンセル</button>
      <button class="btn btn-primary" id="mSubmit">追加</button>
    </div>`);
  if (defCat) document.getElementById('mC').value = defCat;
  setupNameValidation(document.getElementById('mN'));
  document.getElementById('mCancel').onclick = hideModal;
  document.getElementById('mSubmit').onclick = () => {
    const catId = parseInt(document.getElementById('mC').value);
    let name = document.getElementById('mN').value.trim();
    if (name && !name.startsWith('$')) name = '$' + name;
    const positive = document.getElementById('mP').value.trim();
    const negative = document.getElementById('mNG').value.trim();
    if (!catId || !name) { toast('カテゴリと変数名は必須'); return; }
    addVar(catId, name, positive, negative);
    hideModal();
  };
}

function showEditVarModal(varId, catId) {
  const cat = state.findCat(catId);
  if (!cat) return;
  const v = cat.variables.find(x => x.id === varId);
  if (!v) return;
  const nameWithout$ = v.name.startsWith('$') ? v.name.substring(1) : v.name;
  showModal(`<h3>変数編集</h3>
    <div class="form-group"><label>カテゴリ（変更で移動）</label><select id="mC">${buildCatOpts()}</select></div>
    <div class="form-group"><label>変数名</label>
      <div class="dollar-input"><span class="dollar-prefix">$</span><input id="mN" value="${escAttr(nameWithout$)}"></div>
      <div class="var-name-warning" style="display:none"></div>
    </div>
    <div class="form-group"><label>ポジティブ値</label>
      <textarea id="mP" rows="3">${esc(v.positive || '')}</textarea>
    </div>
    <div class="form-group"><label>ネガティブ値</label>
      <textarea id="mNG" rows="2">${esc(v.negative || '')}</textarea>
    </div>
    <div class="modal-actions">
      <button class="btn" id="mCancel">キャンセル</button>
      <button class="btn btn-primary" id="mSubmit">保存</button>
    </div>`);
  document.getElementById('mC').value = catId;
  setupNameValidation(document.getElementById('mN'));
  document.getElementById('mCancel').onclick = hideModal;
  document.getElementById('mSubmit').onclick = () => {
    let name = document.getElementById('mN').value.trim();
    if (name && !name.startsWith('$')) name = '$' + name;
    const newCatId = parseInt(document.getElementById('mC').value) || catId;
    const positive = document.getElementById('mP').value.trim();
    const negative = document.getElementById('mNG').value.trim();
    if (!name) { toast('変数名必須'); return; }
    updVar(varId, catId, newCatId, name, positive, negative);
    hideModal();
  };
}

// ---- コンテキストメニュー ----
function showContextMenu(e, catId) {
  e.preventDefault();
  e.stopPropagation();
  ctxTargetId = catId;
  const menu = document.getElementById('contextMenu');
  menu.classList.add('active');
  const menuW = 160, menuH = 140;
  let x = e.clientX, y = e.clientY;
  if (x + menuW > window.innerWidth) x = window.innerWidth - menuW - 4;
  if (y + menuH > window.innerHeight) y = window.innerHeight - menuH - 4;
  menu.style.left = x + 'px';
  menu.style.top  = y + 'px';
}

function hideContextMenu() {
  document.getElementById('contextMenu').classList.remove('active');
}
