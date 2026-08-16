"""验证 extract_layers.py 的输出完整性（跑完提取后必须执行）。

用法:
  python scripts/verify_layers.py <layers.json> [sketch.json]

检查项:
  1. 文本 color 缺失数
  2. 渐变节点必须含 gradientType / from / to
  3. border 必须含 lineAlignment
  4. shadow 必须含 inset
  5. rotationDeg != 0 列表
  6. （传 sketch.json 时）抽查文本 color/fontWeight 与原始 sketch 一致

退出码: 0 = 全部通过；1 = 存在失败项

现在核心逻辑已迁移到 lanhu.tools.layer_verifier，本文件保持兼容 CLI。
"""
import sys
from pathlib import Path

# 把仓库根目录加入路径，以便直接运行时 import 本地 lanhu 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lanhu.tools.layer_verifier import verify_layers


def main():
    if len(sys.argv) < 2:
        print(__doc__)
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
