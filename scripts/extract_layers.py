"""从 lanhu sketch_json 深度提取结构化图层树（组件分组 + 精确样式），替代标注模式的拍平散件。

用法: python scripts/extract_layers.py <sketch.json> <out.json>

现在核心逻辑已迁移到 lanhu.tools.layer_extractor，本文件保持兼容 CLI。
"""
import sys
from pathlib import Path

# 把 skill 目录（lanhu.tools 唯一真源所在）加入路径，以便直接运行时 import 本地 lanhu 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "lanhu-design-restore"))
from lanhu.tools.layer_extractor import extract_layers


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    src, dst = sys.argv[1], sys.argv[2]
    total = extract_layers(src, dst)
    print(f'节点总数: {total}')
    print(f'已输出: {dst}')


if __name__ == '__main__':
    main()
