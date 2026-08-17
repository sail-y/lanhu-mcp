"""从蓝湖 sketch_json 深度提取结构化图层树。"""
import json
import math


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
        borders.append({'thickness': b.get('thickness'),
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


def walk(node, depth=0):
    """递归提取节点。"""
    fr = node.get('frame') or {}
    tf = node.get('transform')
    rotation_deg = 0
    if tf and len(tf) >= 2 and len(tf[0]) >= 2:
        rotation_deg = round(math.degrees(math.atan2(tf[0][1], tf[0][0])))
    item = {
        'name': node.get('name'),
        'type': node.get('type'),
        'frame': {
            'left': round(fr.get('left', 0), 2),
            'top': round(fr.get('top', 0), 2),
            'width': round(fr.get('width', 0), 2),
            'height': round(fr.get('height', 0), 2),
        },
        'visible': node.get('visible', True),
        'opacity': node.get('opacity', 1),
        'rotation': node.get('rotation', 0),
        'rotationDeg': rotation_deg,
        'transform': tf,
        'sharedStyle': node.get('sharedStyle'),
        'depth': depth,
    }
    st = node.get('style')
    if st:
        item['style'] = style_to_css(st, node)
    if node.get('type') in ('textLayer', 'text'):
        item['text'] = text_to_dict(node)
    children = node.get('layers') or []
    if children:
        item['children'] = [walk(ch, depth + 1) for ch in children if ch.get('visible', True)]
    return item


def extract_layers_from_sketch(sketch_data):
    """从已加载的 sketch 字典提取结构化图层树。"""
    return walk(sketch_data['artboard'])


def extract_layers(sketch_path, out_path):
    """从 sketch.json 文件提取并保存到 out_path。返回节点总数。"""
    with open(sketch_path, encoding='utf-8') as f:
        sk = json.load(f)
    tree = extract_layers_from_sketch(sk)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(tree, f, ensure_ascii=False, indent=1)

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
