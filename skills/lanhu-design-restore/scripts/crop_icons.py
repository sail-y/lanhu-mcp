"""从蓝湖渲染图 + layers.json 自动裁剪图标，输出 webp/png 文件列表。

默认裁剪到 .lanhu 工作区的 icons/（按 project_id + image_id 定位），渲染图默认取 raw/render.png；也可传位置参数走显式路径。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lanhu.tools.icon_cropper import crop_icons
from lanhu.tools.workspace import (
    resolve_workdir,
    layers_path,
    render_path,
    icons_dir,
    manifest_path,
    touch_image,
)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Crop icons from render.png by layers.json")
    parser.add_argument("layers", nargs="?", help="layers.json path (or use --project-id/--image-id)")
    parser.add_argument("png", nargs="?", help="render.png path (or raw/render.png)")
    parser.add_argument("out", nargs="?", help="output dir (or standard .lanhu icons/)")
    parser.add_argument("--project-id", default=None)
    parser.add_argument("--image-id", default=None)
    parser.add_argument("--workdir", default=None)
    parser.add_argument("--name-map", default=None, help="name_map.json (path or inline JSON)")
    parser.add_argument("--fmt", default="webp", choices=["webp", "png"])
    args = parser.parse_args()

    workdir = resolve_workdir(args.workdir)

    if args.project_id and args.image_id:
        layers_p = layers_path(workdir, args.project_id, args.image_id)
        png_p = Path(args.png) if args.png else render_path(workdir, args.project_id, args.image_id)
        if not png_p.exists():
            print(f"[FAIL] render.png not found: {png_p}\n"
                  f"       请先放置渲染图到该路径，或用 --render 传给 fetch_sketch.py，"
                  f"或显式传 png 位置参数。")
            sys.exit(2)
        out_dir = Path(args.out) if args.out else icons_dir(workdir, args.project_id, args.image_id)
        name_map = args.name_map
    else:
        if not (args.layers and args.png and args.out):
            print("用法: python crop_icons.py <layers.json> <render.png> <out_dir> "
                  "[--name-map x.json] [--fmt webp|png]  "
                  "[或 --project-id PID --image-id IID --workdir DIR]")
            sys.exit(2)
        layers_p, png_p, out_dir, name_map = (
            Path(args.layers), Path(args.png), Path(args.out), args.name_map
        )

    result = crop_icons(str(layers_p), str(png_p), str(out_dir), name_map, args.fmt)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    status = result.get("status")
    if status in ("success", "partial") and args.project_id and args.image_id:
        touch_image(workdir, args.project_id, args.image_id, icons=True)
        print(f"[INFO] manifest updated: {manifest_path(workdir, args.project_id)}")
    sys.exit(0 if status == "success" else 1)


if __name__ == "__main__":
    main()
