"""从 layers.json 生成页面规格摘要，输出卡片/输入框/按钮/开关/图标/字体分组。

默认按 project_id + image_id 从 .lanhu 读 layers.json，结果写到 analysis/page_summary.json；也可传位置参数 <layers.json> 仅打印。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lanhu.tools.page_summarizer import summarize_page
from lanhu.tools.workspace import (
    resolve_workdir,
    layers_path,
    analysis_path,
    touch_image,
)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Summarize page spec from layers.json")
    parser.add_argument("layers", nargs="?", help="layers.json path (or use --project-id/--image-id)")
    parser.add_argument("page", nargs="?", help="page name (optional)")
    parser.add_argument("--project-id", default=None)
    parser.add_argument("--image-id", default=None)
    parser.add_argument("--workdir", default=None)
    args = parser.parse_args()

    workdir = resolve_workdir(args.workdir)

    if args.project_id and args.image_id:
        lp = layers_path(workdir, args.project_id, args.image_id)
        result = summarize_page(str(lp), args.page)
        out = analysis_path(workdir, args.project_id, args.image_id, "page_summary")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        touch_image(workdir, args.project_id, args.image_id, analysis_kind="page_summary")
        print(f"[OK] analysis saved: {out}")
    else:
        if not args.layers:
            print("用法: python summarize_page.py <layers.json> [page_name]  "
                  "[或 --project-id PID --image-id IID --workdir DIR]")
            sys.exit(2)
        result = summarize_page(args.layers, args.page)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get("status") == "success" else 1)


if __name__ == "__main__":
    main()
