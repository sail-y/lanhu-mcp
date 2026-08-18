"""分析容器布局意图，输出 margins / intent / CSS 建议。

默认按 project_id + image_id 从 .lanhu 读 layers.json，结果写到 analysis/layout_intent.json；也可传位置参数 <layers.json> 仅打印。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lanhu.tools.layout_analyzer import analyze_layout
from lanhu.tools.workspace import (
    resolve_workdir,
    layers_path,
    analysis_path,
    touch_image,
)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Analyze container layout intent")
    parser.add_argument("layers", nargs="?", help="layers.json path (or use --project-id/--image-id)")
    parser.add_argument("container", nargs="?", help="container name (optional)")
    parser.add_argument("--container", dest="container_opt", default=None,
                        help="container name (explicit; avoids positional ambiguity)")
    parser.add_argument("--project-id", default=None)
    parser.add_argument("--image-id", default=None)
    parser.add_argument("--workdir", default=None)
    args = parser.parse_args()

    container_name = args.container_opt or args.container
    # 文档用法 `--project-id PID --image-id IID 容器名` 中，argparse 会把容器名
    # 绑定到第一个位置参数 layers 上；这里把它救回来（.json 路径除外）。
    if args.project_id and args.image_id and not container_name \
            and args.layers and not str(args.layers).endswith(".json"):
        container_name = args.layers
        args.layers = None

    workdir = resolve_workdir(args.workdir)

    if args.project_id and args.image_id:
        lp = layers_path(workdir, args.project_id, args.image_id)
        result = analyze_layout(str(lp), container_name)
        out = analysis_path(workdir, args.project_id, args.image_id, "layout_intent")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        touch_image(workdir, args.project_id, args.image_id, analysis_kind="layout_intent")
        print(f"[OK] analysis saved: {out}")
    else:
        if not args.layers:
            print("用法: python layout_intent.py <layers.json> [容器名]  "
                  "[或 --project-id PID --image-id IID 容器名 --workdir DIR]")
            sys.exit(2)
        result = analyze_layout(args.layers, container_name)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get("status") == "success" else 1)


if __name__ == "__main__":
    main()
