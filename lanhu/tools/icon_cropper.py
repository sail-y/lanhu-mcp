"""从蓝湖渲染图 + layers.json 自动裁剪图标/小图，输出 webp（支持透明，失败回退 png）。

可被 MCP 工具与 CLI 脚本共用。
"""
import json
import re
from pathlib import Path
from typing import Optional

try:
    from PIL import Image
except ImportError as e:  # pragma: no cover
    raise ImportError('请先安装 Pillow: pip install Pillow>=10.0.0') from e

from .page_summarizer import find_page

ICON_RE = re.compile(r'icon|loading|logo|arrow|check|close|delete|edit|add|search', re.I)
MAX_ICON_SIZE = 128


def load_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def safe_name(name: str) -> str:
    """文件名安全化：保留中文、字母、数字、下划线、短横线。"""
    name = re.sub(r'[\s/\\]+', '-', name)
    name = re.sub(r'[^\w\u4e00-\u9fa5-]', '', name)
    return name.strip('-') or 'icon'


def is_icon_candidate(node) -> bool:
    """判断节点是否值得裁剪。"""
    fr = node.get('frame', {})
    w = fr.get('width', 0)
    h = fr.get('height', 0)
    if w <= 0 or h <= 0:
        return False
    t = node.get('type', '')
    name = (node.get('name') or '').lower()

    # bitmap 永远是候选
    if t == 'bitmap':
        return True

    # 小尺寸 symbol / 形状，且名字像图标
    if w <= MAX_ICON_SIZE and h <= MAX_ICON_SIZE and ICON_RE.search(name):
        return True

    # 显式 icon 命名即使稍大也裁剪
    if 'icon' in name and w <= MAX_ICON_SIZE * 2 and h <= MAX_ICON_SIZE * 2:
        return True

    return False


def walk_all(node, path=None, collector=None):
    if collector is None:
        collector = []
    if path is None:
        path = []
    collector.append((node, path + [node.get('name')]))
    for c in node.get('children', []):
        walk_all(c, path + [node.get('name')], collector)
    return collector


def crop_icons(layers_path: str, png_path: str, output_dir: str,
               name_map_json: Optional[str] = None, fmt: str = 'webp') -> dict:
    """从 PNG 裁剪图标。

    Args:
        layers_path: layers.json 路径。
        png_path: 蓝湖渲染图路径（通常 2x 尺寸）。
        output_dir: 输出目录。
        name_map_json: 可选 JSON 字符串/文件路径，把 layer name 映射到输出文件名。
        fmt: 默认 webp，可传 png 强制。
    Returns:
        结果字典，含 saved / skipped / errors。
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    tree = load_json(layers_path)
    page = find_page(tree, None)
    artboard = page.get('frame', {})
    ab_w = artboard.get('width', 1)
    ab_h = artboard.get('height', 1)

    img = Image.open(png_path)
    img_w, img_h = img.size
    scale_x = img_w / ab_w
    scale_y = img_h / ab_h

    name_map = {}
    if name_map_json:
        p = Path(name_map_json)
        if p.exists():
            name_map = load_json(str(p))
        else:
            try:
                name_map = json.loads(name_map_json)
            except json.JSONDecodeError:
                name_map = {}

    saved = []
    skipped = []
    errors = []

    seen = set()
    for node, bc in walk_all(page):
        if not is_icon_candidate(node):
            continue
        fr = node.get('frame', {})
        left = int(round(fr.get('left', 0) * scale_x))
        top = int(round(fr.get('top', 0) * scale_y))
        right = int(round((fr.get('left', 0) + fr.get('width', 0)) * scale_x))
        bottom = int(round((fr.get('top', 0) + fr.get('height', 0)) * scale_y))
        if right <= left or bottom <= top:
            skipped.append({'name': node.get('name'), 'reason': 'zero_size'})
            continue

        raw_name = node.get('name')
        out_name = name_map.get(raw_name) or safe_name(raw_name)
        # 避免同名覆盖：使用递增序号
        if out_name in seen:
            idx = 1
            while f'{out_name}-{idx}' in seen:
                idx += 1
            out_name = f'{out_name}-{idx}'
        seen.add(out_name)

        out_path = output_dir / f'{out_name}.{fmt}'
        try:
            cropped = img.crop((left, top, right, bottom))
            if fmt == 'webp':
                # WebP 保留 alpha；部分 PIL 版本对 RGBA 转 WEBP 需要显式 method
                cropped.save(out_path, 'WEBP', lossless=True, method=6)
            else:
                cropped.save(out_path)
            saved.append({
                'layer_id': raw_name,
                'path': str(out_path),
                'frame': fr,
                'crop_px': [left, top, right, bottom],
                'size_px': [right - left, bottom - top],
            })
        except Exception as e:
            # webp 失败时回退 png
            if fmt == 'webp':
                fallback = output_dir / f'{out_name}.png'
                try:
                    cropped.save(fallback)
                    saved.append({
                        'layer_id': raw_name,
                        'path': str(fallback),
                        'frame': fr,
                        'crop_px': [left, top, right, bottom],
                        'size_px': [right - left, bottom - top],
                        'fallback': 'png',
                    })
                    continue
                except Exception as e2:
                    errors.append({'name': raw_name, 'error': str(e2)})
                    continue
            errors.append({'name': raw_name, 'error': str(e)})

    return {
        'status': 'success' if not errors else 'partial',
        'output_dir': str(output_dir),
        'scale': [scale_x, scale_y],
        'saved': saved,
        'skipped': skipped,
        'errors': errors,
        'total': len(saved) + len(skipped) + len(errors),
    }


def main():
    import sys
    if len(sys.argv) < 4:
        print('用法: python icon_cropper.py <layers.json> <render.png> <output_dir> [name_map.json] [webp|png]')
        sys.exit(2)
    layers_path = sys.argv[1]
    png_path = sys.argv[2]
    output_dir = sys.argv[3]
    name_map_json = sys.argv[4] if len(sys.argv) > 4 else None
    fmt = sys.argv[5] if len(sys.argv) > 5 else 'webp'
    result = crop_icons(layers_path, png_path, output_dir, name_map_json, fmt)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get('status') == 'success' else 1)


if __name__ == '__main__':
    main()
