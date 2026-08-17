"""从 sketch 图层树分析容器内部间距（padding / margin / gap）。"""
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

TOLERANCE = 2  # px，认为同一 padding/margin 的容差
MIN_CLUSTER_RATIO = 0.5  # 超过一半子元素贴某边时，视为父容器 padding


def load_json(path: str) -> dict:
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def find_node(root: dict, name: str) -> Optional[dict]:
    if root.get('name') == name:
        return root
    for c in root.get('children', []):
        n = find_node(c, name)
        if n:
            return n
    return None


def find_nodes_by_name(root: dict, name: str) -> List[dict]:
    """按完整 name 匹配所有节点（含自身）。"""
    out = []
    if root.get('name') == name:
        out.append(root)
    for c in root.get('children', []):
        out.extend(find_nodes_by_name(c, name))
    return out


def find_container_candidates(root: dict, prefix: str = '') -> List[dict]:
    """返回可能是容器的节点：有子元素且自身有面积。"""
    out = []
    children = root.get('children', [])
    frame = root.get('frame', {})
    width = frame.get('width', 0)
    height = frame.get('height', 0)
    if children and width > 0 and height > 0:
        if not prefix or prefix in (root.get('name') or ''):
            out.append(root)
    for c in children:
        out.extend(find_container_candidates(c, prefix))
    return out


def _edge_values(children: List[dict], container_frame: dict) -> Dict[str, List[Tuple[float, str, dict]]]:
    """计算每个子元素相对容器四边的距离。"""
    cl = container_frame.get('left', 0)
    ct = container_frame.get('top', 0)
    cw = container_frame.get('width', 0)
    ch = container_frame.get('height', 0)
    cr = cl + cw
    cb = ct + ch

    edges = {'left': [], 'right': [], 'top': [], 'bottom': []}
    for c in children:
        if not c.get('visible', True):
            continue
        fr = c.get('frame', {})
        l = fr.get('left', 0)
        t = fr.get('top', 0)
        w = fr.get('width', 0)
        h = fr.get('height', 0)
        name = c.get('name', '')
        edges['left'].append((round(l - cl, 2), name, c))
        edges['right'].append((round(cr - (l + w), 2), name, c))
        edges['top'].append((round(t - ct, 2), name, c))
        edges['bottom'].append((round(cb - (t + h), 2), name, c))
    return edges


def _cluster_values(values: List[Tuple[float, str, dict]]) -> List[Dict[str, Any]]:
    """将边缘距离值聚类，返回 [{value, count, children}]，按 count 降序。"""
    if not values:
        return []
    sorted_vals = sorted(values, key=lambda x: x[0])
    clusters = []
    current = [sorted_vals[0]]
    for v in sorted_vals[1:]:
        if abs(v[0] - current[0][0]) <= TOLERANCE:
            current.append(v)
        else:
            clusters.append(current)
            current = [v]
    clusters.append(current)

    result = []
    for cluster in clusters:
        avg = round(sum(v[0] for v in cluster) / len(cluster), 2)
        result.append({
            'value': avg,
            'count': len(cluster),
            'children': [{'name': v[1], 'value': v[0]} for v in cluster],
        })
    result.sort(key=lambda x: (-x['count'], x['value']))
    return result


def _sibling_gaps(children: List[dict], axis: str = 'x') -> List[Dict[str, Any]]:
    """计算相邻子元素在 x 或 y 轴上的间距。"""
    visible = [c for c in children if c.get('visible', True)]
    if len(visible) < 2:
        return []
    items = []
    for c in visible:
        fr = c.get('frame', {})
        if axis == 'x':
            items.append({
                'name': c.get('name', ''),
                'start': fr.get('left', 0),
                'end': fr.get('left', 0) + fr.get('width', 0),
            })
        else:
            items.append({
                'name': c.get('name', ''),
                'start': fr.get('top', 0),
                'end': fr.get('top', 0) + fr.get('height', 0),
            })
    items.sort(key=lambda x: x['start'])
    gaps = []
    for i in range(len(items) - 1):
        gap = round(items[i + 1]['start'] - items[i]['end'], 2)
        gaps.append({
            'between': [items[i]['name'], items[i + 1]['name']],
            'gap': gap,
        })
    return gaps


def analyze_container(node: dict) -> Dict[str, Any]:
    """分析单个容器的 padding / margin / gap。"""
    frame = node.get('frame', {})
    children = [c for c in node.get('children', []) if c.get('visible', True)]
    if not children:
        return {
            'name': node.get('name'),
            'frame': frame,
            'error': '无可见子元素',
        }

    edges = _edge_values(children, frame)
    padding = {}
    deviations = {}
    for edge in ('left', 'right', 'top', 'bottom'):
        clusters = _cluster_values(edges[edge])
        if not clusters:
            padding[edge] = 0
            deviations[edge] = []
            continue
        # 最大簇作为父容器 padding；其余为子元素 margin
        main = clusters[0]
        padding[edge] = main['value']
        if main['count'] >= len(children) * MIN_CLUSTER_RATIO:
            deviations[edge] = [
                {'name': c['name'], 'value': c['value'], 'diff': round(c['value'] - main['value'], 2)}
                for cluster in clusters[1:]
                for c in cluster['children']
            ]
        else:
            # 没有明显多数，认为没有统一 padding，全部记为子元素 margin
            deviations[edge] = [
                {'name': c['name'], 'value': c['value'], 'diff': round(c['value'] - main['value'], 2)}
                for cluster in clusters
                for c in cluster['children']
            ]
            padding[edge] = 0

    return {
        'name': node.get('name'),
        'type': node.get('type'),
        'frame': frame,
        'child_count': len(children),
        'padding': padding,
        'deviations': deviations,
        'horizontal_gaps': _sibling_gaps(children, axis='x'),
        'vertical_gaps': _sibling_gaps(children, axis='y'),
    }


def check_container(layers_path: str, container_name: str) -> Dict[str, Any]:
    """分析指定容器。"""
    tree = load_json(layers_path)
    node = find_node(tree, container_name)
    if not node:
        return {
            'status': 'error',
            'message': f'未找到容器: {container_name}',
        }
    return {
        'status': 'success',
        'source': layers_path,
        'container': analyze_container(node),
    }


def check_all_containers(layers_path: str, prefix: str = '') -> Dict[str, Any]:
    """分析所有容器候选。"""
    tree = load_json(layers_path)
    candidates = find_container_candidates(tree, prefix)
    if not candidates:
        return {
            'status': 'error',
            'message': '未找到容器候选',
        }
    return {
        'status': 'success',
        'source': layers_path,
        'containers': [analyze_container(n) for n in candidates],
    }


def compare_containers(layers_paths: List[str], container_name: str) -> Dict[str, Any]:
    """跨多个页面比较同名容器。"""
    pages = []
    def frame_dist(ref, cand):
        rfr = ref.get('frame', {})
        cfr = cand.get('frame', {})
        dw = abs(rfr.get('width', 0) - cfr.get('width', 0))
        dh = abs(rfr.get('height', 0) - cfr.get('height', 0))
        return dw + dh

    for idx, p in enumerate(layers_paths):
        tree = load_json(p)
        nodes = find_nodes_by_name(tree, container_name)
        if not nodes:
            pages.append({'source': p, 'found': False})
            continue
        # 跨页对比时优先匹配与参考容器 frame 最接近的节点，避免同名不同容器导致噪声
        if idx == 0 or not pages or not pages[-1].get('container'):
            chosen = nodes[0]
        else:
            ref = pages[0]['container']
            chosen = min(nodes, key=lambda n: frame_dist(ref, n))
        pages.append({
            'source': p,
            'found': True,
            'note': f'找到 {len(nodes)} 个同名节点，使用与参考容器 frame 最接近的做对比',
            'container': analyze_container(chosen),
        })

    found = [p for p in pages if p['found']]
    if not found:
        return {
            'status': 'error',
            'message': f'在 {len(layers_paths)} 个文件中均未找到容器: {container_name}',
        }

    # 提取所有容器的 frame / padding 做差异汇总
    frames = []
    paddings = []
    for p in found:
        c = p['container']
        frames.append({
            'source': p['source'],
            'name': c['name'],
            'frame': c['frame'],
        })
        paddings.append({
            'source': p['source'],
            'name': c['name'],
            'padding': c['padding'],
            'deviations': c['deviations'],
        })

    # 简单差异检测：frame width/height 或 padding 任意维度不同即 flagged
    flagged = []
    if len(frames) > 1:
        first_frame = frames[0]['frame']
        for f in frames[1:]:
            fr = f['frame']
            if (abs(fr.get('width', 0) - first_frame.get('width', 0)) > TOLERANCE or
                    abs(fr.get('height', 0) - first_frame.get('height', 0)) > TOLERANCE):
                flagged.append({
                    'type': 'frame_size',
                    'message': f"尺寸不一致: {frames[0]['source']} vs {f['source']}",
                    'values': [
                        {'source': frames[0]['source'], 'frame': first_frame},
                        {'source': f['source'], 'frame': fr},
                    ],
                })
    if len(paddings) > 1:
        first_pad = paddings[0]['padding']
        for p in paddings[1:]:
            pad = p['padding']
            for edge in ('left', 'right', 'top', 'bottom'):
                if abs(pad.get(edge, 0) - first_pad.get(edge, 0)) > TOLERANCE:
                    flagged.append({
                        'type': 'padding',
                        'edge': edge,
                        'message': f"{edge} padding 不一致: {paddings[0]['source']} vs {p['source']}",
                        'values': [
                            {'source': paddings[0]['source'], 'padding': first_pad},
                            {'source': p['source'], 'padding': pad},
                            ],
                    })
                    break

    return {
        'status': 'success',
        'container_name': container_name,
        'pages': pages,
        'summary': {
            'total_files': len(layers_paths),
            'found_files': len(found),
            'flagged': flagged,
        },
    }


def main():
    import sys
    if len(sys.argv) < 2:
        print('用法:')
        print('  python check_spacing.py <layers.json> [容器名]')
        print('  python check_spacing.py --compare <layers1.json> <layers2.json> ... --name <容器名>')
        sys.exit(2)
    args = sys.argv[1:]
    if args[0] == '--compare':
        paths = []
        name = None
        i = 1
        while i < len(args):
            if args[i] == '--name':
                name = args[i + 1]
                i += 2
            else:
                paths.append(args[i])
                i += 1
        if not name or len(paths) < 2:
            print('--compare 需要至少两个 layers.json 和 --name 容器名')
            sys.exit(2)
        result = compare_containers(paths, name)
    else:
        layers_path = args[0]
        container_name = args[1] if len(args) > 1 else None
        if container_name:
            result = check_container(layers_path, container_name)
        else:
            result = check_all_containers(layers_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get('status') == 'success' else 1)


if __name__ == '__main__':
    main()
