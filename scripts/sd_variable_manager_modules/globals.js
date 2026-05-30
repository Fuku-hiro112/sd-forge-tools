'use strict';
// ============================================================
//  globals.js — グローバル状態変数
// ============================================================

const state   = new AppState();
const builder = new BuilderState();
const FORGE_URL_KEY = 'sd_vm_forge_url';

let ctxTargetId = null;

// カテゴリD&D
let catDragId = null;

// 列タブD&D
let colDragIdx   = -1;
let colDragRowId = null;

// チップD&D（グループ単位）
let chipDragColId    = null;
let chipDragRowId    = null;
let chipDragGroupIdx = -1;

// 変数カード → カテゴリD&D
let varDragId    = null;
let varDragCatId = null;

// 行タブD&D
let rowDragIdx = -1;

// ビルダーリサイズ
let resizeDragging = false;
let resizeStartY   = 0;
let resizeStartH   = 0;
