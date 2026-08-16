"""本文件是薄包装：核心逻辑在 repo/lanhu/tools。
直接运行本脚本时自动定位 repo 根目录并加入 sys.path。
支持两种安装方式：
  1. 把本 skill 目录 symlink 到 ~/.codex/skills/lanhu-design-restore/（自动解析）
  2. 设置环境变量 LANHU_MCP_REPO 指向 repo 根目录
"""
import sys
from pathlib import Path

def _find_repo():
    import os
    # 1. 如果 skill 是 symlink 到 repo/skills/lanhu-design-restore/，解析后向上两级就是 repo
    skill_dir = Path(__file__).resolve().parent
    candidate = skill_dir.parent.parent.parent
    if (candidate / 'lanhu' / 'tools').exists():
        return candidate
    # 2. 环境变量显式指定
    env = os.environ.get('LANHU_MCP_REPO')
    if env:
        p = Path(env)
        if (p / 'lanhu' / 'tools').exists():
            return p
    # 3. 常见路径兜底
    home = Path.home()
    for p in [
        home / 'lanhu-mcp',
        home / 'work' / 'ai' / 'lanhu-mcp',
        home / 'projects' / 'lanhu-mcp',
    ]:
        if (p / 'lanhu' / 'tools').exists():
            return p
    raise RuntimeError(
        '找不到 lanhu-mcp repo。请把本 skill 以 symlink 安装到 ~/.codex/skills/lanhu-design-restore/，'
        '或设置环境变量 LANHU_MCP_REPO 指向 repo 根目录。'
    )

sys.path.insert(0, str(_find_repo()))
import sys
from lanhu.tools.layer_verifier import verify_layers


def main():
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
