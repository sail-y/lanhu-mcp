"""根据 sketch 图层树分析容器布局意图（居中 / 固定左偏移 / 全宽）。"""
import json
from pathlib import Path
from typing import Optional

TOLERANCE = 24  # 左右留白差异 <= 24px 时视为可居中
MIN_MARGIN = 20  # 一边留白 < 20px 时视为贴近边缘


def load_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def find_node(root, name: Optional[str]):
    """按 name 查找节点；name 为空则返回 root。"""
    if not name:
        return root
    if root.get('name') == name:
        return root
    for c in root.get('children', []):
        n = find_node(c, name)
        if n:
            return n
    return None


def find_artboard(node):
    """向上（这里只有根）或直接取 artboard 节点。"""
    if node.get('type') == 'artboard':
        return node
    # 假设 root 是 artboard
    return node


def analyze_layout_dict(layers_tree: dict, container_name: Optional[str] = None) -> dict:
    """对内存中的 layers 树分析布局。返回包含 margins / intent / css 建议的字典。"""
    artboard = find_artboard(layers_tree)
    ab = artboard.get('frame', {})
    ab_w = ab.get('width', 0)
    ab_h = ab.get('height', 0)

    container = find_node(layers_tree, container_name)
    if not container:
        return {
            'status': 'error',
            'message': f'未找到容器: {container_name}',
            'artboard': {'width': ab_w, 'height': ab_h},
        }

    fr = container.get('frame', {})
    left = fr.get('left', 0)
    top = fr.get('top', 0)
    width = fr.get('width', 0)
    height = fr.get('height', 0)

    right = ab_w - left - width

    # 决策
    if width >= ab_w - 2 * MIN_MARGIN:
        intent = 'full-width'
        css_recommendation = 'width: 100%; padding-left: {left}px; padding-right: {right}px;'
    elif abs(left - right) <= TOLERANCE:
        intent = 'center'
        css_recommendation = 'max-width: {width}px; margin: 0 auto;'
    else:
        intent = 'fixed-left'
        css_recommendation = 'margin-left: {left}px; width: {width}px;'

    return {
        'status': 'success',
        'artboard': {'width': ab_w, 'height': ab_h},
        'container': {
            'layer_id': container.get('name'),
            'type': container.get('type'),
            'left': left,
            'top': top,
            'width': width,
            'height': height,
        },
        'margins': {
            'left': left,
            'right': right,
            'top': top,
        },
        'intent': intent,
        'css_recommendation': css_recommendation.format(left=left, right=right, width=width),
    }


def analyze_layout(layers_path: str, container_name: Optional[str] = None) -> dict:
    """从文件路径分析布局。"""
    tree = load_json(layers_path)
    return analyze_layout_dict(tree, container_name)


def main():
    import sys
    if len(sys.argv) < 2:
        print('用法: python layout_analyzer.py <layers.json> [container_name]')
        sys.exit(2)
    layers_path = sys.argv[1]
    container_name = sys.argv[2] if len(sys.argv) > 2 else None
    result = analyze_layout(layers_path, container_name)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get('status') == 'success' else 1)


if __name__ == '__main__':
    main()
