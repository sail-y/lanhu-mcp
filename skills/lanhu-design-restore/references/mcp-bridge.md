# 可选 MCP Server 桥接

本节为可选扩展，不属于 skill 核心能力。skill 本身独立可用，无需阅读本节即可正常使用。

仓库内另含一个独立的 MCP Server 工程（`lanhu_mcp_server.py`），可将同一套 `lanhu/tools` 纯函数暴露为 MCP 工具，供支持 MCP 的客户端调用。关系如下：

- **共享逻辑**：MCP Server 复用 `lanhu/tools/*.py` 的纯函数，不重复实现。
- **配置分离**：MCP Server 的配置来自其自身 `.env` / `.mcp.json`，与 skill 的 `.env` 互不读取。
- **skill 不依赖 MCP**：无论是否部署 MCP Server，本 skill 的 CLI 脚本均可独立运行。

CLI 脚本与 MCP 工具名映射（仅供参考，不是 skill 使用前提）：

| CLI 脚本 | 等效 MCP 工具名 |
|----------|----------------|
| `scripts/fetch_sketch.py` | `lanhu_get_sketch_json` |
| `scripts/extract_layers.py` | `lanhu_extract_layers` |
| `scripts/verify_layers.py` | `lanhu_verify_layers` |
| `scripts/layout_intent.py` | `lanhu_analyze_layout` |
| `scripts/summarize_page.py` | `lanhu_summarize_page` |
| `scripts/download_slices.py` | `lanhu_get_design_slices` |
| `scripts/crop_icons.py` | `lanhu_crop_icons` |
| `scripts/check_spacing.py` | `lanhu_check_spacing` |
