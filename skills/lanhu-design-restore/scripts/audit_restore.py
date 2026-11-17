"""交付前对账：设计稿（layers.json）vs 已生成的前端代码。

用法（C3 门禁；不带 --fail-on-missing 时只报告不阻塞）：
    python scripts/audit_restore.py --layers <layers.json>[,...] --code <file.vue>[,...]
           [--root auto|容器名] [--extra-root 弹窗面板,抽屉] [--var-file <base.css,...>]
           [--accept <accept.json>] [--top N] [--fail-on-missing]

--fail-on-missing：只要「设计有·代码未出现」（文案/颜色/圆角/边框/字号/字距/阴影）
还有未登记项就退出码 1，可直接当交付门禁；accept 清单里登记过的偏差不算缺口。

v2 相比 v1 修掉的假阳性/假阴性：
  1. 边框用 inset box-shadow 实现（box-shadow: 0 0 0 1px X inset）现在能识别
  2. letter-spacing 用 em 表达现在能匹配（按设计字号换算）
  3. 渐变 stops 的颜色现在计入设计色值
  4. 代码独有颜色分三类：项目规范色（来自 --var-file 定义）/ 组件库默认 / 未定义（只有这类算可疑）
  5. symbol 实例 radius 与 <4px 装饰形状不再计入设计圆角
  6. 支持 --accept 清单：登记「设计稿 ↔ 项目规范」的已知偏差，不再重复报
  7. 阴影开始比对（颜色 + blur + inset），不再只打印设计值
  8. 几何 padding/gap 只作参考清单（带容器名），不给百分比
  9. 一个 .vue 对应多块设计区域（页面 + 弹窗 + 抽屉）时用 --extra-root 全纳入；
     文案按 (内容, 图层) 去重，多张设计稿不再重复计分母
 10. node.opacity=0 的图层（设计稿里根本看不见的隐藏/废弃态）整棵跳过——
     否则它的填充色/圆角/阴影会被当成设计需求，凭空造出假缺口
 11. 颜色 alpha 乘节点有效不透明度：遮罩常写成「黑填充 + opacity 0.6」，
     不乘就会把 rgba(0,0,0,0.6) 记成 rgba(0,0,0,1)
 12. 渐变 stops 两种落点都认（fill.stops 与 fill.gradient.stops）——取数层用的是前者
 13. 字距按 0.2px 容差比（设计写 em、代码写 px，实际差 0.1~0.15px，渲染不可见）
 14. 几何只报「≥2 个容器共用且 ≤60px」的值，绝对定位/两端对齐算出的 133/200 不再当间距
 15. 文案分三档：图层唯一=计分；同名图层多内容=表格/列表清单（人工判断、不计分）；
     纯数字/编码=示例数据直接排除

已经踩过的坑（别回退）：
  · 用「同名图层有多句内容」当数据判据不要写成「整层排除」——表头与单元格同名，
    把整层排除会把真表头（来源关联/操作/引用）一起放过；只能降级成人工清单
  · 几何数字不能当得分：选择框/表格行内部的 6/10/41 是组件内部实现，不是页面间距

仍然覆盖不到的：hover/禁用/空态等交互状态、字体实际字形、被遮挡元素的可视性、
代码侧按整文件扫（--root 限定的设计区域之外的颜色也会出现在「代码独有」里）、
布局/间距本身（几何只做参考清单；布局要对 DOM 实测，不在本脚本范围）。
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

# --------------------------------------------------------------------------- 基础

HEX_RE = re.compile(r'#([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b')
RGBA_RE = re.compile(r'rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)(?:\s*,\s*([\d.]+%?))?\s*\)')
DESIGN_RGBA_RE = re.compile(r'rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)')

# 组件库（Element Plus）默认色：出现这些不算项目自造
EP_COLORS = {
    (64, 158, 255), (121, 187, 255), (103, 194, 58), (230, 162, 60), (245, 108, 108),
    (144, 147, 153), (96, 98, 102), (192, 196, 204), (235, 238, 245), (245, 247, 250),
    (220, 223, 230), (233, 236, 241), (250, 250, 250), (48, 49, 51), (48, 55, 61),
    (168, 171, 178), (64, 64, 64), (0, 0, 0), (255, 255, 255),
}
# 与设计稿可能不同但属于通用基础色
BASE_COLORS = {(255, 255, 255), (0, 0, 0), (250, 250, 250), (51, 51, 51), (102, 102, 102),
               (153, 153, 153), (204, 204, 204), (238, 238, 238), (243, 243, 243)}


def norm_color(r, g, b, a=1.0):
    return (int(round(float(r))), int(round(float(g))), int(round(float(b))), round(float(a), 2))


def parse_code_colors(text):
    out = Counter()
    for m in HEX_RE.finditer(text):
        h = m.group(1)
        if len(h) in (3, 4):
            r, g, b = (int(c * 2, 16) for c in h[:3])
            a = int(h[3] * 2, 16) / 255 if len(h) == 4 else 1.0
        elif len(h) == 6:
            r, g, b, a = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0
        else:
            r, g, b, a = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16) / 255
        out[norm_color(r, g, b, a)] += 1
    for m in RGBA_RE.finditer(text):
        a = m.group(4)
        if a and a.endswith('%'):
            a = float(a[:-1]) / 100
        out[norm_color(m.group(1), m.group(2), m.group(3), float(a) if a else 1.0)] += 1
    return out


def parse_design_color(value):
    """rgba() 字符串（fills/borders/shadows）或 {r,g,b,a} 字典（text.color）。"""
    if not value:
        return None
    if isinstance(value, dict):
        if all(k in value for k in ('r', 'g', 'b')):
            return norm_color(value['r'], value['g'], value['b'], value.get('a', 1))
        return None
    if not isinstance(value, str):
        return None
    m = DESIGN_RGBA_RE.search(value)
    return norm_color(m.group(1), m.group(2), m.group(3), m.group(4)) if m else None


def with_alpha(color, opacity=1.0):
    """把节点有效不透明度乘进颜色 alpha（设计稿常把 60% 遮罩写成 fill=黑 + opacity=0.6）。"""
    if color is None:
        return None
    if opacity >= 0.999:
        return color
    return (color[0], color[1], color[2], round(color[3] * opacity, 2))


def color_dist(a, b):
    drgb = sum((x - y) ** 2 for x, y in zip(a[:3], b[:3])) ** 0.5
    return drgb, abs(a[3] - b[3])


def spacing_px(value, font_size=None):
    """{value, unit} → px；PERCENT 按字号换算。"""
    if value is None:
        return None
    if isinstance(value, dict):
        v, unit = value.get('value'), (value.get('unit') or '').upper()
        if v is None:
            return None
        v = float(v)
        if unit.startswith('PERCENT') and font_size:
            return round(v / 100.0 * float(font_size), 2)
        return round(v, 2)
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- 设计侧

def walk(node):
    yield node
    for c in node.get('children') or []:
        yield from walk(c)


def subtree_size(node):
    return 1 + sum(subtree_size(c) for c in node.get('children') or [])


def pick_root(tree, root_name):
    if root_name == 'auto':
        board = tree.get('frame') or {}
        board_w = board.get('width') or 0
        cands = []
        for n in walk(tree):
            f = n.get('frame') or {}
            left, width = f.get('left') or 0, f.get('width') or 0
            if left > 50 and width >= 600 and (not board_w or width < board_w - 100) \
                    and subtree_size(n) > 100:
                cands.append(n)
        if not cands:
            return None
        chosen = max(cands, key=subtree_size)
        f = chosen.get('frame') or {}
        print(f'    auto 内容区: {chosen.get("name")!r} '
              f'(frame {f.get("left")},{f.get("top")} {f.get("width")}×{f.get("height")}, '
              f'{subtree_size(chosen)} 节点)')
        return chosen
    matches = [n for n in walk(tree) if n.get('name') == root_name or n.get('node_id') == root_name]
    if not matches:
        return None
    chosen = max(matches, key=subtree_size)
    if len(matches) > 1:
        f = chosen.get('frame') or {}
        print(f'    ⚠ {len(matches)} 个同名 {root_name!r}，取最大子树 '
              f'(frame {f.get("left")},{f.get("top")} {f.get("width")}×{f.get("height")})')
    return chosen


def collect_design(layers_files, root_name=None, accept=None, extra_roots=()):
    accept = accept or {}
    ignore_radius = {float(v) for v in accept.get('ignore_radius', [])}
    snap = {
        'colors': Counter(), 'radii': Counter(), 'border_widths': Counter(),
        'fonts': Counter(), 'texts': [], 'shadows': Counter(),
        'paddings': Counter(), 'gaps': Counter(), 'padding_examples': defaultdict(set),
        'gap_examples': defaultdict(set),
    }
    for path in layers_files:
        tree = json.load(open(path, encoding='utf-8'))
        scopes = []
        if root_name:
            scope = pick_root(tree, root_name)
            if scope is None:
                raise SystemExit(f'在 {os.path.basename(path)} 里找不到根节点: {root_name}')
            scopes.append(scope)
        else:
            scopes.append(tree)
        # 同一个 .vue 常实现「页面 + 弹层」多块区域：额外把弹窗面板等子树纳入
        for name in extra_roots:
            extra = pick_root(tree, name)
            if extra is None:
                print(f'    ⚠ {os.path.basename(os.path.dirname(path))} 里没有 {name!r}，跳过')
            else:
                scopes.append(extra)
        for scope in scopes:
            _collect_scope(snap, scope, ignore_radius)
    # 多张设计稿常复用同一批图层（页面/弹窗/抽屉），文案按 (内容, 图层) 去重；
    # 不去重则同一句文案被统计 N 次，覆盖率分母虚高、缺失项重复列
    snap['texts'] = list(dict.fromkeys(snap['texts']))
    return snap


def _collect_scope(snap, scope, ignore_radius):
    # 文案记录上级容器名：表格行 / 列表项的示例值一眼可辨，不必硬猜。
    # 同时算「有效不透明度」：node.opacity=0 的元素在设计稿里完全不可见（典型是
    # 被隐藏的交互态/废弃图层），它的填充色/圆角/阴影都不是设计需求，必须跳过，
    # 否则会凭空多出「设计有·代码未出现」的假缺口。
    parent_of = {}
    eff_opacity = {}

    def stamp(node, inherited=1.0):
        op = node.get('opacity')
        op = inherited * (1.0 if op is None else float(op))
        eff_opacity[id(node)] = op
        for child in node.get('children') or []:
            parent_of[id(child)] = node
            stamp(child, op)

    stamp(scope)
    for node in walk(scope):
        if eff_opacity.get(id(node), 1.0) <= 0.01:
            continue
        st = node.get('style') or {}
        node_type = str(node.get('type') or '').lower()
        nf = node.get('frame') or {}
        tiny = (nf.get('width') or 0) < 4 or (nf.get('height') or 0) < 4
        # 看见的颜色 = 填充色 × 节点有效不透明度；遮罩层就是 black@opacity 0.6 这种写法，
        # 不乘就会把 rgba(0,0,0,0.6) 记成 rgba(0,0,0,1)
        eff = eff_opacity.get(id(node), 1.0)

        for f in st.get('fills') or []:
            c = with_alpha(parse_design_color(f.get('color')), eff)
            if c:
                snap['colors'][c] += 1
            # 渐变 stops 的颜色也要计入。取数层把 stops 放在 fill 顶层（type=gradient），
            # 也有格式嵌在 fill.gradient.stops 下，两种都认，否则渐变端点色会被误报「代码独有」
            stops = f.get('stops') or (f.get('gradient') or {}).get('stops') or []
            for s in stops:
                sc = with_alpha(parse_design_color(s.get('color')), eff)
                if sc:
                    snap['colors'][sc] += 1
        for b in st.get('borders') or []:
            c = with_alpha(parse_design_color(b.get('color')), eff)
            if c:
                snap['colors'][c] += 1
            if b.get('thickness'):
                snap['border_widths'][round(float(b['thickness']), 2)] += 1
        for s in st.get('shadows') or []:
            c = with_alpha(parse_design_color(s.get('color')), eff)
            if c:
                snap['colors'][c] += 1
                off = s.get('offset') or (0, 0)
                snap['shadows'][(round(float(off[0]), 2), round(float(off[1]), 2),
                                 round(float(s.get('blur') or 0), 2),
                                 round(float(s.get('spread') or 0), 2),
                                 bool(s.get('inset')), c)] += 1
        r = st.get('radius')
        if r and not node_type.startswith('symbol') and not tiny:
            for v in r:
                if v and round(float(v), 2) not in ignore_radius:
                    snap['radii'][round(float(v), 2)] += 1

        t = node.get('text') or {}
        c = with_alpha(parse_design_color(t.get('color')), eff)
        if c:
            snap['colors'][c] += 1
        size = t.get('size')
        if size:
            tcol = t.get('color')
            ckey = tuple(tcol.get(k) for k in ('r', 'g', 'b', 'a')) if isinstance(tcol, dict) else tcol
            ls_px = spacing_px(t.get('letterSpacing'), size)
            ls_em = round(ls_px / float(size), 3) if ls_px else None
            snap['fonts'][(round(float(size), 2), ckey, ls_px, ls_em,
                           spacing_px(t.get('lineHeight'), size))] += 1
        content = (t.get('content') or '').strip()
        if content and len(content) >= 2:
            pn = parent_of.get(id(node))
            snap['texts'].append((content, node.get('name'), (pn or {}).get('name')))

    # 几何参考：容器 padding / 兄弟 gap（带容器名，供人工判断）
    for node in walk(scope):
        if eff_opacity.get(id(node), 1.0) <= 0.01:
            continue
        kids = [c for c in (node.get('children') or [])
                if eff_opacity.get(id(c), 1.0) > 0.01]
        if len(kids) < 2:
            continue
        f = node.get('frame') or {}
        if not f:
            continue
        inner = []
        for k in kids:
            kf = k.get('frame') or {}
            if not kf:
                continue
            if (kf.get('left', 0) >= f.get('left', 0) - 1
                    and kf.get('top', 0) >= f.get('top', 0) - 1
                    and kf.get('left', 0) + kf.get('width', 0) <= f.get('left', 0) + f.get('width', 0) + 1
                    and kf.get('top', 0) + kf.get('height', 0) <= f.get('top', 0) + f.get('height', 0) + 1):
                inner.append(kf)
        if len(inner) < 2:
            continue
        min_l = min(k['left'] for k in inner)
        min_t = min(k['top'] for k in inner)
        max_r = max(k['left'] + k['width'] for k in inner)
        max_b = max(k['top'] + k['height'] for k in inner)
        for v in (min_l - f['left'], min_t - f['top'],
                  f['left'] + f['width'] - max_r, f['top'] + f['height'] - max_b):
            v = round(float(v))
            if 0 <= v <= 200:
                snap['paddings'][v] += 1
                snap['padding_examples'][v].add(node.get('name'))
        xs = sorted(inner, key=lambda k: k['left'])
        for a, b in zip(xs, xs[1:]):
            g = round(float(b['left'] - (a['left'] + a['width'])))
            if 0 <= g <= 200:
                snap['gaps'][g] += 1
                snap['gap_examples'][g].add(node.get('name'))
        ys = sorted(inner, key=lambda k: k['top'])
        for a, b in zip(ys, ys[1:]):
            g = round(float(b['top'] - (a['top'] + a['height'])))
            if 0 <= g <= 200:
                snap['gaps'][g] += 1
                snap['gap_examples'][g].add(node.get('name'))
    return snap


# --------------------------------------------------------------------------- 代码侧

VAR_DEF_RE = re.compile(r'(--[\w-]+)\s*:\s*([^;{}]+)')


def load_var_map(var_files):
    mapping = {}
    for path in var_files:
        text = open(path, encoding='utf-8', errors='replace').read()
        for m in VAR_DEF_RE.finditer(text):
            mapping[m.group(1)] = m.group(2).strip()
    return mapping


def resolve_vars(text, var_map):
    if not var_map:
        return text
    pattern = re.compile(r'var\(\s*(--[\w-]+)\s*(?:,\s*([^)]*))?\)')
    for _ in range(3):
        def sub(m):
            value = var_map.get(m.group(1))
            if value and value.startswith('var('):
                return value
            return value or m.group(2) or m.group(0)
        new = pattern.sub(sub, text)
        if new == text:
            break
        text = new
    return text


def strip_comments(text):
    text = re.sub(r'<!--.*?-->', ' ', text, flags=re.S)
    text = re.sub(r'/\*.*?\*/', ' ', text, flags=re.S)
    text = re.sub(r'(?m)^\s*//.*$', ' ', text)
    return text


DECL_RE = {
    'radius': re.compile(r'border-radius\s*:\s*([^;{}]+)'),
    'font-size': re.compile(r'font-size\s*:\s*([^;{}]+)'),
    'letter-spacing': re.compile(r'letter-spacing\s*:\s*([^;{}]+)'),
    'line-height': re.compile(r'line-height\s*:\s*([^;{}]+)'),
    'border': re.compile(r'border(?:-(?:top|right|bottom|left))?\s*:\s*([^;{}]+)'),
    'box-shadow': re.compile(r'box-shadow\s*:\s*([^;{}]+)'),
    'padding': re.compile(r'(?:padding|padding-(?:top|right|bottom|left))\s*:\s*([^;{}]+)'),
    'gap': re.compile(r'(?:gap|row-gap|column-gap)\s*:\s*([^;{}]+)'),
    'margin': re.compile(r'(?:margin|margin-(?:top|right|bottom|left))\s*:\s*([^;{}]+)'),
}


def nums_in(value):
    return [round(float(x), 2) for x in re.findall(r'-?\d+(?:\.\d+)?', value or '')]


def pem_in(value):
    """返回 [(数值, 单位)]，单位 px/em/rem/% 等。"""
    return [(float(v), u or 'px') for v, u in
            re.findall(r'(-?\d+(?:\.\d+)?)\s*(px|em|rem|%)?', value or '') if v]


def collect_code(code_files, var_files=()):
    raw = ''
    for p in code_files:
        raw += '\n' + open(p, encoding='utf-8', errors='replace').read()
    var_map = load_var_map(var_files)
    text = resolve_vars(strip_comments(raw), var_map)
    out = {'colors': parse_code_colors(text), 'decls': {k: [] for k in DECL_RE}, 'var_map': var_map}
    for key, rx in DECL_RE.items():
        for m in rx.finditer(text):
            out['decls'][key].append(m.group(1))
    return out


def code_borders(code):
    """边框：既认 border: 1px solid，也认 box-shadow 里 inset 的 0 0 0 Npx 描边。"""
    widths = set()
    for v in code['decls']['border']:
        for n in nums_in(v):
            if n:
                widths.add(round(n, 2))
    for v in code['decls']['box-shadow']:
        # 形如：0 0 0 1px #e0e0e0 inset / inset 0 3px 5px rgba(...)
        for m in re.finditer(r'(\d+(?:\.\d+)?)px', v):
            n = float(m.group(1))
            if n:
                widths.add(round(n, 2))
    return widths


def code_letter_spacings(code):
    px_vals, em_vals = set(), set()
    for v in code['decls']['letter-spacing']:
        for n, unit in pem_in(v):
            if unit == 'em' or unit == 'rem':
                em_vals.add(round(n, 3))
            else:
                px_vals.add(round(n, 3))
    return px_vals, em_vals


def code_shadows(code):
    """把 box-shadow 声明解析成 [(inset, 数字元组, 颜色)]。"""
    out = []
    for v in code['decls']['box-shadow']:
        for part in re.split(r',(?![^()]*\))', v):
            inset = 'inset' in part
            nums = [n for n in nums_in(re.sub(r'rgba?\([^)]*\)', '', part))]
            col = None
            m = RGBA_RE.search(part)
            if m:
                a = m.group(4)
                if a and a.endswith('%'):
                    a = float(a[:-1]) / 100
                col = norm_color(m.group(1), m.group(2), m.group(3), float(a) if a else 1.0)
            else:
                hm = HEX_RE.search(part)
                if hm:
                    h = hm.group(1)
                    if len(h) == 3:
                        h = ''.join(c * 2 for c in h)
                    if len(h) >= 6:
                        col = norm_color(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
            if nums or col:
                out.append((inset, tuple(round(x, 2) for x in nums), col))
    return out


STATE_RE = re.compile(r':(hover|focus|active|disabled|checked|visited|link)\b|::(selection|placeholder)')


def state_colors(text):
    """收集只出现在交互态规则里的颜色（hover/focus/disabled/::placeholder 等）。

    做法：对每个颜色出现位置，回退到最近的 `{`，取它前面的选择器片段判断是否含状态伪类。
    """
    out = set()
    for m in list(HEX_RE.finditer(text)) + list(RGBA_RE.finditer(text)):
        start = m.start()
        brace = text.rfind('{', 0, start)
        if brace < 0:
            continue
        prev_end = max(text.rfind('}', 0, brace), text.rfind('{', 0, brace))
        selector = text[prev_end + 1:brace]
        if STATE_RE.search(selector):
            chunk = m.group(0)
            parsed = parse_code_colors(chunk)
            out.update(parsed)
    return out


def code_geometry(code):
    geo = set()
    for key in ('padding', 'gap', 'margin'):
        for v in code['decls'][key]:
            for n in nums_in(v):
                if 0 <= n <= 200:
                    geo.add(round(n))
    return geo


# --------------------------------------------------------------------------- 报告

DATA_TEXT_RE = re.compile(
    r'^[\s\d\W]+$'
    r'|^[A-Z]{1,4}\d{2}[-–]'
    r'|^\d+\s*(段|条|个|项|人|天|次)$'
)


def classify_texts(texts):
    """把设计文案分成三桶。

    strong —— 图层名只对应一句内容：标准 UI 文案，必须出现在代码里，计入得分
    weak   —— 同图层名挂着多句内容：典型是表格列/列表行（表头 + 单元格同名），
              或复用组件；只列清单供人工判断，不计入得分（既不冤枉也不放过）
    data   —— 纯数字/编码/计数，是示例数据，直接排除
    """
    by_layer = defaultdict(set)
    for content, layer, _parent in texts:
        by_layer[layer].add(content)
    strong, weak, data = [], [], []
    for content, layer, parent in texts:
        if DATA_TEXT_RE.search(content):
            data.append((content, layer, parent))
        elif len(by_layer[layer]) > 1:
            weak.append((content, layer, parent))
        else:
            strong.append((content, layer, parent))
    return strong, weak, data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--layers', required=True)
    ap.add_argument('--code', required=True)
    ap.add_argument('--var-file', default='')
    ap.add_argument('--accept', default='')
    ap.add_argument('--root', default=None)
    ap.add_argument('--extra-root', default='',
                    help='额外纳入的设计子树名（逗号分隔），如弹窗面板/抽屉；同一 .vue 常实现多块区域')
    ap.add_argument('--top', type=int, default=12)
    ap.add_argument('--near', type=float, default=6.0)
    ap.add_argument('--fail-on-missing', action='store_true',
                    help='有未登记缺口时退出码 1（交付门禁用）；默认只报告')
    args = ap.parse_args()

    layers_files = [p for p in args.layers.split(',') if p]
    code_files = [p for p in args.code.split(',') if p]
    var_files = [p for p in args.var_file.split(',') if p]
    extra_roots = [p.strip() for p in args.extra_root.split(',') if p.strip()]
    accept = json.load(open(args.accept, encoding='utf-8')) if args.accept else {}
    ignore_texts = set(accept.get('ignore_texts', []))
    ignore_colors = {norm_color(*c) if isinstance(c, list) else None for c in accept.get('ignore_colors', [])}
    ignore_colors = {c for c in ignore_colors if c}
    project_colors = set()
    for c in accept.get('project_colors', []):
        if isinstance(c, list) and len(c) >= 3:
            project_colors.add(norm_color(*c))

    design = collect_design(layers_files, args.root, accept, extra_roots=extra_roots)
    code = collect_code(code_files, var_files)

    # 变量定义里的颜色也算「项目规范色」
    for value in code['var_map'].values():
        c = parse_code_colors(value)
        project_colors.update(c)

    print('=' * 78)
    print('代码  :', ', '.join(os.path.basename(p) for p in code_files))
    print('范围  :', f'设计子树 {args.root!r}' if args.root else '整张设计稿',
          f'+ 附加 {extra_roots}' if extra_roots else '')
    if var_files:
        print('变量  :', ', '.join(os.path.basename(p) for p in var_files))
    if accept:
        print('accept:', ', '.join(f'{k}={len(v) if isinstance(v, list) else v}' for k, v in accept.items()))
    print('=' * 78)

    # 门禁统计：只收「设计有·代码未出现」，代码独有不算缺口
    gaps = []

    # 1) 文案
    squash = re.sub(r'\s+', '', strip_comments(' '.join(
        open(p, encoding='utf-8', errors='replace').read() for p in code_files)))
    strong_texts, weak_texts, data_texts = classify_texts(design['texts'])
    strong_texts = [x for x in strong_texts if x[0] not in ignore_texts]
    hit = [x for x in strong_texts if re.sub(r'\s+', '', x[0]) in squash]
    miss = [x for x in strong_texts if re.sub(r'\s+', '', x[0]) not in squash]
    print(f'\n[1] 静态文案(图层唯一): {len(hit)}/{len(strong_texts)} '
          f'({len(hit) / max(1, len(strong_texts)) * 100:.0f}%)  '
          f'| 数值/编码示例 {len(data_texts)} 条已排除'
          + (f' | accept 忽略 {len(accept.get("ignore_texts", []))} 条' if accept.get('ignore_texts') else ''))
    for t, n, p in miss[:args.top]:
        print(f'      · 未出现 {t[:40]!r:<44} 图层 {n!r}')
    gaps += [('文案', t) for t, _n, _p in miss]
    # 同名图层挂多句内容 = 表格列/列表行（表头与单元格同名）或复用组件：
    # 只列清单不评分，避免把示例行数据算成「漏还原」，也避免漏掉真表头
    weak_texts = [x for x in weak_texts if x[0] not in ignore_texts]
    weak_miss = [x for x in weak_texts if re.sub(r'\s+', '', x[0]) not in squash]
    if weak_texts:
        print(f'[1b] 同名图层文案: {len(weak_texts) - len(weak_miss)}/{len(weak_texts)} 出现'
              f'（表格/列表/复用组件，人工判断）')
        for t, n, p in weak_miss[:args.top]:
            print(f'      · 未出现 {t[:36]!r:<38} 图层 {n!r} 上级 {p!r}')

    # 2) 颜色
    d_set = {c for c in design['colors'] if c not in ignore_colors}
    c_set = set(code['colors'])
    exact = d_set & c_set
    miss_c = d_set - c_set
    extra = c_set - d_set
    print(f'\n[2] 颜色: 设计 {len(d_set)} / 代码 {len(c_set)} | 精确命中 {len(exact)} '
          f'({len(exact) / max(1, len(d_set)) * 100:.0f}%)')
    if args.root or extra_roots:
        print('    注: 代码侧按整文件扫（含本次未纳入设计范围的区域），'
              '「代码独有」不代表设计稿要求，只有「设计有·代码未出现」才是缺口')

    near = []
    for d in miss_c:
        for c in extra:
            drgb, da = color_dist(d, c)
            if drgb <= args.near and da <= 0.02:
                near.append((d, c, drgb, design['colors'][d], code['colors'][c]))
    near.sort(key=lambda x: -x[3])
    if near:
        print(f'    ⚠ 近似但不等（{len(near)} 对，可能是目测取值）')
        for d, c, dist, dc, cc in near[:args.top]:
            tag = '（项目规范色）' if c in project_colors else ''
            print(f'      设计 rgba{tuple(d)} ×{dc} ←→ 代码 rgba{tuple(c)} ×{cc} 差 {dist:.1f}{tag}')

    unknown = [c for c in extra
               if c[:3] not in EP_COLORS and c[:3] not in BASE_COLORS
               and c not in project_colors and c[3] != 0]
    st_colors = state_colors(strip_comments(' '.join(
        open(p, encoding='utf-8', errors='replace').read() for p in code_files)))
    state_only = [c for c in unknown if c in st_colors]
    unknown = [c for c in unknown if c not in st_colors]
    if state_only:
        print(f'    代码独有·交互态（hover/focus/disabled，设计稿通常不覆盖）: {len(state_only)} 种'
              f' {[tuple(c) for c in state_only]}')
    if unknown:
        print(f'    代码独有·未定义来源（{len(unknown)} 种，按次数）')
        for c in sorted(unknown, key=lambda x: -code['colors'][x])[:args.top]:
            print(f'      rgba{tuple(c)} ×{code["colors"][c]}')
    muted = [c for c in extra if c in project_colors]
    if muted:
        print(f'    代码独有·项目规范色（已视为合规）: {len(muted)} 种')
    if miss_c:
        print(f'    设计有·代码未出现（{len(miss_c)} 种，按设计次数）')
        for c in sorted(miss_c, key=lambda x: -design['colors'][x])[:args.top]:
            print(f'      rgba{tuple(c)} 设计出现 {design["colors"][c]} 次')
    gaps += [('颜色', tuple(c)) for c in miss_c]

    # 3) 圆角
    c_radii = set()
    for v in code['decls']['radius']:
        for n in nums_in(v):
            c_radii.add(round(n, 2))
    d_radii = set(design['radii'])
    if d_radii:
        hit_r = d_radii & c_radii
        print(f'\n[3] 圆角: 设计 {sorted(d_radii)} | 命中 {len(hit_r)}/{len(d_radii)}'
              + (f' | 未命中 {sorted(d_radii - hit_r)}' if d_radii - hit_r else ' ✅'))
        gaps += [('圆角', v) for v in sorted(d_radii - hit_r)]

    # 4) 边框粗细（含 inset box-shadow 实现）
    d_bw = set(design['border_widths'])
    c_bw = code_borders(code)
    if d_bw:
        hit_b = d_bw & c_bw
        print(f'[4] 边框粗细: 设计 {sorted(d_bw)} | 代码（含 inset 描边）{sorted(c_bw)} '
              f'| 命中 {len(hit_b)}/{len(d_bw)}' + ('' if d_bw - hit_b else ' ✅')
              + (f' 未命中 {sorted(d_bw - hit_b)}' if d_bw - hit_b else ''))
        gaps += [('边框', v) for v in sorted(d_bw - hit_b)]

    # 5) 字号
    d_sizes = {p[0] for p in design['fonts']}
    c_sizes = set()
    for v in code['decls']['font-size']:
        for n in nums_in(v):
            c_sizes.add(round(n, 2))
    if d_sizes:
        hit_s = d_sizes & c_sizes
        print(f'[5] 字号: 设计 {sorted(d_sizes)} | 命中 {len(hit_s)}/{len(d_sizes)}'
              + (f' | 未命中 {sorted(d_sizes - hit_s)}' if d_sizes - hit_s else ' ✅'))
        gaps += [('字号', v) for v in sorted(d_sizes - hit_s)]

    # 6) 字距（同时认 px 与 em）
    d_ls = {(p[2], p[3], p[0]) for p in design['fonts'] if p[2]}  # (px, em, size)
    c_ls_px, c_ls_em = code_letter_spacings(code)
    if d_ls:
        matched, negligible, unmatched = [], [], []
        for px, em, size in d_ls:
            # 0.2px 以内视为同一字距：设计用 em（随字号换算）与代码用 px 常差
            # 0.1~0.15px，浏览器不可见；em 侧给 0.01em 容差
            near_px = any(abs(px - v) <= 0.2 for v in c_ls_px)
            near_em = bool(em) and any(abs(em - v) <= 0.01 for v in c_ls_em)
            if near_px or near_em:
                matched.append((px, em, size))
            elif abs(px) < 0.2:
                # 小于 0.2px 是亚像素（Sketch 的 0.12999 这类残留），浏览器渲染不出差异
                negligible.append((px, em, size))
            else:
                unmatched.append((px, em, size))
        print(f'[6] 字距: 设计 {len(d_ls)} 组 | 命中 {len(matched)}'
              + (f' | 亚像素忽略 {len(negligible)} {[px for px, _, _ in negligible]}' if negligible else '')
              + (f' | 未命中 {[(px, f"{em}em", f"{size}px") for px, em, size in unmatched]}' if unmatched else ' ✅'))
        gaps += [('字距', (px, em, size)) for px, em, size in unmatched]
        if c_ls_px or c_ls_em:
            print(f'      代码值: px={sorted(c_ls_px)} em={sorted(c_ls_em)}')

    # 7) 阴影（颜色已登记到 ignore_colors 的整条跳过，否则「登记了颜色还报阴影」）
    d_sh = Counter({k: v for k, v in design['shadows'].items() if k[5] not in ignore_colors})
    c_sh = code_shadows(code)
    if d_sh:
        hit_sh = 0
        for spec, cnt in d_sh.most_common():
            ox, oy, blur, spread, inset, col = spec
            found = any(
                s_inset == inset and s_col == col and round(blur, 2) in s_nums
                for s_inset, s_nums, s_col in c_sh
            )
            hit_sh += 1 if found else 0
            mark = '✅' if found else '⚠'
            print(f'[7] 阴影 {mark} {ox} {oy} blur={blur} spread={spread} inset={inset} '
                  f'rgba{tuple(col)} ×{cnt}')
            if not found:
                gaps.append(('阴影', spec))
        print(f'    阴影命中 {hit_sh}/{len(d_sh)}')

    # 8) 几何参考
    c_geo = code_geometry(code)
    print('\n[8] 几何参考（反推值，含组件内部布局，不作得分）')
    # 只保留「≥2 个不同容器都在用」且 ≤60px 的值：单个容器里算出来的大间距
    # （如 133/200）多半是绝对定位/两端对齐的产物，不是设计间距
    for label, key, ex_key in (('padding 反推', 'paddings', 'padding_examples'),
                               ('兄弟 gap', 'gaps', 'gap_examples')):
        vals = {v: c for v, c in design[key].items()
                if c >= 2 and 0 < v <= 60 and len(design[ex_key][v]) >= 2}
        if not vals:
            continue
        miss_v = sorted(v for v in vals if v not in c_geo)
        print(f'    {label}: 多容器共用 {sorted(vals)}' +
              (f' | 代码未出现 {miss_v}' if miss_v else ' | 均有对应 ✅'))
        for v in miss_v[:4]:
            print(f'      {v}px 来自容器: {sorted(design[ex_key][v])[:4]}')

    # 9) 门禁结论
    if gaps:
        kinds = Counter(k for k, _ in gaps)
        print(f'\n[9] 缺口合计 {len(gaps)} 项: ' +
              '、'.join(f'{k} {n}' for k, n in kinds.most_common()))
        print('    （「代码独有」与几何参考不计入；确认属项目规范/示例数据的，'
              '登记到 --accept 清单后不再报）')
    else:
        print('\n[9] 无未登记缺口 ✅')
    if args.fail_on_missing and gaps:
        sys.exit(1)


if __name__ == '__main__':
    main()
