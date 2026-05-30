"""
job_builder_b.py - ジョブ構築モジュール

【モード】行単位グループ方式

【書き方】
  1行が1つの生成グループ。列は // で区切る。
  ; 区切りで複数値を書くと、その部分だけ直積になる。
  カンマはプロンプトの一部として扱われる（区切り文字ではない）。

  例:
    生徒A;生徒B;生徒C // 制服;寝間着 // 状態1;状態2
    教師A;教師B // スーツ;寝間着 // 状態1;状態2

  → 1行目: 3キャラ × 2服装 × 2状態 = 12枚
  → 2行目: 2キャラ × 2服装 × 2状態 = 8枚
  → 合計: 20枚（不要な組み合わせなし）

  カンマを含む値もそのまま書ける:
    school, under table, // pov, expression,
  → 「school, under table,」全体が1つの値として扱われる

【枚数指定】
  項目の末尾に |数字 をつけると、その項目を含む組み合わせの枚数が増える。
  複数の項目に |数字 がある場合は掛け算される。
  |数字 がない項目は1枚扱い。

  例:
    生徒A;生徒B|2 // 制服 // 状態1;状態4|3

  → 生徒A × 制服 × 状態1 = 1×1×1 = 1枚
  → 生徒A × 制服 × 状態4 = 1×1×3 = 3枚
  → 生徒B × 制服 × 状態1 = 2×1×1 = 2枚
  → 生徒B × 制服 × 状態4 = 2×1×3 = 6枚
  → 合計: 12枚

【変数定義】
  --- より上に $変数名 = 値 の形式で変数を定義できる。
  値の区切りは ; （セミコロン）を使用する。
  複数行にまたがって書くことができる。
  次の $ か --- が来るまでが同じ変数の値として扱われる。
  = の後、; の後の改行は任意（あってもなくても動作する）。

  変数内の個別の値にも |数字 をつけられる。

  例（1行で書く場合）:
    $状態 = 状態1;状態2;状態3;状態4|3

  例（複数行で書く場合）:
    $chara =
    堀北 鈴音: 1girl suzune horikita;
    井の頭 心: 1girl kokoro inogashira;
    南方こずえ: 1girl kozue minamikata

  ---
  $生徒 // 制服;寝間着 // $状態
  教師A;教師B|2 // スーツ // $状態

  → 生徒B(2) × 制服(1) × 状態4(3) = 6枚
  → 教師B(2) × スーツ(1) × 状態4(3) = 6枚
  → |数字がない組み合わせは各1枚

【コメント】
  ## から行末までは無視される（## 単体はプロンプトの一部として使用可能）。

  例:
    $chara = 堀北 鈴音: 1girl suzune horikita ## よう実のヒロイン
    ## これは完全に無視される行
    $場所 = school, under table,  ## 学校の机の下

【ネガティブプロンプト】
  変数の値に !! を含めると、!! の前がポジティブ、後がネガティブとして扱われる。
  !! がない値はネガティブなしとして扱われる。

  ポジティブプロンプトでは {N} で列Nのポジティブ値を参照する。
  ネガティブプロンプトでは {!N} で列Nのネガティブ値を参照する。

  $!変数名 の形式で、ネガティブ専用の変数も定義できる。
  この変数を列として使用すると、{N} は空、{!N} に値が入る。

  例:
    $堀北 = suzune horikita, (flat chest:1.5) !! large breasts
    $制服 = school uniform !! bikini
    $!水着補正 = long sleeves, pants
    ---
    $堀北 // $制服 // $!水着補正

    ポジティブ: masterpiece, {2}, {1}
    ネガティブ: {!2}, {!1}, {!3}, bad ears

    → 堀北 × 制服 の場合:
      ポジティブ: masterpiece, school uniform, suzune horikita, (flat chest:1.5)
      ネガティブ: bikini, large breasts, long sleeves, pants, bad ears

【シャッフル】
  { } で囲んだ列はローテーション方式で並び替えられる。
  直積の全パターンを網羅しつつ、同じ値が連続しない。

  例:
    $style // { $キャラ // $lora }
  → $style は通常直積、{} 内はローテーション

【プロンプトでの参照】
  ポジティブ: 列を左から順に {1}, {2}, {3} で参照する。
  ネガティブ: 列を左から順に {!1}, {!2}, {!3} で参照する。

  例:
    ポジティブ: masterpiece, best quality, {2}, {1}, 1girl, solo, {3}
    ネガティブ: {!2}, {!1}, {!3}, disappearing arms, bad ears
"""

import itertools
import re

VAR_PATTERN = re.compile(r"\$!?[^\s,;|/={}:()\[\]!]+")
# 変数名の終端を判定する文字（次の文字がこれらなら変数名終了）
# SD 構文 (kw:1.3) [a:b:0.5] と共存させるため : ( ) [ ] ! も境界に含める
_VAR_NAME_BOUNDARY = r'(?![^\s,;|/={}:()\[\]!])'

def find_variables(text):
    return set(VAR_PATTERN.findall(text))

def preprocess_text(text):
    """入力テキストの前処理（全処理の最上流で1回だけ呼ぶ）
    
    1. 各行の ## 以降を除去する（# 単体はプロンプトの一部として使用可能）
    2. 結果として空になった行を除去する
    
    これにより下流の関数（parse_variables, expand_variables 等）は
    コメントや空行を意識する必要がない。
    """
    if not text:
        return ""
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.split("##")[0]
        if stripped.strip():
            cleaned.append(stripped)
    return "\n".join(cleaned)


def parse_variables(var_section_text):
    """変数定義を解析する（複数行対応）
    
    $変数名 = 値1;値2;値3 の形式（セミコロン区切り）
    次の $ か --- が来るまでが同じ変数の値として扱われる。
    = の後、; の後の改行は任意。
    各値に |数字 がついている場合はそのまま保持する。
    
    $!変数名 の場合、値は自動的にネガティブ専用になる。
    （各値の先頭に !! が付与され、ポジティブ側は空になる）
    """
    variables = {}
    if not var_section_text:
        return variables

    current_name = None
    current_value_lines = []

    def _finalize_variable(name, value_lines):
        """変数の値を確定し、辞書に登録する"""
        raw = " ".join(value_lines)
        values = [v.strip() for v in raw.split(";") if v.strip()]

        # $!変数名 の場合、各値をネガティブ専用に変換
        if name.startswith("$!"):
            values = [_to_negative_only(v) for v in values]

        variables[name] = ";".join(values)

    def _to_negative_only(value):
        """値をネガティブ専用に変換する（!! が未含有の場合のみ）"""
        if "!!" in value:
            return value  # 既に !! がある場合はそのまま
        return "!! " + value

    for line in var_section_text.split("\n"):
        line = line.strip()
        if not line:
            continue

        if line.startswith("$") and "=" in line:
            # 前の変数を確定
            if current_name is not None:
                _finalize_variable(current_name, current_value_lines)

            # 新しい変数開始
            parts = line.split("=", 1)
            current_name = parts[0].strip()
            rest = parts[1].strip()
            current_value_lines = [rest] if rest else []

        elif current_name is not None:
            # 継続行（同じ変数の続き）
            current_value_lines.append(line)

    # 最後の変数を確定
    if current_name is not None:
        _finalize_variable(current_name, current_value_lines)

    return variables

def expand_once(text, variables, sorted_names):
    new_text = text

    for var_name in sorted_names:
        var_values = variables[var_name]

        # $変数名|数字
        pattern_with_count = re.escape(var_name) + r'\|(\d+)(?![\w])'
        match = re.search(pattern_with_count, new_text)
        while match:
            count = int(match.group(1))
            count = max(1, min(count, 50))
            expanded = _apply_count_to_values(var_values, count)
            new_text = new_text[:match.start()] + expanded + new_text[match.end():]
            match = re.search(pattern_with_count, new_text)

        # 通常展開
        pattern = re.escape(var_name) + r'(?![\w])'
        new_text = re.sub(pattern, var_values, new_text)

    return new_text

def expand_variables(text, variables):
    """テキスト内の変数を展開する（後方互換／単純テキスト用）。

    - 長い変数名から順に置換することで部分一致を防ぐ。
    - $変数名|数字 の場合、展開後の全値に|数字を付与（既存は掛け算）。
    - 変数の中の変数も展開する（最大100回、循環参照検知あり）。

    注意: 複数値変数（;区切り）を値の中に埋め込んだ場合、外側の;と衝突する。
    生成リストの値展開には expand_value() を使うこと。
    """
    MAX_DEPTH = 100
    sorted_names = sorted(variables.keys(), key=len, reverse=True)

    for _ in range(MAX_DEPTH):

        # $が無ければ終了
        if "$" not in text:
            break

        # 現在の$変数を取得
        before_vars = find_variables(text)

        new_text = expand_once(text, variables, sorted_names)

        # 変化なしなら終了
        if new_text == text:
            break

        # 変数が減ってなければ危険（循環）
        after_vars = find_variables(new_text)
        if after_vars == before_vars:
            print(f"⚠ 循環または未定義変数の可能性: {after_vars}")
            break

        text = new_text

    return text


_STRUCTURAL_CHARS = ("//", "{", "}")


def _has_structural(text):
    """テキストに列区切り // や シャッフル記号 {, } が含まれるか"""
    return any(c in text for c in _STRUCTURAL_CHARS)


def expand_structural_variables(text, variables, max_depth=100):
    """値に //, {, } を含む「構造的変数」を line レベルで展開する。

    通常の値単位展開（expand_value）では //, { , } をまたぐ展開ができないため、
    これらを含む変数はパース前に先行展開する必要がある。

    値に構造的記号を含まない変数は触らず、後段の値単位展開に任せる。
    """
    if not variables or "$" not in text:
        return text

    structural = {n: v for n, v in variables.items() if _has_structural(v)}
    if not structural:
        return text

    sorted_names = sorted(structural.keys(), key=len, reverse=True)

    for _ in range(max_depth):
        if "$" not in text:
            break
        new_text = text
        for name in sorted_names:
            esc = re.escape(name)
            # $name|数字
            new_text = re.sub(
                esc + r'\|(\d+)' + _VAR_NAME_BOUNDARY,
                lambda m, n=name: _apply_count_to_values(structural[n], int(m.group(1))),
                new_text,
            )
            # $name 単独
            new_text = re.sub(esc + _VAR_NAME_BOUNDARY, structural[name], new_text)
        if new_text == text:
            break
        text = new_text

    return text


def _expand_value_once(value, variables, sorted_names):
    """値内で最も早い位置に出現する変数を1つ展開し、値のリストを返す。

    - 複数値変数（;区切り）の場合、値リストが増殖する。
    - 単一値変数の場合、リスト長は1のまま中身が置換される。
    - どの変数もマッチしなければ [value] を返す（未定義の$はそのまま残す）。

    変数名のマッチでは、後続文字が変数名構成文字 [^\\s,;|] でないことを
    強制する（例: $恰好 が $恰好:制服 の前半に誤マッチするのを防ぐ）。
    """
    best = None  # (start, end, name, count_or_None)

    for name in sorted_names:
        esc = re.escape(name)
        # $name|数字 形式
        m = re.search(esc + r'\|(\d+)' + _VAR_NAME_BOUNDARY, value)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), m.end(), name, int(m.group(1)))
            continue
        # $name 単独
        m = re.search(esc + _VAR_NAME_BOUNDARY, value)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), m.end(), name, None)

    if best is None:
        return [value]

    start, end, name, count = best
    vstr = variables[name]
    if count is not None:
        vstr = _apply_count_to_values(vstr, count)

    sub_values = [v.strip() for v in vstr.split(";") if v.strip()]
    prefix = value[:start]
    suffix = value[end:]

    if not sub_values:
        return [(prefix + suffix).strip()]

    return [prefix + sv + suffix for sv in sub_values]


def expand_value(value, variables, max_depth=100):
    """単一の値文字列を再帰的に変数展開する。

    複数値変数（;区切り）が値の中に出現した場合、値リストを増殖させる。
    例: value="$Rよう実キャラ,$恰好:制服"
        $Rよう実キャラ = 生徒A;生徒B;生徒C
        $恰好:制服   = school uniform
        → ["生徒A,school uniform", "生徒B,school uniform", "生徒C,school uniform"]

    Returns: 展開後の値のリスト（最低1要素）
    """
    if not variables or "$" not in value:
        return [value]

    sorted_names = sorted(variables.keys(), key=len, reverse=True)
    results = [value]

    for _ in range(max_depth):
        if all("$" not in v for v in results):
            break

        next_results = []
        any_changed = False
        for v in results:
            if "$" not in v:
                next_results.append(v)
                continue
            expanded = _expand_value_once(v, variables, sorted_names)
            if len(expanded) == 1 and expanded[0] == v:
                # 未定義変数 — そのまま残す（無限ループ防止）
                next_results.append(v)
            else:
                next_results.extend(expanded)
                any_changed = True

        results = next_results
        if not any_changed:
            break

    return results


def parse_value_with_count(value_str):
    """値文字列から (値, 枚数) を取得する
    
    例: "生徒B|2" → ("生徒B", 2)
    例: "生徒A"   → ("生徒A", 1)
    """
    value_str = value_str.strip()
    if "|" in value_str:
        last_pipe = value_str.rfind("|")
        after_pipe = value_str[last_pipe + 1:].strip()
        try:
            count = int(after_pipe)
            count = max(1, min(count, 50))
            value = value_str[:last_pipe].strip()
            return value, count
        except ValueError:
            pass
    return value_str, 1


def _apply_count_to_values(values_str, count):
    """セミコロン区切りの値文字列の各値に|数字を付与する。
    既に|数字がある値は掛け算する。
    
    例: _apply_count_to_values("loraA;loraB|3;loraC", 2)
    → "loraA|2;loraB|6;loraC|2"
    """
    values = [v.strip() for v in values_str.split(";") if v.strip()]
    result = []
    for v in values:
        existing_value, existing_count = parse_value_with_count(v)
        new_count = existing_count * count
        if new_count > 1:
            result.append(f"{existing_value}|{new_count}")
        else:
            result.append(existing_value)
    return ";".join(result)


def _expand_raw_values(raw_values, variables):
    """生の値リストに対し、各値を変数展開して flatten した値リストを返す。"""
    if not variables:
        return raw_values
    result = []
    for rv in raw_values:
        result.extend(expand_value(rv, variables))
    # 空文字を除去
    return [v for v in result if v.strip()]


def _parse_line_columns(line, variables=None):
    """1行を解析し、列リストとシャッフル列インデックスを返す
    
    { } で囲まれた列はシャッフルグループとして扱う。
    
    例: "$style // { $キャラ // $lora }"
    → columns: [["styleA","styleB"], ["charaA","charaB"], ["loraA","loraB"]]
    → shuffle_indices: [1, 2]  (列1と列2がシャッフル対象)
    
    Returns:
        group: 列のリスト [[(値, 枚数), ...], ...]
        shuffle_indices: シャッフル対象の列インデックスのリスト
    """
    shuffle_indices = []
    
    # { } の有無を確認
    if "{" not in line:
        # 通常の行：//で分割
        columns = [col.strip() for col in line.split("//")]
        group = []
        for col in columns:
            raw_values = [v.strip() for v in col.split(";") if v.strip()]
            raw_values = _expand_raw_values(raw_values, variables)
            parsed_values = [parse_value_with_count(v) for v in raw_values]
            if parsed_values:
                group.append(parsed_values)
        return group, shuffle_indices
    
    # { } がある場合：まず // で分割してから { } の範囲を特定
    # 方針：行全体を // で分割し、各列が { } 内かどうかを追跡
    group = []
    in_shuffle = False
    
    # { と } を // と同等に扱うためにトークン化
    # "A // { B // C } // D" → ["A", "{", "B", "C", "}", "D"]
    tokens = []
    for part in line.split("//"):
        part = part.strip()
        if not part:
            continue
        
        # { や } が含まれる場合を分離
        while part:
            if "{" in part:
                idx = part.index("{")
                before = part[:idx].strip()
                if before:
                    tokens.append(before)
                tokens.append("{")
                part = part[idx + 1:].strip()
            elif "}" in part:
                idx = part.index("}")
                before = part[:idx].strip()
                if before:
                    tokens.append(before)
                tokens.append("}")
                part = part[idx + 1:].strip()
            else:
                tokens.append(part)
                break
    
    col_index = 0
    for token in tokens:
        if token == "{":
            in_shuffle = True
            continue
        elif token == "}":
            in_shuffle = False
            continue
        
        raw_values = [v.strip() for v in token.split(";") if v.strip()]
        raw_values = _expand_raw_values(raw_values, variables)
        parsed_values = [parse_value_with_count(v) for v in raw_values]
        if parsed_values:
            if in_shuffle:
                shuffle_indices.append(col_index)
            group.append(parsed_values)
            col_index += 1
    
    return group, shuffle_indices


def _interleave_combinations(columns):
    """複数列の値をローテーション方式で組み合わせる
    
    直積の全パターンを網羅しつつ、各列の値がなるべく連続しないように並べる。
    
    例: columns = [[(A,1),(B,1),(C,1)], [(X,1),(Y,1),(Z,1)]]
    直積:       AX, AY, AZ, BX, BY, BZ, CX, CY, CZ
    ローテ:     AX, BY, CZ, AY, BZ, CX, AZ, BX, CY
    
    アルゴリズム:
    - 全直積を生成
    - 各列の値の数でローテーションオフセットを適用して並び替え
    """
    if not columns or len(columns) < 2:
        return list(itertools.product(*columns))
    
    # 各列の値リスト（枚数情報付き）
    col_sizes = [len(col) for col in columns]
    
    # 全直積の総数
    total = 1
    for s in col_sizes:
        total *= s
    
    # ローテーション方式で組み合わせを生成
    # 各ステップで、列0はインデックスを順に回す
    # 列1以降はオフセットをずらしていく
    result = []
    seen = set()
    
    # 最大の列サイズを基準にラウンドを回す
    max_size = max(col_sizes)
    rounds = total // max_size + (1 if total % max_size else 0)
    
    for round_idx in range(total):
        indices = []
        for col_idx, col in enumerate(columns):
            size = len(col)
            if col_idx == 0:
                # 列0: 単純にローテーション
                idx = round_idx % size
            else:
                # 列1以降: 列0が一周するたびにオフセットをずらす
                cycle = round_idx // col_sizes[0]
                idx = (round_idx + cycle * col_idx) % size
            indices.append(idx)
        
        key = tuple(indices)
        if key not in seen:
            seen.add(key)
            combo = tuple(columns[col_idx][idx] for col_idx, idx in enumerate(indices))
            result.append(combo)
        
        if len(result) >= total:
            break
    
    # seenで重複排除した分、まだ足りないパターンがあれば直積から補完
    if len(result) < total:
        all_combos = list(itertools.product(*columns))
        result_set = set(result)
        for combo in all_combos:
            if combo not in result_set:
                result.append(combo)
                if len(result) >= total:
                    break
    
    return result


def parse_group_list(text):
    """行単位グループリストを解析する
    
    Returns:
        groups: [(列リスト, shuffle_indices), ...]
        各グループは (列のリスト, シャッフル対象列インデックス) のタプル
    """
    if not text or not text.strip():
        return []

    # 前処理（コメント除去・空行除去）— 全処理の最上流で1回だけ実行
    text = preprocess_text(text)

    # 変数定義と生成リストを分割
    variables = {}

    if "---" in text:
        parts = text.split("---", 1)
        variables = parse_variables(parts[0])
        generate_text = parts[1]
    else:
        generate_text = text

    # 構造的記号 (//, {, }) を含む変数のみ先に line レベルで展開する。
    # それ以外の変数（複数値含む）は値単位で展開し、; の二重解釈を防ぐ。
    generate_text = expand_structural_variables(generate_text, variables)

    groups = []

    for line in generate_text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        group, shuffle_indices = _parse_line_columns(line, variables)

        if group:
            groups.append((group, shuffle_indices))

    return groups


def build_jobs(groups):
    """行単位グループからジョブリストを構築する
    
    各行内は直積（またはシャッフル）、行間は独立して処理する。
    各組み合わせの枚数は、含まれる項目の|数字を掛け算して決定する。
    { } で囲まれた列はローテーション方式で並び替えられる。
    """
    jobs = []
    total_images = 0

    for group, shuffle_indices in groups:
        if shuffle_indices and len(shuffle_indices) >= 2:
            # シャッフル列とそれ以外を分離
            normal_indices = [i for i in range(len(group)) if i not in shuffle_indices]
            
            shuffle_columns = [group[i] for i in shuffle_indices]
            normal_columns = [group[i] for i in normal_indices]
            
            # シャッフル列をローテーション方式で組み合わせ
            shuffle_combos = _interleave_combinations(shuffle_columns)
            
            # 通常列は直積
            if normal_columns:
                normal_combos = list(itertools.product(*normal_columns))
            else:
                normal_combos = [()]
            
            # 通常列の各組み合わせに対して、シャッフル列を結合
            for normal_combo in normal_combos:
                for shuffle_combo in shuffle_combos:
                    # 元の列順序に戻す
                    combined = [None] * len(group)
                    norm_iter = iter(normal_combo)
                    shuf_iter = iter(shuffle_combo)
                    for i in range(len(group)):
                        if i in shuffle_indices:
                            combined[i] = next(shuf_iter)
                        else:
                            combined[i] = next(norm_iter)
                    
                    combo = tuple(combined)
                    count = 1
                    for value, item_count in combo:
                        count *= item_count
                    values = tuple(value for value, _ in combo)
                    jobs.append((values, count, len(group)))
                    total_images += count
        else:
            # 通常の直積
            group_combos = list(itertools.product(*group))

            for combo in group_combos:
                count = 1
                for value, item_count in combo:
                    count *= item_count
                values = tuple(value for value, _ in combo)
                jobs.append((values, count, len(group)))
                total_images += count

    return jobs, total_images


class PromptBuilder:
    """ポジティブ・ネガティブプロンプトの構築を担当するクラス

    値の中に !! が含まれる場合、!! の前をポジティブ、後をネガティブとして分離する。
    ポジティブプロンプトでは {N} プレースホルダを、
    ネガティブプロンプトでは {!N} プレースホルダを使用する。
    """

    SEPARATOR = "!!"

    @classmethod
    def split_value(cls, value):
        """値文字列をポジティブとネガティブに分離する

        例: "suzune horikita !! large breasts" → ("suzune horikita", "large breasts")
        例: "school uniform"                   → ("school uniform", "")
        """
        if cls.SEPARATOR in value:
            parts = value.split(cls.SEPARATOR, 1)
            return parts[0].strip(), parts[1].strip()
        return value, ""

    @classmethod
    def _extract_values(cls, combo, is_negative):
        """comboから指定された側（ポジ/ネガ）の値を抽出する"""
        index = 1 if is_negative else 0
        return tuple(cls.split_value(v)[index] for v in combo)

    @classmethod
    def _replace_placeholders(cls, template, values, num_columns, prefix=""):
        """テンプレート内のプレースホルダを値で置換する

        prefix="" の場合: {1}, {2}, {3}...
        prefix="!" の場合: {!1}, {!2}, {!3}...
        """
        result = template

        # プレースホルダの存在確認
        has_placeholder = any(
            "{" + prefix + str(i + 1) + "}" in result
            for i in range(num_columns)
        )

        if has_placeholder:
            for i, value in enumerate(values):
                placeholder = "{" + prefix + str(i + 1) + "}"
                result = result.replace(placeholder, value)
            # 空値の置換で生じた余分なカンマ・空白を整形
            result = cls._cleanup_prompt(result)
        elif not prefix:
            # ポジティブでプレースホルダなしの場合のみ先頭追加
            non_empty = [v for v in values if v]
            if non_empty:
                result = " ".join(non_empty) + " " + result

        return result

    @staticmethod
    def _cleanup_prompt(text):
        """プロンプト文字列を整形する

        - 連続するカンマ（間の空白含む）を1つのカンマに
        - 先頭・末尾の不要なカンマ・空白を除去
        """
        # ", , , " → ", "
        text = re.sub(r'(,\s*){2,}', ', ', text)
        # 先頭のカンマ+空白を除去
        text = re.sub(r'^\s*,\s*', '', text)
        # 末尾のカンマ+空白を除去
        text = re.sub(r'\s*,\s*$', '', text)
        return text.strip()

    @classmethod
    def build_positive(cls, template, combo, num_columns):
        """ポジティブプロンプトを構築する

        combo内の各値から !! 前のポジティブ部分を抽出し、
        テンプレート内の {1}, {2}, {3}... を置換する。
        """
        positive_values = cls._extract_values(combo, is_negative=False)
        return cls._replace_placeholders(template, positive_values, num_columns, prefix="")

    @classmethod
    def build_negative(cls, template, combo, num_columns):
        """ネガティブプロンプトを構築する

        combo内の各値から !! 後のネガティブ部分を抽出し、
        テンプレート内の {!1}, {!2}, {!3}... を置換する。
        {!N} がテンプレートに存在しない場合はテンプレートをそのまま返す。
        """
        negative_values = cls._extract_values(combo, is_negative=True)
        return cls._replace_placeholders(template, negative_values, num_columns, prefix="!")


def build_prompt(original_prompt, combo, num_columns):
    """組み合わせからポジティブプロンプトを構築する（後方互換）

    comboの各要素を {1}, {2}, {3}... に対応させる。
    値に !! が含まれる場合、!! 前のポジティブ部分のみ使用する。
    """
    return PromptBuilder.build_positive(original_prompt, combo, num_columns)


def build_negative_prompt(original_negative, combo, num_columns):
    """組み合わせからネガティブプロンプトを構築する

    comboの各要素を {!1}, {!2}, {!3}... に対応させる。
    値に !! が含まれる場合、!! 後のネガティブ部分のみ使用する。
    {!N} がない場合はoriginal_negativeをそのまま返す。
    """
    return PromptBuilder.build_negative(original_negative, combo, num_columns)


def get_slot_summary(groups):
    """進捗保存用のスロット情報を返す"""
    slots = []
    for group, shuffle_indices in groups:
        col_values = []
        for col in group:
            for value, count in col:
                display = f"{value}|{count}" if count > 1 else value
                col_values.append(display)
        slots.append(col_values)
    return slots
