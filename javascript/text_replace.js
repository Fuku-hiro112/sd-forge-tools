/*
 * text_replace.js - メインプロンプト用 Ctrl+F フローティング検索置換ウィジェット
 *
 * VSCode 風の検索/置換パネルを純 JS で実装。プロンプト textarea にフォーカス中の
 * Ctrl+F でパネルを開き、検索・前後移動・1件置換・全置換を行う。マッチは
 * setSelectionRange でネイティブ選択ハイライトする。
 *
 * 検索/置換ロジックは scripts/vram_safe_batch_modules/text_tools.py の意味論をミラー。
 * Forge は javascript/*.js を起動時に自動 <script> 読込する。
 */
(function () {
    "use strict";

    // === 状態 ===
    var activeTextarea = null;   // Ctrl+F 押下時にフォーカスされていた textarea
    var matches = [];            // [[start, end], ...]
    var currentIndex = 0;
    var panel = null;            // ルート DOM
    var els = {};                // 子要素参照

    // プロンプト textarea 判定セレクタ (edit-attention.js と同じ流儀)
    var PROMPT_SELECTOR = "*:is([id*='_toprow'] [id*='_prompt'], .prompt) textarea";

    // === 検索/置換ロジック (text_tools.py ミラー) ===

    function escapeRegExp(s) {
        return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    }

    // RegExp を構築。失敗時は null。
    function buildPattern(query, useRegex, caseSensitive, global) {
        if (!query) return null;
        var flags = (global ? "g" : "") + (caseSensitive ? "" : "i");
        try {
            return new RegExp(useRegex ? query : escapeRegExp(query), flags);
        } catch (e) {
            return null;
        }
    }

    // 全マッチの [start, end] 配列。無効正規表現/空クエリ → []。
    function findMatches(text, query, useRegex, caseSensitive) {
        var re = buildPattern(query, useRegex, caseSensitive, true);
        if (!re || !text) return [];
        var out = [];
        var m;
        while ((m = re.exec(text)) !== null) {
            out.push([m.index, m.index + m[0].length]);
            if (m.index === re.lastIndex) re.lastIndex++; // 空マッチで無限ループ防止
            if (out.length > 100000) break;               // 安全上限
        }
        return out;
    }

    // 指定 index のマッチを 1 件置換。(newText, newMatchCount)
    function replaceOne(text, query, replacement, useRegex, caseSensitive, idx) {
        var ms = findMatches(text, query, useRegex, caseSensitive);
        if (ms.length === 0) return { text: text, count: 0 };
        var i = Math.max(0, Math.min(idx, ms.length - 1));
        var start = ms[i][0], end = ms[i][1];
        var matched = text.substring(start, end);
        var replaced;
        if (useRegex) {
            // グループ参照 ($1 等) を解釈するため単発正規表現で置換
            var single = buildPattern(query, true, caseSensitive, false);
            replaced = single ? matched.replace(single, replacement) : replacement;
        } else {
            replaced = replacement;
        }
        var newText = text.substring(0, start) + replaced + text.substring(end);
        var newMs = findMatches(newText, query, useRegex, caseSensitive);
        return { text: newText, count: newMs.length };
    }

    // 全マッチ一括置換。(newText, replacedCount)
    function replaceAll(text, query, replacement, useRegex, caseSensitive) {
        var ms = findMatches(text, query, useRegex, caseSensitive);
        if (ms.length === 0) return { text: text, count: 0 };
        var re = buildPattern(query, useRegex, caseSensitive, true);
        if (!re) return { text: text, count: 0 };
        return { text: text.replace(re, replacement), count: ms.length };
    }

    // === Gradio 同期 ===
    function syncTextarea(ta, newValue) {
        var setter = Object.getOwnPropertyDescriptor(
            window.HTMLTextAreaElement.prototype, "value").set;
        setter.call(ta, newValue);
        if (typeof updateInput === "function") {
            updateInput(ta);
        } else {
            ta.dispatchEvent(new Event("input", { bubbles: true }));
        }
    }

    // === ハイライト (バックドロップ・オーバーレイ方式) ===
    // setSelectionRange はフォーカスが textarea から離れると描画されないため、
    // textarea 背後に同じレイアウトの div を重ね <mark> で背景ハイライトする。
    // 検索ボックスにフォーカスがあってもマッチが見える。

    function escapeHtml(s) {
        return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    // textarea ごとにバックドロップ div を 1 つ用意 (なければ生成)
    function ensureBackdrop(ta) {
        if (ta._trBackdrop && ta._trBackdrop.isConnected) return ta._trBackdrop;
        var bd = document.createElement("div");
        bd.className = "tr-backdrop";
        var parent = ta.parentElement;
        if (getComputedStyle(parent).position === "static") {
            parent.style.position = "relative";
        }
        parent.insertBefore(bd, ta); // textarea の手前 (z-index で背後に回す)
        ta._trBackdrop = bd;
        ta._trOrigBg = ta.style.background;
        ta.style.background = "transparent"; // 背後の bd の <mark> を透かす
        ta.style.position = ta.style.position || "relative";
        ta.style.zIndex = "1";
        ta.addEventListener("scroll", function () {
            bd.scrollTop = ta.scrollTop;
            bd.scrollLeft = ta.scrollLeft;
        });
        return bd;
    }

    // textarea のボックス/文字レイアウトを backdrop に複製
    function syncBackdropBox(ta, bd) {
        var cs = getComputedStyle(ta);
        var props = ["fontFamily", "fontSize", "fontWeight", "fontStyle", "lineHeight",
            "letterSpacing", "wordSpacing", "textTransform", "textAlign", "textIndent",
            "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
            "borderTopWidth", "borderRightWidth", "borderBottomWidth", "borderLeftWidth",
            "boxSizing", "borderRadius"];
        props.forEach(function (p) { bd.style[p] = cs[p]; });
        bd.style.borderStyle = "solid";
        bd.style.borderColor = "transparent";
        bd.style.top = ta.offsetTop + "px";
        bd.style.left = ta.offsetLeft + "px";
        bd.style.width = ta.offsetWidth + "px";
        bd.style.height = ta.offsetHeight + "px";
    }

    // マッチ箇所を <mark> でハイライトした HTML を描画
    function renderHighlights() {
        if (!activeTextarea) return;
        var bd = ensureBackdrop(activeTextarea);
        syncBackdropBox(activeTextarea, bd);
        var text = activeTextarea.value;
        if (matches.length === 0) {
            bd.textContent = text; // 文字は transparent なので見えない (レイアウト維持のみ)
            bd.scrollTop = activeTextarea.scrollTop;
            bd.scrollLeft = activeTextarea.scrollLeft;
            return;
        }
        var html = "";
        var pos = 0;
        for (var i = 0; i < matches.length; i++) {
            var s = matches[i][0], e = matches[i][1];
            if (s < pos) continue; // 重なり保護
            html += escapeHtml(text.substring(pos, s));
            var cls = (i === currentIndex) ? ' class="tr-current"' : '';
            html += "<mark" + cls + ">" + escapeHtml(text.substring(s, e)) + "</mark>";
            pos = e;
        }
        html += escapeHtml(text.substring(pos));
        bd.innerHTML = html + "\n"; // 末尾改行が pre-wrap で潰れないように
        bd.scrollTop = activeTextarea.scrollTop;
        bd.scrollLeft = activeTextarea.scrollLeft;
    }

    // backdrop を撤去し textarea の背景を復元
    function teardownBackdrop() {
        if (activeTextarea && activeTextarea._trBackdrop) {
            var bd = activeTextarea._trBackdrop;
            if (bd && bd.parentElement) bd.parentElement.removeChild(bd);
            activeTextarea._trBackdrop = null;
            if (activeTextarea._trOrigBg !== undefined) {
                activeTextarea.style.background = activeTextarea._trOrigBg;
            }
        }
    }

    function highlightCurrent() {
        if (!activeTextarea) { updateCount(); return; }
        if (matches.length === 0) { renderHighlights(); updateCount(); return; }
        var i = Math.max(0, Math.min(currentIndex, matches.length - 1));
        currentIndex = i;
        var start = matches[i][0], end = matches[i][1];
        // ネイティブ選択も設定 (パネルを閉じた後に編集しやすいよう。描画は backdrop が担う)
        try { activeTextarea.setSelectionRange(start, end); } catch (e) { /* noop */ }
        scrollSelectionIntoView(activeTextarea, start);
        renderHighlights();
        updateCount();
    }

    function scrollSelectionIntoView(ta, charIndex) {
        // 行番号からおおよそのスクロール位置を推定
        var before = ta.value.substring(0, charIndex);
        var line = before.split("\n").length - 1;
        var lineHeight = parseFloat(getComputedStyle(ta).lineHeight) || 20;
        var target = line * lineHeight - ta.clientHeight / 2;
        ta.scrollTop = Math.max(0, target);
    }

    function updateCount() {
        if (!els.count) return;
        if (matches.length === 0) {
            els.count.textContent = els.search && els.search.value ? "0/0" : "";
        } else {
            els.count.textContent = (currentIndex + 1) + "/" + matches.length;
        }
    }

    // === 検索の実行 ===
    function runSearch(resetIndex) {
        if (!activeTextarea) { matches = []; updateCount(); return; }
        var q = els.search.value;
        var useRegex = els.regex.classList.contains("active");
        var caseSensitive = els.case.classList.contains("active");
        matches = findMatches(activeTextarea.value, q, useRegex, caseSensitive);
        if (resetIndex || currentIndex >= matches.length) currentIndex = 0;
        highlightCurrent();
    }

    function navigate(dir) {
        if (matches.length === 0) return;
        currentIndex = (currentIndex + dir + matches.length) % matches.length;
        highlightCurrent();
    }

    function doReplaceOne() {
        if (!activeTextarea || matches.length === 0) return;
        var useRegex = els.regex.classList.contains("active");
        var caseSensitive = els.case.classList.contains("active");
        var res = replaceOne(activeTextarea.value, els.search.value,
            els.replace.value, useRegex, caseSensitive, currentIndex);
        syncTextarea(activeTextarea, res.text);
        runSearch(false);
    }

    function doReplaceAll() {
        if (!activeTextarea || !els.search.value) return;
        var useRegex = els.regex.classList.contains("active");
        var caseSensitive = els.case.classList.contains("active");
        var res = replaceAll(activeTextarea.value, els.search.value,
            els.replace.value, useRegex, caseSensitive);
        syncTextarea(activeTextarea, res.text);
        runSearch(true);
    }

    // === パネル表示/非表示 ===
    function openPanel(ta) {
        if (!panel) buildPanel();
        activeTextarea = ta;
        panel.style.display = "block";
        // 選択中テキストがあれば検索欄に流し込む
        try {
            var sel = ta.value.substring(ta.selectionStart, ta.selectionEnd);
            if (sel && sel.length < 200) els.search.value = sel;
        } catch (e) { /* noop */ }
        els.search.focus();
        els.search.select();
        runSearch(true);
    }

    function closePanel() {
        if (!panel) return;
        panel.style.display = "none";
        teardownBackdrop();
        if (activeTextarea) activeTextarea.focus();
    }

    // === CSS 注入 ===
    function injectCSS() {
        if (document.getElementById("text-replace-style")) return;
        var css = ""
            + "#text-replace-panel{position:fixed;top:64px;right:24px;z-index:9999;"
            + "display:none;width:360px;background:rgba(28,32,42,0.97);color:#e6e9ef;"
            + "border:1px solid rgba(255,255,255,0.14);border-radius:8px;"
            + "box-shadow:0 8px 28px rgba(0,0,0,0.45);padding:10px 12px;"
            + "font-family:system-ui,sans-serif;font-size:13px;backdrop-filter:blur(2px);}"
            + "#text-replace-panel .tr-row{display:flex;align-items:center;gap:6px;margin-bottom:6px;}"
            + "#text-replace-panel .tr-row:last-child{margin-bottom:0;}"
            + "#text-replace-panel input[type=text]{flex:1;min-width:0;background:rgba(0,0,0,0.3);"
            + "color:#e6e9ef;border:1px solid rgba(255,255,255,0.16);border-radius:4px;"
            + "padding:5px 8px;font-size:13px;outline:none;}"
            + "#text-replace-panel input[type=text]:focus{border-color:#6ea8fe;}"
            + "#text-replace-panel button{background:rgba(255,255,255,0.08);color:#e6e9ef;"
            + "border:1px solid rgba(255,255,255,0.16);border-radius:4px;padding:4px 8px;"
            + "font-size:12px;cursor:pointer;white-space:nowrap;}"
            + "#text-replace-panel button:hover{background:rgba(255,255,255,0.18);}"
            + "#text-replace-panel button.tr-toggle.active{background:#3b6fb5;border-color:#6ea8fe;color:#fff;}"
            + "#text-replace-panel .tr-count{min-width:48px;text-align:center;color:#9aa4b2;font-variant-numeric:tabular-nums;}"
            + "#text-replace-panel .tr-icon{padding:4px 7px;font-weight:600;}"
            + "#text-replace-panel .tr-close{margin-left:auto;background:transparent;border:none;color:#9aa4b2;font-size:16px;line-height:1;padding:2px 4px;}"
            + "#text-replace-panel .tr-close:hover{color:#fff;background:transparent;}"
            + "#text-replace-panel .tr-title{font-size:11px;letter-spacing:0.08em;color:#9aa4b2;text-transform:uppercase;}"
            + ".tr-backdrop{position:absolute;margin:0;color:transparent;pointer-events:none;z-index:0;overflow:hidden;"
            + "white-space:pre-wrap;overflow-wrap:break-word;word-break:break-word;background:transparent;}"
            + ".tr-backdrop mark{background:rgba(250,204,21,0.45);color:transparent;border-radius:2px;}"
            + ".tr-backdrop mark.tr-current{background:rgba(251,146,60,0.9);}";
        var style = document.createElement("style");
        style.id = "text-replace-style";
        style.textContent = css;
        document.head.appendChild(style);
    }

    // === DOM 構築 ===
    function buildPanel() {
        injectCSS();
        panel = document.createElement("div");
        panel.id = "text-replace-panel";

        // 行1: タイトル + 閉じる
        var row0 = document.createElement("div");
        row0.className = "tr-row";
        var title = document.createElement("span");
        title.className = "tr-title";
        title.textContent = "🔎 Find / Replace";
        var close = document.createElement("button");
        close.className = "tr-close";
        close.textContent = "×";
        close.title = "閉じる (Esc)";
        close.addEventListener("click", closePanel);
        row0.appendChild(title);
        row0.appendChild(close);

        // 行2: 検索 input + 件数 + ◀▶
        var row1 = document.createElement("div");
        row1.className = "tr-row";
        els.search = document.createElement("input");
        els.search.type = "text";
        els.search.placeholder = "検索";
        els.count = document.createElement("span");
        els.count.className = "tr-count";
        var prev = document.createElement("button");
        prev.className = "tr-icon";
        prev.textContent = "◀";
        prev.title = "前へ";
        prev.addEventListener("click", function () { navigate(-1); });
        var next = document.createElement("button");
        next.className = "tr-icon";
        next.textContent = "▶";
        next.title = "次へ";
        next.addEventListener("click", function () { navigate(1); });
        row1.appendChild(els.search);
        row1.appendChild(els.count);
        row1.appendChild(prev);
        row1.appendChild(next);

        // 行3: 置換 input + 1件 + 全
        var row2 = document.createElement("div");
        row2.className = "tr-row";
        els.replace = document.createElement("input");
        els.replace.type = "text";
        els.replace.placeholder = "置換";
        var repOne = document.createElement("button");
        repOne.textContent = "1件";
        repOne.title = "現在のマッチを置換";
        repOne.addEventListener("click", doReplaceOne);
        var repAll = document.createElement("button");
        repAll.textContent = "全て";
        repAll.title = "全マッチを置換";
        repAll.addEventListener("click", doReplaceAll);
        row2.appendChild(els.replace);
        row2.appendChild(repOne);
        row2.appendChild(repAll);

        // 行4: オプショントグル
        var row3 = document.createElement("div");
        row3.className = "tr-row";
        els.case = document.createElement("button");
        els.case.className = "tr-toggle";
        els.case.textContent = "Aa";
        els.case.title = "大文字/小文字を区別";
        els.case.addEventListener("click", function () {
            els.case.classList.toggle("active");
            runSearch(true);
        });
        els.regex = document.createElement("button");
        els.regex.className = "tr-toggle";
        els.regex.textContent = ".*";
        els.regex.title = "正規表現";
        els.regex.addEventListener("click", function () {
            els.regex.classList.toggle("active");
            runSearch(true);
        });
        row3.appendChild(els.case);
        row3.appendChild(els.regex);

        panel.appendChild(row0);
        panel.appendChild(row1);
        panel.appendChild(row2);
        panel.appendChild(row3);
        document.body.appendChild(panel);

        // 検索リアルタイム
        els.search.addEventListener("input", function () { runSearch(true); });
        // Enter: 次へ / Shift+Enter: 前へ
        els.search.addEventListener("keydown", function (e) {
            if (e.key === "Enter") {
                e.preventDefault();
                navigate(e.shiftKey ? -1 : 1);
            } else if (e.key === "Escape") {
                e.preventDefault();
                closePanel();
            }
        });
        els.replace.addEventListener("keydown", function (e) {
            if (e.key === "Escape") { e.preventDefault(); closePanel(); }
        });
    }

    // === グローバル keydown (Ctrl+F フック) ===
    addEventListener("keydown", function (event) {
        // Esc: パネルが開いていれば閉じる
        if (event.key === "Escape" && panel && panel.style.display === "block") {
            event.preventDefault();
            closePanel();
            return;
        }
        if (event.key !== "f" && event.key !== "F") return;
        if (!(event.ctrlKey || event.metaKey)) return;

        var target = event.target;
        // パネル内の検索欄で Ctrl+F → そのまま検索欄にフォーカス維持
        if (panel && panel.contains(target)) {
            event.preventDefault();
            els.search.focus();
            els.search.select();
            return;
        }
        // プロンプト textarea にフォーカスがある時だけ横取り
        if (target && target.matches && target.matches(PROMPT_SELECTOR)) {
            event.preventDefault();
            openPanel(target);
        }
        // それ以外はブラウザ標準 Ctrl+F を阻害しない
    });

    // パネル表示中はウィンドウリサイズで backdrop の位置/サイズを再追従
    addEventListener("resize", function () {
        if (panel && panel.style.display === "block" && activeTextarea && matches.length >= 0) {
            renderHighlights();
        }
    });
})();
