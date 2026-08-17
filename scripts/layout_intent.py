"""分析 sketch 图层树中某个容器的布局意图（居中 / 固定左偏移 / 全宽）。

用法: python scripts/layout_intent.py <layers.json> [container_name]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "lanhu-design-restore"))
from lanhu.tools.layout_analyzer import analyze_layout


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    layers_path = sys.argv[1]
    container_name = sys.argv[2] if len(sys.argv) > 2 else None
    result = analyze_layout(layers_path, container_name)
    import json
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get('status') == 'success' else 1)


if __name__ == '__main__':
    main()
