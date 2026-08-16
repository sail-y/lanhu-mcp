"""从蓝湖渲染图 + layers.json 自动裁剪图标。

用法: python scripts/crop_icons.py <layers.json> <render.png> <output_dir> [name_map.json] [webp|png]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lanhu.tools.icon_cropper import crop_icons


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(2)
    layers_path = sys.argv[1]
    png_path = sys.argv[2]
    output_dir = sys.argv[3]
    name_map_json = sys.argv[4] if len(sys.argv) > 4 else None
    fmt = sys.argv[5] if len(sys.argv) > 5 else 'webp'
    result = crop_icons(layers_path, png_path, output_dir, name_map_json, fmt)
    import json
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get('status') == 'success' else 1)


if __name__ == '__main__':
    main()
