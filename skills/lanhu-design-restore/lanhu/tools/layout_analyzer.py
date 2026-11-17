"""根据 sketch 图层树分析容器布局意图（居中 / 固定左偏移 / 全宽）。"""
import json
from pathlib import Path
from typing import Optional

TOLERANCE = 24  # 左右留白差异 <= 24px 时视为可居中
MIN_MARGIN = 20  # 一边留白 < 20px 时视为贴近边缘
COORD_EPS = 0.5  # 原点噪声容差：小于该量级的负值视为 0，不当作「绝对坐标」
OFFBOARD_TOL = 1.0  # 判断越界时的像素容差


def load_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def find_node(root, name: Optional[str]):
    """按 node_id 优先、其次按 name 查找节点；name 为空则返回 root。"""
    if not name:
        return root
    by_id = _find_by_id(root, name)
    if by_id is not None:
        return by_id
    if root.get('name') == name:
        return root
    for c in root.get('children', []):
        n = find_node(c, name)
        if n:
            return n
    return None


def _find_by_id(root, node_id):
    if node_id and root.get('node_id') == node_id:
        return root
    for c in root.get('children', []):
        n = _find_by_id(c, node_id)
        if n:
            return n
    return None


def find_artboard(node):
    """向上（这里只有根）或直接取 artboard 节点。"""
    if node.get('type') == 'artboard':
        return node
    # 假设 root 是 artboard
    return node


def detect_coordinate_space(artboard) -> dict:
    """判断画板内图层的 frame 是「画板本地坐标」还是「页面绝对坐标」。

    做法：按两种假设分别统计采样容器的越界像素，取越界更少的一种。
    不依赖单个节点的符号判断——浮点噪声（如 left=-0.000244）不会被误判成绝对坐标。

    返回 {'space': 'local'|'absolute', 'dx': float, 'dy': float, 'evidence': {...}}
    其中 dx/dy 是「需要从 frame 减掉的偏移量」，本地坐标时为 0。
    """
    ab = artboard.get('frame') or {}
    ab_w = ab.get('width') or 0
    ab_h = ab.get('height') or 0
    ab_left = ab.get('left') or 0
    ab_top = ab.get('top') or 0

    # 画板原点本身就在 0 附近 -> 两种假设等价，直接用本地坐标
    if abs(ab_left) <= COORD_EPS and abs(ab_top) <= COORD_EPS:
        return {'space': 'local', 'dx': 0, 'dy': 0,
                'evidence': {'artboard_origin': [ab_left, ab_top], 'reason': 'origin_at_zero'}}
    if ab_w <= 0 or ab_h <= 0:
        return {'space': 'local', 'dx': 0, 'dy': 0,
                'evidence': {'artboard_origin': [ab_left, ab_top], 'reason': 'canvas_size_unknown'}}

    # 采样前 3 层容器（最多 200 个），代表整页布局
    sample = []

    def collect(node, depth):
        if depth > 3 or len(sample) >= 200:
            return
        for child in node.get('children') or []:
            sample.append(child)
            collect(child, depth + 1)

    collect(artboard, 0)
    if not sample:
        return {'space': 'local', 'dx': 0, 'dy': 0,
                'evidence': {'artboard_origin': [ab_left, ab_top], 'reason': 'no_children'}}

    def violations(dx, dy):
        bad = 0
        overflow = 0.0
        for n in sample:
            fr = n.get('frame') or {}
            left, top = fr.get('left'), fr.get('top')
            width, height = fr.get('width'), fr.get('height')
            if None in (left, top, width, height):
                continue
            l = left - dx
            t = top - dy
            over = max(0.0, -l, l + width - ab_w) + max(0.0, -t, t + height - ab_h)
            if over > OFFBOARD_TOL:
                bad += 1
                overflow += over
        return bad, overflow

    v_local = violations(0, 0)
    v_abs = violations(ab_left, ab_top)
    evidence = {
        'artboard_origin': [ab_left, ab_top],
        'sampled': len(sample),
        'local_violations': {'nodes': v_local[0], 'overflow_px': round(v_local[1], 1)},
        'absolute_violations': {'nodes': v_abs[0], 'overflow_px': round(v_abs[1], 1)},
    }
    # 绝对坐标只有在「明显更少越界」时才采用，避免骑墙时来回摇摆
    if v_abs[0] < v_local[0] - 1 or (v_abs[0] <= v_local[0] and v_abs[1] < v_local[1] * 0.5):
        evidence['reason'] = 'children_fit_absolute_space_better'
        return {'space': 'absolute', 'dx': ab_left, 'dy': ab_top, 'evidence': evidence}
    evidence['reason'] = 'children_fit_local_space_better' if v_local[0] <= v_abs[0] else 'ambiguous_default_local'
    return {'space': 'local', 'dx': 0, 'dy': 0, 'evidence': evidence}


def analyze_layout_dict(layers_tree: dict, container_name: Optional[str] = None) -> dict:
    """对内存中的 layers 树分析布局。返回包含 margins / intent / css 建议的字典。"""
    artboard = find_artboard(layers_tree)
    ab = artboard.get('frame', {})
    ab_w = ab.get('width', 0)
    ab_h = ab.get('height', 0)
    # artboard frame 在页面坐标系里可能带负原点（如 (-1863,-1691)），
    # 而图层 frame 通常已是画板内相对坐标；留白必须按画板本地空间计算。
    # 若 layers.json 由上游 normalize 产出，坐标已被归一化并有 verified 标记，直接采信。
    upstream_cm = (layers_tree.get('_meta') or {}).get('coordinate_mapping')
    if upstream_cm:
        space = {
            'space': 'upstream_normalized',
            'dx': 0, 'dy': 0,
            'evidence': {
                'source': 'lanhu_design.normalize',
                'verified': upstream_cm.get('verified'),
                'strategy': upstream_cm.get('strategy'),
            },
        }
    else:
        space = detect_coordinate_space(artboard)
    dx, dy = space['dx'], space['dy']

    container = find_node(layers_tree, container_name)
    if not container:
        return {
            'status': 'error',
            'message': f'未找到容器: {container_name}',
            'artboard': {'width': ab_w, 'height': ab_h},
            'coordinate_space': space,
        }

    if container is artboard:
        return {
            'status': 'success',
            'artboard': {'width': ab_w, 'height': ab_h},
            'container': {'layer_id': container.get('name'), 'node_id': container.get('node_id'),
                          'type': container.get('type'),
                          'left': 0, 'top': 0, 'width': ab_w, 'height': ab_h},
            'margins': {'left': 0, 'right': 0, 'top': 0},
            'intent': 'artboard-root',
            'coordinate_space': space,
            'css_recommendation': '目标即画板自身；请传入具体容器名分析其版心策略。',
        }

    fr = container.get('frame', {})
    left = fr.get('left', 0) - dx
    top = fr.get('top', 0) - dy
    width = fr.get('width', 0)
    height = fr.get('height', 0)
    # 单个节点仍可能落在另一种坐标系里：仅当按全局假设明显越界、而换成另一种
    # 假设后能落回画板内时，才对这一个节点改用另一种假设。
    if space['space'] == 'local' and left < -OFFBOARD_TOL and max(abs(dx), abs(dy)) < COORD_EPS:
        ab_left = ab.get('left', 0)
        if -COORD_EPS <= left - ab_left and left - ab_left + width <= ab_w + OFFBOARD_TOL:
            left -= ab_left
    elif space['space'] == 'absolute' and left + width > ab_w + OFFBOARD_TOL:
        if -COORD_EPS <= fr.get('left', 0) and fr.get('left', 0) + width <= ab_w + OFFBOARD_TOL:
            left = fr.get('left', 0)

    right = ab_w - left - width

    def clean(v):
        """把浮点噪声（±0.000244 这类）归零，并保留两位小数。"""
        v = float(v)
        return 0.0 if abs(v) < COORD_EPS else round(v, 2)

    left, top, right = clean(left), clean(top), clean(right)
    width, height = clean(width), clean(height)

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
            'node_id': container.get('node_id'),
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
        'coordinate_space': space,
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
