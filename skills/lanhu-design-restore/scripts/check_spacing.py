"""从 layers.json 分析容器 padding/margin/gap，支持跨页同名容器对比。

单容器模式默认按 project_id + image_id 从 .lanhu 读 layers.json，结果写到 analysis/spacing.json；--compare 跨页对比走显式路径（不落盘）。

用法：
  python check_spacing.py --project-id PID --image-id IID [容器名] [--workdir DIR]
  python check_spacing.py <layers.json> [容器名]
  python check_spacing.py --compare <a.json> <b.json> ... --name <容器名>
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lanhu.tools.spacing_checker import check_container, check_all_containers, compare_containers
from lanhu.tools.workspace import (
    resolve_workdir,
    layers_path,
    analysis_path,
    touch_image,
)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Check container spacing from layers.json")
    parser.add_argument("layers", nargs="?", help="layers.json path (single mode; or use --project-id/--image-id)")
    parser.add_argument("container", nargs="?", help="container name (optional)")
    parser.add_argument("--project-id", default=None)
    parser.add_argument("--image-id", default=None)
    parser.add_argument("--workdir", default=None)
    parser.add_argument("--compare", nargs="+", default=None,
                        help="2+ layers.json paths for cross-page compare")
    parser.add_argument("--name", default=None, help="container name for --compare")
    args = parser.parse_args()

    workdir = resolve_workdir(args.workdir)

    if args.compare:
        paths = args.compare
        name = args.name
        if not name or len(paths) < 2:
            print("--compare 需要至少两个 layers.json 和 --name 容器名")
            sys.exit(2)
        result = compare_containers(paths, name)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result.get("status") == "success" else 1)

    if args.project_id and args.image_id:
        lp = layers_path(workdir, args.project_id, args.image_id)
        container_name = args.container
        result = check_container(str(lp), container_name) if container_name else check_all_containers(str(lp))
        out = analysis_path(workdir, args.project_id, args.image_id, "spacing")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        touch_image(workdir, args.project_id, args.image_id, analysis_kind="spacing")
        print(f"[OK] analysis saved: {out}")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result.get("status") == "success" else 1)

    if not args.layers:
        print("用法:\n"
              "  python check_spacing.py <layers.json> [容器名]\n"
              "  python check_spacing.py --project-id PID --image-id IID [容器名] [--workdir DIR]\n"
              "  python check_spacing.py --compare <a.json> <b.json> ... --name <容器名>")
        sys.exit(2)
    layers_path_arg = args.layers
    container_name = args.container
    if container_name:
        result = check_container(layers_path_arg, container_name)
    else:
        result = check_all_containers(layers_path_arg)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get("status") == "success" else 1)


if __name__ == "__main__":
    main()
