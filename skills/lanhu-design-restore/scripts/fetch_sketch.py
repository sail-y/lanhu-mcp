"""Fetch raw sketch JSON for a Lanhu design image.

Calls the Lanhu HTTP API directly and writes the result into the .lanhu
workspace. Configuration comes from lanhu.tools.config (env var or skill .env).
"""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

try:
    import httpx
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Please install httpx: pip install httpx>=0.27.0") from exc

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lanhu.tools.config import load_dotenv, get_cookie, ENV_FILE
from lanhu.tools.workspace import (  # noqa: E402
    resolve_workdir,
    sketch_path,
    render_path,
    manifest_path,
    touch_image,
)

BASE_URL = "https://lanhuapp.com"


def fetch_sketch(project_id: str, image_id: str, team_id: str | None = None,
                 version_id: str | None = None) -> dict:
    """拉取设计原始 JSON。

    返回 {'payload': <设计 JSON>, 'version': {id, name, created_at, url, json_url, sha256}}。
    版本默认取最新；传 version_id 可锁定历史版本——这样「同一条命令两次跑出不同数值」
    能立刻区分是稿子改了还是代码改了。
    """
    cookie = get_cookie()
    headers = {"Cookie": cookie, "User-Agent": "Mozilla/5.0"}

    with httpx.Client(
        headers=headers, follow_redirects=True, timeout=60.0
    ) as client:
        url = f"{BASE_URL}/api/project/image"
        params = {"dds_status": 1, "image_id": image_id, "project_id": project_id}
        if team_id:
            params["team_id"] = team_id

        resp = client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != "00000":
            raise SystemExit(f"[FAIL] Failed to fetch design: {data.get('msg')}")

        result = data.get("result") or {}
        versions = result.get("versions") or []
        if not versions:
            raise SystemExit("[FAIL] No usable versions found")

        chosen = None
        if version_id:
            for v in versions:
                if str(v.get("id")) == str(version_id):
                    chosen = v
                    break
            if chosen is None:
                available = ", ".join(str(v.get("id")) for v in versions[:10])
                raise SystemExit(f"[FAIL] version_id={version_id} 不在该设计图版本列表里；可选: {available}")

        # 版本列表按新→旧返回；没有显式指定时取最新，但把版本号记录下来
        selected = chosen or versions[0]
        json_url = selected.get("json_url")
        if not json_url:
            raise SystemExit("[FAIL] json_url not found")

        sketch_resp = client.get(json_url)
        sketch_resp.raise_for_status()
        raw = sketch_resp.content
        version_meta = {
            "version_id": selected.get("id"),
            "version_name": selected.get("name"),
            "created_at": selected.get("created_at") or selected.get("createdAt"),
            "json_url": json_url,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "pinned": chosen is not None,
        }
        return {"payload": sketch_resp.json(), "version": version_meta}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch Lanhu sketch JSON into the .lanhu workspace"
    )
    parser.add_argument("project_id", help="Lanhu project_id")
    parser.add_argument("image_id", help="Design image_id")
    parser.add_argument(
        "--out",
        default=None,
        help="Override sketch output path (default: "
        "<workdir>/.lanhu/projects/<project_id>/images/<image_id>/raw/sketch.json)",
    )
    parser.add_argument(
        "--workdir",
        default=None,
        help="Working directory holding .lanhu (default: cwd)",
    )
    parser.add_argument("--team_id", default=None, help="Team ID (optional)")
    parser.add_argument(
        "--version-id",
        default=None,
        help="锁定设计版本 id（不传取最新；无论是否指定都会把版本号与 sha256 写入 raw/sketch.meta.json）",
    )
    parser.add_argument(
        "--render",
        default=None,
        help="Optional local render.png to copy into raw/render.png",
    )
    parser.add_argument(
        "--no-dotenv",
        action="store_true",
        help="Do not read the skill-local .env file (use env vars only)",
    )
    args = parser.parse_args()

    if not args.no_dotenv:
        if load_dotenv():
            print(f"[INFO] Loaded config from {ENV_FILE}")

    workdir = resolve_workdir(args.workdir)
    out_path = Path(args.out) if args.out else sketch_path(
        workdir, args.project_id, args.image_id
    )

    fetched = fetch_sketch(args.project_id, args.image_id, args.team_id, args.version_id)
    sketch = fetched["payload"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(sketch, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] sketch saved: {out_path}")

    meta_path = out_path.with_name("sketch.meta.json")
    meta_path.write_text(
        json.dumps(fetched["version"], ensure_ascii=False, indent=1), encoding="utf-8"
    )
    v = fetched["version"]
    print(f"[OK] version pinned: id={v['version_id']} sha256={v['sha256'][:12]}… "
          f"({'显式锁定' if v['pinned'] else '最新版（已记录，可回溯）'})")

    if args.render:
        rp = render_path(workdir, args.project_id, args.image_id)
        rp.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.render, rp)
        print(f"[OK] render saved: {rp}")

    touch_image(
        workdir,
        args.project_id,
        args.image_id,
        fetched=True,
        render=bool(args.render),
    )
    print(f"[INFO] manifest updated: {manifest_path(workdir, args.project_id)}")


if __name__ == "__main__":
    main()
