"""验证 extract_layers.py 的输出完整性。"""
import json


def walk(n, fn):
    fn(n)
    for c in n.get('children', []):
        walk(c, fn)


def hex_color(c):
    if not c:
        return None
    return f'#{c["r"]:02X}{c["g"]:02X}{c["b"]:02X}'


def verify_layers_dict(layers_tree):
    """对内存中的 layers 树执行验证。返回结果字典。"""
    checks = []

    txts = []
    walk(layers_tree, lambda n: txts.append(n) if n.get('text') and n['text'].get('content') else None)
    no_color = [n for n in txts if not n['text'].get('color')]
    checks.append({'name': '文本 color 缺失数 = 0',
                   'detail': f'{len(no_color)} / {len(txts)} 缺失',
                   'ok': len(no_color) == 0,
                   'extra': [f'"{n.get("name")}"' for n in no_color[:5]]})

    grads = []
    def scan_grad(n):
        for f in (n.get('style') or {}).get('fills') or []:
            if f.get('type') == 'gradient':
                grads.append((n.get('name'), f))
    walk(layers_tree, scan_grad)
    bad_grad = [(nm, f) for nm, f in grads
                if f.get('gradientType') is None or not f.get('from') or not f.get('to')]
    checks.append({'name': '渐变含 gradientType/from/to',
                   'detail': f'{len(grads)} 个渐变，{len(bad_grad)} 个缺方向',
                   'ok': len(bad_grad) == 0,
                   'extra': [f'"{nm}"' for nm, _ in bad_grad[:5]]})

    borders = []
    walk(layers_tree, lambda n: borders.extend((n.get('name'), b) for b in (n.get('style') or {}).get('borders') or []))
    no_align = [(nm, b) for nm, b in borders if not b.get('lineAlignment')]
    no_thickness = [(nm, b) for nm, b in borders if b.get('thickness') is None]
    aligns = {}
    for _, b in borders:
        aligns[b.get('lineAlignment')] = aligns.get(b.get('lineAlignment'), 0) + 1
    checks.append({'name': 'border 含 lineAlignment 与 thickness',
                   'detail': (f'{len(borders)} 个边框，{len(no_align)} 缺对齐，{len(no_thickness)} 缺粗细; '
                              f'分布 {aligns}'),
                   'ok': len(no_align) == 0 and len(no_thickness) == 0,
                   'extra': [f'"{nm}"' for nm, _ in (no_align + no_thickness)[:5]]})

    shadows = []
    walk(layers_tree, lambda n: shadows.extend((n.get('name'), s) for s in (n.get('style') or {}).get('shadows') or []))
    no_inset = [(nm, s) for nm, s in shadows if 'inset' not in s]
    checks.append({'name': 'shadow 含 inset',
                   'detail': f'{len(shadows)} 个阴影，{len(no_inset)} 缺方向',
                   'ok': len(no_inset) == 0,
                   'extra': [f'"{nm}"' for nm, _ in no_inset[:5]]})

    rots = []
    walk(layers_tree, lambda n: rots.append((n.get('name'), n.get('rotationDeg'))) if n.get('rotationDeg') else None)
    checks.append({'name': 'rotationDeg=0 之外需人工确认',
                   'detail': f'{len(rots)} 个旋转节点: {[(nm, r) for nm, r in rots[:8]]}',
                   'ok': True,
                   'extra': []})

    all_pass = all(c['ok'] for c in checks)
    return {'checks': checks, 'all_pass': all_pass, 'total_texts': len(txts),
            'total_gradients': len(grads), 'total_borders': len(borders),
            'total_shadows': len(shadows), 'rotation_nodes': rots}


def verify_against_sketch(layers_tree, sketch_data):
    """对比 layers 和原始 sketch 的文本颜色/字重。"""
    sk = sketch_data
    all_sk_nodes = []
    def walk_sk(n):
        all_sk_nodes.append(n)
        for ch in n.get('layers') or []:
            walk_sk(ch)
    walk_sk(sk['artboard'])

    mismatches = []
    by_name = {}
    for n in all_sk_nodes:
        tx = n.get('text') or {}
        c = tx.get('content')
        if c is not None:
            by_name.setdefault(c, []).append(n)

    def collect_texts(n):
        out = []
        walk(n, lambda x: out.append(x) if x.get('text') and x['text'].get('content') else None)
        return out

    txts = collect_texts(layers_tree)
    for n in txts:
        content = n['text'].get('content')
        sk_nodes = by_name.get(content, [])
        if not sk_nodes:
            continue
        skn = sk_nodes[0]
        sk_style = (skn.get('text') or {}).get('style') or {}
        sk_color = sk_style.get('color') or {}
        sk_fw = (sk_style.get('font') or {}).get('fontWeight')
        l_color = n['text'].get('color')
        if l_color:
            l_hex = f'#{l_color["r"]:02X}{l_color["g"]:02X}{l_color["b"]:02X}'
            sk_hex = f'#{round(sk_color.get("r",0)*255):02X}{round(sk_color.get("g",0)*255):02X}{round(sk_color.get("b",0)*255):02X}'
            if l_hex != sk_hex:
                mismatches.append(f'"{content}" color {l_hex} != sketch {sk_hex}')
        if l_color and n['text'].get('fontWeight') != sk_fw:
            mismatches.append(f'"{content}" fontWeight {n["text"].get("fontWeight")} != sketch {sk_fw}')
    return mismatches


def verify_layers(layers_path, sketch_path=None):
    """从文件路径验证 layers.json。返回统一结果字典。"""
    with open(layers_path, encoding='utf-8') as f:
        layers_tree = json.load(f)
    result = verify_layers_dict(layers_tree)
    if sketch_path:
        with open(sketch_path, encoding='utf-8') as f:
            sketch_data = json.load(f)
        mismatches = verify_against_sketch(layers_tree, sketch_data)
        result['sketch_mismatches'] = mismatches
        if mismatches:
            result['all_pass'] = False
    return result


def main():
    """兼容旧的命令行入口。"""
    import sys
    if len(sys.argv) < 2:
        print('用法: python verify_layers.py <layers.json> [sketch.json]')
        sys.exit(2)
    layers_path = sys.argv[1]
    sketch_path = sys.argv[2] if len(sys.argv) > 2 else None
    result = verify_layers(layers_path, sketch_path)

    print(f'===== 验证: {layers_path.split("/")[-1]} =====')
    for c in result['checks']:
        flag = 'PASS' if c['ok'] else 'FAIL'
        print(f'  [{flag}] {c["name"]}: {c["detail"]}')
        if c['extra']:
            print(f'         {c["extra"]}')
    if 'sketch_mismatches' in result:
        if result['sketch_mismatches']:
            print(f'  [FAIL] 与原始 sketch 抽查不一致:')
            for m in result['sketch_mismatches'][:10]:
                print(f'         {m}')
        else:
            print(f'  [PASS] 与原始 sketch 抽查文本一致（{result["total_texts"]} 个）')
    print()
    print('结论:', '全部通过 ✅' if result['all_pass'] else '存在失败项 ❌')
    sys.exit(0 if result['all_pass'] else 1)


if __name__ == '__main__':
    main()
