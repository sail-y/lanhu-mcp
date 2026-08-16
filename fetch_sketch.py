"""从蓝湖拉取指定设计图的原始 sketch 图层树并落盘（lanhu-design-restore skill 取数第一步）。

用法:
  python fetch_sketch.py <project_id> <image_id> <out.json> [--team_id TEAM_ID] [--server PATH]

前置条件（唯一外部依赖）:
  1. lanhu-mcp 已配置在 ~/.workbuddy/mcp.json（env 含 LANHU_COOKIE，可选 http_proxy/https_proxy）
  2. lanhu_mcp_server.py 可访问——默认探测 <skill_dir>/../lanhu-mcp/lanhu_mcp_server.py，
     可用 --server 或环境变量 LANHU_MCP_SERVER 覆盖

说明:
  - cookie 在 server import 时一次性读取，故必须先 setenv 再 import
  - team_id 一般传 None（本项目用不到）；image_id 可从 lanhu_get_designs 列表获取
"""
import importlib.util
import json
import os
import sys
from pathlib import Path


def load_mcp_env():
    """从 ~/.workbuddy/mcp.json 读取 lanhu-mcp 的 env（cookie + 代理）"""
    mcp_path = Path.home() / '.workbuddy' / 'mcp.json'
    if not mcp_path.exists():
        print('[WARN] 未找到 ~/.workbuddy/mcp.json，将使用环境变量中的 cookie')
        return
    try:
        cfg = json.loads(mcp_path.read_text(encoding='utf-8'))
    except Exception as e:
        print(f'[WARN] 读取 mcp.json 失败: {e}')
        return
    srv = (cfg.get('mcpServers') or {}).get('lanhu-mcp') or {}
    for k, v in (srv.get('env') or {}).items():
        os.environ.setdefault(k, v)
    print(f'[INFO] 已从 mcp.json 注入 env（LANHU_COOKIE={bool(os.environ.get("LANHU_COOKIE"))}）')


def find_server(candidates):
    for p in candidates:
        if p and Path(p).exists():
            return str(p)
    return None


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(2)
    project_id = sys.argv[1]
    image_id = sys.argv[2]
    out_path = sys.argv[3]
    team_id = None
    server_path = os.environ.get('LANHU_MCP_SERVER')
    args = sys.argv[4:]
    i = 0
    while i < len(args):
        if args[i] == '--team_id' and i + 1 < len(args):
            team_id = args[i + 1]
            i += 2
        elif args[i] == '--server' and i + 1 < len(args):
            server_path = args[i + 1]
            i += 2
        else:
            i += 1

    # 探测 server 路径：--server > LANHU_MCP_SERVER > skill 目录的 lanhu-mcp 工作区 > 常见位置
    script_dir = Path(__file__).resolve().parent
    candidates = [
        server_path,
        str(script_dir.parent.parent.parent / 'lanhu-mcp' / 'lanhu_mcp_server.py'),  # skill 上级的 lanhu-mcp
        r'd:/work/ai/lanhu-mcp/lanhu_mcp_server.py',
        r'C:/Users/USER/.workbuddy/lanhu-mcp/lanhu_mcp_server.py',
    ]
    server = find_server(candidates)
    if not server:
        print('[FAIL] 找不到 lanhu_mcp_server.py，请用 --server 或 LANHU_MCP_SERVER 指定路径')
        sys.exit(1)

    load_mcp_env()

    # lanhu_mcp_server.py 无条件 import codex_stdio_bridge（IDE MCP 运行时的 stdio 桥接，独立运行时不存在）。
    # fetch 只需 LanhuExtractor 做 HTTP，注入 stub 绕过该桥接（install 为 no-op）。
    import types
    _stub = types.ModuleType('codex_stdio_bridge')
    _stub.install = lambda: None
    sys.modules['codex_stdio_bridge'] = _stub

    spec = importlib.util.spec_from_file_location('lanhu_mcp_server', server)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    async def run():
        ex = m.LanhuExtractor()
        sk = await ex.get_sketch_json(image_id, team_id, project_id)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(json.dumps(sk, ensure_ascii=False), encoding='utf-8')
        print(f'[OK] sketch 已落盘: {out_path}')

    import asyncio
    asyncio.run(run())


if __name__ == '__main__':
    main()
