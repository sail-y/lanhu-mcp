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
import json
from lanhu.tools.icon_cropper import crop_icons


def main():
    if len(sys.argv) < 4:
        print('用法: python crop_icons.py <layers.json> <render.png> <output_dir> [name_map.json] [webp|png]')
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
