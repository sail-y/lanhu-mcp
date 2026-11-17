"""从蓝湖设计 JSON 深度提取结构化图层树。取数优先复用上游 lanhu_design.normalize。"""
import hashlib
import json
import math
from pathlib import Path


def css_color(c):
    if not c:
        return None
    r, g, b = c.get('r', 0), c.get('g', 0), c.get('b', 0)
    a = c.get('a', 1)

    def hex8(x):
        return round(x * 255)
    return {'r': hex8(r), 'g': hex8(g), 'b': hex8(b), 'a': round(a, 3)}


def style_to_css(st, node):
    """把 style 里的 fills/borders/shadows/blurs/text 转成可读 CSS 描述。"""
    if not st.get('isEnabled', True):
        return {'isEnabled': False}
    out = {'isEnabled': True, 'opacity': st.get('opacity', 1)}
    # 圆角：Sketch 里在 paths[].radius，不在 node.radius
    for p in (node.get('paths') or []):
        r = p.get('radius')
        if isinstance(r, dict):
            vals = [r.get('topLeft'), r.get('topRight'), r.get('bottomLeft'), r.get('bottomRight')]
            if vals and any(v is not None for v in vals):
                out['radius'] = [v if v is not None else 0 for v in vals]
                break
    fills = []
    for f in (st.get('fills') or []):
        if not f.get('isEnabled', True):
            continue
        if f.get('type') == 'gradient':
            stops = []
            for s in f.get('gradient', {}).get('stops', []):
                col = css_color(s.get('color'))
                if col:
                    stops.append({'color': f'rgba({col["r"]},{col["g"]},{col["b"]},{col["a"]})', 'pos': round(s.get('position', 0), 2)})
            gr = f.get('gradient') or {}
            fills.append({'type': 'gradient', 'gradientType': gr.get('type'),
                          'from': gr.get('from'), 'to': gr.get('to'), 'stops': stops})
        elif f.get('type') in ('solid', 'color'):
            col = css_color(f.get('color'))
            if col:
                fills.append({'type': 'solid', 'color': f'rgba({col["r"]},{col["g"]},{col["b"]},{col["a"]})'})
        else:
            fills.append({'type': f.get('type'), 'raw': f})
    if fills:
        out['fills'] = fills
    borders = []
    for b in (st.get('borders') or []):
        if not b.get('isEnabled', True):
            continue
        col = css_color(b.get('color'))
        # 蓝湖原始 JSON 边框粗细字段是 width（thickness 不存在，兜底保留）
        borders.append({'thickness': b.get('width', b.get('thickness')),
                        'color': f'rgba({col["r"]},{col["g"]},{col["b"]},{col["a"]})' if col else None,
                        'lineAlignment': b.get('lineAlignment')})
    if borders:
        out['borders'] = borders
    if st.get('shadows'):
        sh = []
        for s in st.get('shadows') or []:
            if not s.get('isEnabled', True):
                continue
            col = css_color(s.get('color'))
            sh.append({'offset': (s.get('x'), s.get('y')), 'blur': s.get('blur'), 'spread': s.get('spread'),
                       'inset': bool(s.get('inset', False)),
                       'color': f'rgba({col["r"]},{col["g"]},{col["b"]},{col["a"]})' if col else None})
        if sh:
            out['shadows'] = sh
    if st.get('blurs'):
        blurs = []
        type_map = {0: 'gaussian', 1: 'motion', 2: 'zoom', 3: 'background'}
        for b in st.get('blurs') or []:
            if not b.get('isEnabled', True):
                continue
            blur_type = b.get('type', 0)
            radius = b.get('radius', 0)
            item = {
                'type': type_map.get(blur_type, blur_type),
                'radius': radius,
                'motionAngle': b.get('motionAngle'),
                'center': b.get('center'),
                'saturation': b.get('saturation'),
            }
            if blur_type == 3:
                item['css'] = f'backdrop-filter: blur({radius}px)'
            elif blur_type == 0:
                item['css'] = f'filter: blur({radius}px)'
            blurs.append(item)
        if blurs:
            out['blurs'] = blurs
    blend = st.get('blendMode')
    if blend is not None and blend != 0:
        out['blendMode'] = blend
    return out


def text_to_dict(node):
    """文本图层的字体信息。"""
    txt = node.get('text') or {}
    style = txt.get('style') or {}
    font = style.get('font') or {}
    return {
        'content': style.get('content'),
        'font': font.get('name'),
        'postScriptName': font.get('postScriptName'),
        'fontType': font.get('type'),
        'size': font.get('size'),
        'align': font.get('align'),
        'letterSpacing': font.get('letterSpacing'),
        'lineHeight': font.get('lineHeight'),
        'lineSpacing': font.get('lineSpacing'),
        'fontWeight': font.get('fontWeight'),
        'verticalAlignment': font.get('verticalAlignment'),
        'underline': font.get('underline'),
        'linethrough': font.get('linethrough'),
        'color': css_color(style.get('color') or font.get('color')),
    }


def walk(node, depth=0, pointer='/artboard', seen_ids=None):
    """递归提取节点（本地回退引擎）。

    与上游 normalize 对齐：每个节点都带稳定 `node_id`——
    优先源 `id`/`objectID`；源无 id 或 id 重复时降级为 `source-path:<sha256(pointer)[:16]>`，
    永不用 name 当身份。
    """
    if seen_ids is None:
        seen_ids = set()
    fr = node.get('frame') or {}
    tf = node.get('transform')
    rotation_deg = _rotation_deg(tf) if tf else 0

    source_id = None
    for key in ('id', 'objectID', 'do_objectID'):
        if node.get(key) is not None:
            source_id = str(node[key])
            break
    digest = hashlib.sha256(pointer.encode('utf-8')).hexdigest()[:16]
    if source_id is None:
        node_id = f'source-path:{digest}'
    elif source_id in seen_ids:
        node_id = f'{source_id}:source-path:{digest}'
    else:
        node_id = source_id
    while node_id in seen_ids:
        node_id += ':generated'
    seen_ids.add(node_id)

    frame = _round_frame(fr)
    item = {
        'name': node.get('name'),
        'type': node.get('type'),
        'node_id': node_id,
        'frame': frame,
        'depth': depth,
    }
    # 与上游引擎一致：默认值与等价字段不写盘
    if source_id is not None and str(source_id) != str(node_id):
        item['source_id'] = source_id
        item['identity_source'] = 'source_pointer'
    if node.get('visible', True) is False:
        item['visible'] = False
    if node.get('opacity', 1) != 1:
        item['opacity'] = node['opacity']
    if node.get('rotation', 0):
        item['rotation'] = node['rotation']
    if rotation_deg:
        item['rotationDeg'] = rotation_deg
        if tf:
            item['transform'] = tf
    if node.get('sharedStyle') is not None:
        item['sharedStyle'] = node['sharedStyle']
    st = node.get('style')
    if st:
        interpreted = style_to_css(st, node)
        if not _style_is_trivial(interpreted):
            item['style'] = interpreted
    if node.get('type') in ('textLayer', 'text'):
        item['text'] = text_to_dict(node)
    children = node.get('layers') or []
    if children:
        item['children'] = [
            walk(ch, depth + 1, f'{pointer}/layers/{i}', seen_ids)
            for i, ch in enumerate(children) if ch.get('visible', True)
        ]
    return item


# ---------------------------------------------------------------------------
# 上游 lanhu_design.normalize 取数路径（优先）
#
# 本 skill 的取数层复用上游实现，白拿四样东西：
#   1. 稳定 node_id（源 id / duplicate 时降级 pointer 哈希，永不拿名字当身份）
#   2. 坐标归一化（Figma 混合原点：artboard 绝对坐标 vs 子层本地坐标）+ verified 标记
#   3. 三种源格式（sketch 扁平 info[] / figma artboard / photoshop board）
#   4. gaps[] 诊断 + 素材变体（区分 designer export 与 render fallback）
# 解释层仍是本 skill 自己的 style_to_css / text_to_dict，产出形状不变。
# ---------------------------------------------------------------------------

STRUCTURAL_KEYS = {
    "id", "objectID", "do_objectID", "name", "type", "ddsType", "layerType",
    "layers", "children", "parentID", "parentId", "parent_id",
    "image", "ddsImage", "images",
}


def _rotation_deg(transform):
    """从 2x2 线性部分推导旋转角度（θ=atan2(b,a)）。"""
    if not transform or len(transform) < 2 or len(transform[0]) < 2:
        return 0
    return round(math.degrees(math.atan2(transform[0][1], transform[0][0])))


def _round_frame(fr):
    def r(v):
        v = round(v or 0, 2)
        return 0.0 if v == 0 else v  # 消掉 -0.0
    return {
        'left': r(fr.get('left')),
        'top': r(fr.get('top')),
        'width': r(fr.get('width')),
        'height': r(fr.get('height')),
    }


def _style_is_trivial(style):
    """只有 isEnabled/opacity 默认值的 style 不写盘（节点缺 style 等价于空样式）。"""
    if not style:
        return True
    keys = set(style)
    return keys <= {'isEnabled', 'opacity'} and style.get('opacity', 1) == 1 and style.get('isEnabled', True)


def _node_from_normalized(node, depth):
    """把上游归一化节点翻译成本 skill 的图层节点形状（解释逻辑不变）。

    默认值一律省略（visible=true / opacity=1 / rotation=0 / sharedStyle=null /
    source_id==node_id / source_frame==frame / 空 asset_ids）：等价信息不重复写，
    单页可省下约一半 token，同时保持「缺字段=取默认值」的读法。
    """
    raw = node.get('raw_style') or {}
    bounds = node.get('bounds') or {}
    source = node.get('source_bounds') or bounds
    frame = _round_frame({
        'left': bounds.get('x', 0), 'top': bounds.get('y', 0),
        'width': bounds.get('width', 0), 'height': bounds.get('height', 0),
    })
    source_frame = _round_frame({
        'left': source.get('x', 0), 'top': source.get('y', 0),
        'width': source.get('width', 0), 'height': source.get('height', 0),
    })
    rotation_deg = _rotation_deg(raw.get('transform'))
    node_id = node.get('node_id')
    source_id = node.get('source_id')
    item = {
        'name': node.get('name'),
        'type': node.get('node_type'),
        'node_id': node_id,
        'frame': frame,
        'depth': depth,
    }
    if source_id is not None and str(source_id) != str(node_id):
        item['source_id'] = source_id
        item['identity_source'] = node.get('identity_source')
    elif node.get('identity_source') not in (None, 'source_id'):
        item['identity_source'] = node.get('identity_source')
    if source_frame != frame:
        item['source_frame'] = source_frame
    mode = node.get('bounds_coordinate_mode')
    if mode not in (None, 'source', 'local', 'canvas_origin'):
        item['bounds_coordinate_mode'] = mode
    if node.get('source_visible') is False:
        item['visible'] = False
    if raw.get('opacity', 1) != 1:
        item['opacity'] = raw['opacity']
    if raw.get('rotation', 0):
        item['rotation'] = raw['rotation']
    if rotation_deg:
        item['rotationDeg'] = rotation_deg
        if raw.get('transform'):
            item['transform'] = raw['transform']
    if raw.get('sharedStyle') is not None:
        item['sharedStyle'] = raw['sharedStyle']
    if node.get('asset_ids'):
        item['asset_ids'] = node['asset_ids']

    st = raw.get('style')
    if st:
        interpreted = style_to_css(st, raw)
        if not _style_is_trivial(interpreted):
            item['style'] = interpreted
    if raw.get('text'):
        item['text'] = text_to_dict(raw)
    return item


def build_tree_from_normalized(norm):
    """把 normalize_design() 输出重建为单根图层树。返回 (tree, stats)。"""
    nodes = norm.get('nodes') or []
    by_id = {n['node_id']: n for n in nodes}
    children_of = {}
    for n in nodes:
        children_of.setdefault(n.get('parent_id'), []).append(n)
    for siblings in children_of.values():
        siblings.sort(key=lambda x: x.get('source_order', 0))

    stats = {'node_count': len(nodes), 'hidden_dropped': 0, 'extra_roots': 0}

    def build(n, depth):
        kids = []
        for child in children_of.get(n['node_id'], []):
            if child.get('source_visible') is False:
                stats['hidden_dropped'] += count_subtree(child)
                continue
            kids.append(build(child, depth + 1))
        item = _node_from_normalized(n, depth)
        if kids:
            item['children'] = kids
        return item

    def count_subtree(n):
        total = 1
        for child in children_of.get(n['node_id'], []):
            total += count_subtree(child)
        return total

    canvas = norm.get('canvas') or {}
    roots = children_of.get(None, [])
    root = None
    for candidate in roots:
        b = candidate.get('bounds') or {}
        if (candidate.get('node_type') in ('artboard', 'artboardSection')
                and abs((b.get('width') or 0) - (canvas.get('width') or 0)) < 1
                and abs((b.get('height') or 0) - (canvas.get('height') or 0)) < 1):
            root = candidate
            break
    if root is None and roots:
        root = max(roots, key=lambda n: ((n.get('bounds') or {}).get('width') or 0)
                   * ((n.get('bounds') or {}).get('height') or 0))
    if root is None:
        raise ValueError('normalize 结果里找不到画板根节点')

    tree = build(root, 0)
    # 其余根节点挂到画板下，避免丢内容
    for other in roots:
        if other is root:
            continue
        stats['extra_roots'] += 1
        tree.setdefault('children', []).append(build(other, 1))
    return tree, stats


def _gaps_summary(gaps):
    summary = {}
    for g in gaps or []:
        code = g.get('code')
        summary[code] = summary.get(code, 0) + 1
    return summary


# 这两种是已知行为，逐条写盘会把单页 token 翻倍，只保留计数
ROUTINE_GAP_CODES = {'transform_preserved_not_applied', 'nonzero_canvas_origin_normalized'}


def _trim_gaps(gaps, per_code=20):
    """按 code 分组保留少量样本；例行 code 只留计数（在 gaps_summary 里）。"""
    kept = {}
    for g in gaps or []:
        code = g.get('code')
        if code in ROUTINE_GAP_CODES:
            continue
        bucket = kept.setdefault(code, [])
        if len(bucket) < per_code:
            bucket.append(g)
    return kept


def _assets_projection(assets):
    """素材投影：只留「是设计师导出还是渲染兜底」相关的字段。"""
    out = []
    for a in assets or []:
        variants = []
        for v in a.get('variants') or []:
            variants.append({
                'format': v.get('format_hint') or v.get('format'),
                'url': v.get('url'),
            })
        out.append({
            'asset_id': a.get('asset_id'),
            'node_id': a.get('node_id'),
            'kind': a.get('kind'),
            'source_field': a.get('source_field'),
            'format_hint': a.get('format_hint'),
            'render_bounds': a.get('render_bounds'),
            'variants': variants,
        })
    return out


def load_upstream_normalizer():
    """上游 normalize_design；未安装（skill 单独分发）时返回 None。"""
    try:
        from lanhu_design.normalize import normalize_design  # type: ignore
    except ModuleNotFoundError:
        return None
    return normalize_design


def extract_layers_from_sketch(sketch_data):
    """从已加载的设计 JSON 提取结构化图层树。

    优先走上游 normalize（稳定 ID / 坐标归一 / 三格式 / 诊断），
    上游包不可用时回退到本地 walk（行为与历史版本一致）。
    """
    normalize = load_upstream_normalizer()
    if normalize is not None:
        norm = normalize(sketch_data)
        tree, stats = build_tree_from_normalized(norm)
        tree['_meta'] = {
            'engine': 'upstream_normalize',
            'schema_version': norm.get('schema_version'),
            'source_type': norm.get('source_type'),
            'canvas': norm.get('canvas'),
            'canvas_origin': norm.get('canvas_origin'),
            'coordinate_mapping': norm.get('coordinate_mapping'),
            'gaps': _trim_gaps(norm.get('gaps')),
            'gaps_summary': _gaps_summary(norm.get('gaps')),
            'assets': _assets_projection(norm.get('assets')),
            'node_count': stats['node_count'],
            'hidden_dropped': stats['hidden_dropped'],
            'extra_roots': stats['extra_roots'],
        }
        return tree

    artboard = sketch_data.get('artboard') or sketch_data.get('board')
    if artboard is None:
        raise ValueError('既非上游可识别的格式，也没有 artboard/board 节点，无法提取')
    tree = walk(artboard)
    tree['_meta'] = {
        'engine': 'legacy_walk',
        'source_type': 'unknown',
        'gaps': [],
        'gaps_summary': {},
        'assets': [],
        'node_count': _count_nodes(tree),
    }
    return tree


def _count_nodes(tree):
    return 1 + sum(_count_nodes(c) for c in tree.get('children') or [])


def extract_layers(sketch_path, out_path):
    """从 sketch.json 文件提取并保存到 out_path。返回节点总数。

    若同目录存在 sketch.meta.json（fetch_sketch 写入的版本信息），
    把版本号与原文哈希并进 _meta，保证「同一条命令跑两次」可追溯是稿子变了还是代码变了。
    """
    with open(sketch_path, encoding='utf-8') as f:
        sk = json.load(f)
    tree = extract_layers_from_sketch(sk)
    meta = tree.setdefault('_meta', {})
    sidecar = Path(sketch_path).with_name('sketch.meta.json')
    if sidecar.is_file():
        try:
            meta['source_version'] = json.loads(sidecar.read_text(encoding='utf-8'))
        except Exception as exc:  # 版本信息只做追溯，坏了不阻塞提取
            meta['source_version_error'] = str(exc)
    with open(out_path, 'w', encoding='utf-8') as f:
        # 紧凑输出：整份要喂给模型读，缩进纯属浪费（实测单页省 39% token）
        json.dump(tree, f, ensure_ascii=False, separators=(',', ':'))

    def count(n):
        return 1 + sum(count(c) for c in n.get('children', []))
    return count(tree)


def main():
    """兼容旧的命令行入口。新脚本建议直接调用 extract_layers()。"""
    import sys
    if len(sys.argv) < 3:
        print('用法: python extract_layers.py <sketch.json> <out.json>')
        sys.exit(2)
    src, dst = sys.argv[1], sys.argv[2]
    total = extract_layers(src, dst)
    print(f'节点总数: {total}')
    print(f'已输出: {dst}')


if __name__ == '__main__':
    main()
