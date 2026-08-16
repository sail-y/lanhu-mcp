"""把 layers.json 转成前端可用的页面规格摘要（布局/卡片/输入/按钮/开关/图标/字体）。

可被 MCP 工具与 CLI 脚本共用。
"""
import json
import re
from pathlib import Path
from typing import Optional

from .layout_analyzer import analyze_layout_dict

IGNORED_NAMES = re.compile(r'^(矩形|路径|div_line|line|shapeLayer|textLayer)\s*\d*$')


def load_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def find_page(root, page_name: Optional[str]):
    """按名称查找页面根节点；page_name 为空则返回 root。"""
    if not page_name or root.get('name') == page_name:
        return root
    for c in root.get('children', []):
        n = find_page(c, page_name)
        if n:
            return n
    return None


def hex_from_rgba_dict(c):
    if not c:
        return None
    r, g, b = c.get('r', 0), c.get('g', 0), c.get('b', 0)
    return f'#{r:02X}{g:02X}{b:02X}'


def css_rgba(c):
    if not c:
        return None
    r, g, b, a = c.get('r', 0), c.get('g', 0), c.get('b', 0), c.get('a', 1)
    return f'rgba({r},{g},{b},{a})'


def first_solid_color(style):
    if not style:
        return None
    for f in (style.get('fills') or []):
        if f.get('type') == 'solid':
            return f.get('color')
    return None


def first_border(style):
    if not style:
        return None
    borders = style.get('borders') or []
    return borders[0] if borders else None


def first_shadow(style):
    if not style:
        return None
    shadows = style.get('shadows') or []
    return shadows[0] if shadows else None


def is_card(node):
    """卡片/面板：大容器带背景或边框或阴影。"""
    fr = node.get('frame', {})
    w, h = fr.get('width', 0), fr.get('height', 0)
    if w < 80 or h < 40:
        return False
    style = node.get('style') or {}
    has_fill = bool(first_solid_color(style))
    has_border = bool(first_border(style))
    has_shadow = bool(first_shadow(style))
    t = node.get('type', '')
    name = node.get('name', '')
    # 容器/面板/卡片
    if '容器' in name or '面板' in name or 'card' in name.lower() or 'panel' in name.lower():
        return has_fill or has_border or has_shadow
    if t == 'artboard' and (has_fill or has_border or has_shadow) and w > 200 and h > 100:
        return True
    return False


def is_input(node):
    name = (node.get('name') or '').lower()
    return any(k in name for k in ['input', 'inputbox', 'select', '选择框', '搜索', 'search', 'dropdown', '下拉'])


def is_button(node):
    name = (node.get('name') or '').lower()
    return any(k in name for k in ['button', 'btn', '按钮', '保存', '提交', '确认', '取消'])


def is_switch(node):
    name = (node.get('name') or '').lower()
    return any(k in name for k in ['switch', 'checkbox', 'toggle', '复选框', '开关'])


def is_icon(node):
    """图标：小尺寸 symbol 或 bitmap，或名字含 icon。"""
    fr = node.get('frame', {})
    w, h = fr.get('width', 0), fr.get('height', 0)
    name = (node.get('name') or '').lower()
    t = node.get('type', '')
    if 'icon' in name or 'loading' in name:
        return True
    if t in ('symbolInstence', 'symbolInstance', 'bitmap') and w <= 64 and h <= 64:
        return True
    return False


def walk_all(node, path=None, collector=None):
    if collector is None:
        collector = []
    if path is None:
        path = []
    breadcrumb = path + [node.get('name')]
    collector.append((node, breadcrumb))
    for c in node.get('children', []):
        walk_all(c, breadcrumb, collector)
    return collector


def summarize_node(node, breadcrumb, artboard_width):
    """单个节点摘要。"""
    fr = node.get('frame', {})
    style = node.get('style') or {}
    text = node.get('text') or {}
    item = {
        'layer_id': node.get('name'),
        'type': node.get('type'),
        'path': ' / '.join(breadcrumb),
        'frame': fr,
    }

    fill = first_solid_color(style)
    if fill:
        item['background'] = fill
    border = first_border(style)
    if border:
        item['border'] = border
    shadow = first_shadow(style)
    if shadow:
        item['shadow'] = shadow
    radius = style.get('radius')
    if radius:
        item['radius'] = radius

    if text.get('content'):
        item['text'] = {
            'content': text.get('content'),
            'font': text.get('font'),
            'size': text.get('size'),
            'fontWeight': text.get('fontWeight'),
            'letterSpacing': text.get('letterSpacing'),
            'color': text.get('color'),
        }
        # 相对 artboard 的左侧百分比（用于居中/版心验证）
        item['text']['left_ratio'] = round(fr.get('left', 0) / artboard_width, 3) if artboard_width else 0

    return item


def summarize_page_dict(layers_tree: dict, page_name: Optional[str] = None) -> dict:
    """对内存中的 layers 树生成页面规格。"""
    page = find_page(layers_tree, page_name)
    if not page:
        return {'status': 'error', 'message': f'未找到页面: {page_name}'}

    ab = page.get('frame', {})
    ab_w = ab.get('width', 0)
    ab_h = ab.get('height', 0)

    nodes = walk_all(page)
    all_items = [summarize_node(n, bc, ab_w) for n, bc in nodes]
    cards = []
    inputs = []
    buttons = []
    switches = []
    icons = []
    texts = []
    for n, bc in nodes:
        if is_card(n):
            cards.append(summarize_node(n, bc, ab_w))
        elif is_input(n):
            inputs.append(summarize_node(n, bc, ab_w))
        elif is_button(n):
            buttons.append(summarize_node(n, bc, ab_w))
        elif is_switch(n):
            switches.append(summarize_node(n, bc, ab_w))
        elif is_icon(n):
            icons.append(summarize_node(n, bc, ab_w))
        if n.get('text') and n['text'].get('content'):
            texts.append(summarize_node(n, bc, ab_w))

    # 字体统计：按 font/size/weight/color 分组
    style_groups = {}
    for t in texts:
        txt = t.get('text', {})
        key = (txt.get('font'), txt.get('size'), txt.get('fontWeight'), hex_from_rgba_dict(txt.get('color')))
        style_groups.setdefault(key, []).append(t['text']['content'])

    text_styles = []
    for (font, size, fw, color), contents in sorted(style_groups.items(), key=lambda x: (x[0][1] or 0, x[0][2] or 0)):
        text_styles.append({
            'font': font,
            'size': size,
            'fontWeight': fw,
            'color': color,
            'sample_count': len(contents),
            'samples': contents[:5],
        })

    # 主内容容器推测：最深的 artboard 且宽度接近版心（排除面包屑/标题栏）
    main_container = None
    for n, bc in nodes:
        fr = n.get('frame', {})
        if n.get('type') == 'artboard' and fr.get('width', 0) < ab_w - 200 and fr.get('height', 0) > 200:
            main_container = n
            break

    layout = {
        'artboard': {'width': ab_w, 'height': ab_h},
        'main_container': analyze_layout_dict(page, main_container.get('name') if main_container else None) if main_container else None,
    }
    if not layout['main_container']:
        # 回退：直接用整个 page
        layout['main_container'] = analyze_layout_dict(page, None)

    # 页面背景
    bg = first_solid_color(page.get('style') or {})

    return {
        'status': 'success',
        'page': {
            'name': page.get('name'),
            'type': page.get('type'),
            'width': ab_w,
            'height': ab_h,
            'background': bg,
        },
        'layout': layout,
        'cards': cards,
        'inputs': inputs,
        'buttons': buttons,
        'switches': switches,
        'icons': icons,
        'text_styles': text_styles,
        'total_nodes': len(nodes),
    }


def summarize_page(layers_path: str, page_name: Optional[str] = None) -> dict:
    """从文件路径生成页面规格。"""
    tree = load_json(layers_path)
    return summarize_page_dict(tree, page_name)


def main():
    import sys
    if len(sys.argv) < 2:
        print('用法: python page_summarizer.py <layers.json> [page_name]')
        sys.exit(2)
    layers_path = sys.argv[1]
    page_name = sys.argv[2] if len(sys.argv) > 2 else None
    result = summarize_page(layers_path, page_name)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get('status') == 'success' else 1)


if __name__ == '__main__':
    main()
