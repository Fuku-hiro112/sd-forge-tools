'use strict';
// ============================================================
//  themes.js — Atelier Terminal カラーテーマ定義と適用
// ============================================================

const THEMES = {
  // Graphite — 黒鉛と象牙 (default)
  graphite: {
    '--bg-primary':'#17171c','--bg-secondary':'#1e1e24','--bg-tertiary':'#26262e',
    '--bg-hover':'#2e2e36','--bg-input':'#1b1b21',
    '--text-primary':'#ede8dc','--text-secondary':'#a8a298','--text-muted':'#6a655d',
    '--accent':'#e8b04a','--accent-hover':'#f0c478','--accent-dim':'rgba(232,176,74,0.14)',
    '--positive':'#9ec98a','--positive-dim':'rgba(158,201,138,0.13)',
    '--negative':'#e87662','--negative-dim':'rgba(232,118,98,0.13)',
    '--warning':'#d8a45c',
    '--border':'rgba(237,232,220,0.09)','--border-light':'rgba(237,232,220,0.18)',
    '--shadow':'rgba(0,0,0,0.5)','--grid':'rgba(237,232,220,0.025)',
  },
  // Noir — 深夜の計器盤
  noir: {
    '--bg-primary':'#0a0a0d','--bg-secondary':'#111115','--bg-tertiary':'#17171c',
    '--bg-hover':'#1e1e24','--bg-input':'#0e0e12',
    '--text-primary':'#e6ebe6','--text-secondary':'#8a9090','--text-muted':'#525656',
    '--accent':'#5eead4','--accent-hover':'#7df0dc','--accent-dim':'rgba(94,234,212,0.13)',
    '--positive':'#86dfa3','--positive-dim':'rgba(134,223,163,0.13)',
    '--negative':'#f08080','--negative-dim':'rgba(240,128,128,0.13)',
    '--warning':'#e6c870',
    '--border':'rgba(230,235,230,0.07)','--border-light':'rgba(230,235,230,0.16)',
    '--shadow':'rgba(0,0,0,0.6)','--grid':'rgba(230,235,230,0.02)',
  },
  // Paper — クリーム紙にインク
  paper: {
    '--bg-primary':'#f4efe4','--bg-secondary':'#fbf7ee','--bg-tertiary':'#ebe5d6',
    '--bg-hover':'#e0d9c6','--bg-input':'#fffbf2',
    '--text-primary':'#1a1814','--text-secondary':'#5a5448','--text-muted':'#8a8270',
    '--accent':'#c83a2a','--accent-hover':'#dc5a48','--accent-dim':'rgba(200,58,42,0.10)',
    '--positive':'#3a8b54','--positive-dim':'rgba(58,139,84,0.10)',
    '--negative':'#b02838','--negative-dim':'rgba(176,40,56,0.10)',
    '--warning':'#b76e10',
    '--border':'rgba(26,24,20,0.10)','--border-light':'rgba(26,24,20,0.22)',
    '--shadow':'rgba(60,40,20,0.15)','--grid':'rgba(26,24,20,0.025)',
  },
  // Sakura — 桜色の朝
  sakura: {
    '--bg-primary':'#faf3f3','--bg-secondary':'#fffafa','--bg-tertiary':'#f0e5e6',
    '--bg-hover':'#e6d5d7','--bg-input':'#fffefe',
    '--text-primary':'#2a1f24','--text-secondary':'#6a5a60','--text-muted':'#988088',
    '--accent':'#c9457a','--accent-hover':'#d96690','--accent-dim':'rgba(201,69,122,0.10)',
    '--positive':'#3f8a6e','--positive-dim':'rgba(63,138,110,0.10)',
    '--negative':'#b8344f','--negative-dim':'rgba(184,52,79,0.10)',
    '--warning':'#b07020',
    '--border':'rgba(42,31,36,0.10)','--border-light':'rgba(42,31,36,0.22)',
    '--shadow':'rgba(120,40,80,0.15)','--grid':'rgba(42,31,36,0.025)',
  },
  // Pine — 深林と苔
  pine: {
    '--bg-primary':'#0f1a17','--bg-secondary':'#15231f','--bg-tertiary':'#1c2c27',
    '--bg-hover':'#243630','--bg-input':'#131e1b',
    '--text-primary':'#e6ebe2','--text-secondary':'#8a9c8e','--text-muted':'#56685c',
    '--accent':'#a8c89c','--accent-hover':'#bcd6b2','--accent-dim':'rgba(168,200,156,0.13)',
    '--positive':'#9ed4a3','--positive-dim':'rgba(158,212,163,0.13)',
    '--negative':'#e08a78','--negative-dim':'rgba(224,138,120,0.13)',
    '--warning':'#d8c070',
    '--border':'rgba(230,235,226,0.08)','--border-light':'rgba(230,235,226,0.18)',
    '--shadow':'rgba(0,0,0,0.55)','--grid':'rgba(230,235,226,0.02)',
  },
  // Atlas — 深海と真鍮
  atlas: {
    '--bg-primary':'#0d1828','--bg-secondary':'#142236','--bg-tertiary':'#1c2d44',
    '--bg-hover':'#243857','--bg-input':'#101c30',
    '--text-primary':'#e8edf4','--text-secondary':'#8a9cb4','--text-muted':'#5a6a82',
    '--accent':'#d4a857','--accent-hover':'#e4bf78','--accent-dim':'rgba(212,168,87,0.14)',
    '--positive':'#82c8a8','--positive-dim':'rgba(130,200,168,0.13)',
    '--negative':'#e88080','--negative-dim':'rgba(232,128,128,0.13)',
    '--warning':'#e0c070',
    '--border':'rgba(232,237,244,0.08)','--border-light':'rgba(232,237,244,0.18)',
    '--shadow':'rgba(0,0,0,0.55)','--grid':'rgba(232,237,244,0.02)',
  },
  // Terminal — 80s CRT 蛍光フォスファー
  terminal: {
    '--bg-primary':'#050a05','--bg-secondary':'#0a140a','--bg-tertiary':'#0f1f0f',
    '--bg-hover':'#143014','--bg-input':'#070e07',
    '--text-primary':'#b8ffb8','--text-secondary':'#6acc7a','--text-muted':'#3e7a48',
    '--accent':'#4afa6e','--accent-hover':'#7cffa0','--accent-dim':'rgba(74,250,110,0.14)',
    '--positive':'#7cffa0','--positive-dim':'rgba(124,255,160,0.13)',
    '--negative':'#ff5050','--negative-dim':'rgba(255,80,80,0.13)',
    '--warning':'#f0e040',
    '--border':'rgba(74,250,110,0.10)','--border-light':'rgba(74,250,110,0.22)',
    '--shadow':'rgba(0,30,0,0.6)','--grid':'rgba(74,250,110,0.03)',
  },
  // Cyber — マゼンタ × シアンの電脳
  cyber: {
    '--bg-primary':'#0a0612','--bg-secondary':'#140a24','--bg-tertiary':'#1c1230',
    '--bg-hover':'#261942','--bg-input':'#0e081a',
    '--text-primary':'#ecdfff','--text-secondary':'#a896c4','--text-muted':'#6a5a88',
    '--accent':'#ff3ec8','--accent-hover':'#ff70d6','--accent-dim':'rgba(255,62,200,0.14)',
    '--positive':'#38e8ff','--positive-dim':'rgba(56,232,255,0.13)',
    '--negative':'#ff5577','--negative-dim':'rgba(255,85,119,0.13)',
    '--warning':'#ffd848',
    '--border':'rgba(236,223,255,0.09)','--border-light':'rgba(236,223,255,0.20)',
    '--shadow':'rgba(80,0,140,0.5)','--grid':'rgba(236,223,255,0.025)',
  },
  // Mocha — チョコ & キャラメル
  mocha: {
    '--bg-primary':'#1c1410','--bg-secondary':'#261c16','--bg-tertiary':'#30241c',
    '--bg-hover':'#3a2d22','--bg-input':'#1f1612',
    '--text-primary':'#f0e4d4','--text-secondary':'#b8a890','--text-muted':'#80705c',
    '--accent':'#d99458','--accent-hover':'#e6ad78','--accent-dim':'rgba(217,148,88,0.14)',
    '--positive':'#a8c878','--positive-dim':'rgba(168,200,120,0.13)',
    '--negative':'#d87060','--negative-dim':'rgba(216,112,96,0.13)',
    '--warning':'#e6b860',
    '--border':'rgba(240,228,212,0.08)','--border-light':'rgba(240,228,212,0.18)',
    '--shadow':'rgba(40,20,10,0.55)','--grid':'rgba(240,228,212,0.025)',
  },
  // Arctic — 氷雪と北欧
  arctic: {
    '--bg-primary':'#eef4f8','--bg-secondary':'#f7fafc','--bg-tertiary':'#e2ecf2',
    '--bg-hover':'#d4e2ec','--bg-input':'#ffffff',
    '--text-primary':'#102030','--text-secondary':'#4a5a6e','--text-muted':'#8090a0',
    '--accent':'#2466a0','--accent-hover':'#3880bc','--accent-dim':'rgba(36,102,160,0.10)',
    '--positive':'#2a8870','--positive-dim':'rgba(42,136,112,0.10)',
    '--negative':'#b0364c','--negative-dim':'rgba(176,54,76,0.10)',
    '--warning':'#a06820',
    '--border':'rgba(16,32,48,0.10)','--border-light':'rgba(16,32,48,0.22)',
    '--shadow':'rgba(40,80,120,0.15)','--grid':'rgba(16,32,48,0.025)',
  },
};

const THEME_LABELS = {
  graphite:'🪨 Graphite', noir:'🌑 Noir',  paper:'📜 Paper',
  sakura:'🌸 Sakura',    pine:'🌿 Pine',  atlas:'🧭 Atlas',
  terminal:'>_ Terminal', cyber:'⚡ Cyber', mocha:'☕ Mocha', arctic:'❄ Arctic',
};

// 旧キー → 新キーのマイグレーション
const _THEME_MIGRATE = {
  nebula:'graphite', ocean:'noir', forest:'pine',
  ember:'paper',     mono:'sakura', light:'atlas',
};

function applyTheme(name) {
  const theme = THEMES[name] || THEMES.graphite;
  for (const [k, v] of Object.entries(theme)) {
    document.documentElement.style.setProperty(k, v);
  }
  localStorage.setItem('sd_vm_theme', name);
  document.querySelectorAll('.theme-opt').forEach(b =>
    b.classList.toggle('active', b.dataset.theme === name)
  );
}

function initTheme() {
  let saved = localStorage.getItem('sd_vm_theme') || 'graphite';
  if (_THEME_MIGRATE[saved]) {
    saved = _THEME_MIGRATE[saved];
    localStorage.setItem('sd_vm_theme', saved);
  }
  if (!(saved in THEMES)) saved = 'graphite';
  applyTheme(saved);
}
