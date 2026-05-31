'use strict';
// ============================================================
//  utils.js — 共通ユーティリティ
// ============================================================

function esc(s) {
  return s ? s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;') : '';
}

function escAttr(s) {
  return s ? esc(s).replace(/'/g,'&#39;') : '';
}

function toast(msg) {
  const el = document.createElement('div');
  el.className = 'toast';
  el.textContent = msg;
  document.getElementById('toastContainer').appendChild(el);
  setTimeout(() => el.remove(), 3000);
}

function copyToClipboard(text, label) {
  navigator.clipboard.writeText(text).then(
    () => toast(`${label}をコピー`),
    () => toast('コピーに失敗しました')
  );
}
