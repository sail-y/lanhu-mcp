"""从 layers.json 生成页面规格摘要（布局/卡片/输入/按钮/开关/图标/字体）。

用法: python scripts/summarize_page.py <layers.json> [page_name]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "lanhu-design-restore"))
from lanhu.tools.page_summarizer import summarize_page


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    layers_path = sys.argv[1]
    page_name = sys.argv[2] if len(sys.argv) > 2 else None
    result = summarize_page(layers_path, page_name)
    import json
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get('status') == 'success' else 1)


if __name__ == '__main__':
    main()
