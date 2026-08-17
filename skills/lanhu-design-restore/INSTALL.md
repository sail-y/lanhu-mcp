# lanhu-design-restore 技能安装指南

本 skill 不依赖 Codex 专属路径，可安装到任何支持 skill 的 AI 助手，也可单独作为命令行工具使用。

## 前置条件

- Python 3.10+
- 蓝湖账号 Cookie

## 安装依赖

```bash
pip install -r requirements.txt
```

## 配置 Cookie

脚本只读取 **skill 自身的配置**。
两种配置方式任选其一：

### 方式 1（推荐）：环境变量

```bash
export LANHU_COOKIE="your_lanhu_cookie_string"
```

### 方式 2：skill 本地 `.env`

在 skill 根目录（即 `scripts/` 的上一级）放置 `.env` 文件，复制 `.env.example` 后填写：

```bash
cd lanhu-mcp/skills/lanhu-design-restore
cp .env.example .env
# 编辑 .env，填入 LANHU_COOKIE
```

`.env` 内容示例：

```ini
LANHU_COOKIE=your_lanhu_cookie_string
```

> 优先级：环境变量 > `.env`。`.env` 含敏感信息，已被仓库 `.gitignore` 忽略，请勿提交。
> 想跳过 `.env` 自动读取时，运行脚本加 `--no-dotenv`。

## 网络代理（可选，非 skill 配置）

访问蓝湖需要外网代理时，**无需在 skill 内配置**。httpx 默认沿用运行环境的标准代理：
Windows 走系统代理设置、其他平台读 `HTTPS_PROXY` / `HTTP_PROXY` 环境变量，自动生效。
即在你自己的 shell / 系统里配好代理即可，skill 源码与 `.env` 都不含任何代理开关。

## 配置统一工作目录（缓存落在哪）

本 skill 的所有取数 / 分析产物都写到 **当前工作目录下的 `.lanhu/` 固定子目录**，**不依赖任何环境变量**。

> 复用成立的唯一前提是「每次调用落在同一个工作目录」：你在哪个项目干活，当前目录就是那个项目根目录，`.lanhu` 就建在那里，跨项目天然隔离、同项目可跨会话复用。

- 仅在需要把缓存放到非当前目录的位置时，用 `--workdir <DIR>` 显式覆盖（非常规路径）。
- 若当前目录解析到 skill 自身安装目录内，脚本会直接报错退出（护栏，防止缓存写进 skill）。

## 方式 A：通过 skill-installer 安装

```bash
git clone https://github.com/<your-fork>/lanhu-mcp.git
cd lanhu-mcp
python <path-to-skill-installer>/scripts/install-skill-from-github.py \
  --repo <your-fork>/lanhu-mcp \
  --path skills/lanhu-design-restore
```

安装后 skill 会被放到对应 AI 助手的 skills 目录（如 WorkBuddy 的 `~/.workbuddy/skills/lanhu-design-restore`、Codex 的 `~/.codex/skills/lanhu-design-restore`）。

## 方式 B：手动复制/软链

```bash
git clone https://github.com/<your-fork>/lanhu-mcp.git
cd lanhu-mcp
pip install -r skills/lanhu-design-restore/requirements.txt
ln -s $(pwd)/skills/lanhu-design-restore ~/.workbuddy/skills/lanhu-design-restore  # 换成你所用 AI 助手的 skills 目录
```

## 方式 C：不安装 skill，直接当脚本用

```bash
cd lanhu-mcp/skills/lanhu-design-restore
export LANHU_COOKIE="..."
python scripts/fetch_sketch.py <project_id> <image_id> sketch.json
python scripts/extract_layers.py sketch.json layers.json
python scripts/check_spacing.py layers.json
```

## 验证安装

```bash
python scripts/check_spacing.py --help
```

> 注：`lanhu-mcp` 仓库根目录的 `lanhu_mcp_server.py` 是**独立的 MCP Server 工程**，
> 其 Cookie/代理配置来自它自己的 `.env` / `.mcp.json`，与本 skill 的 `.env` 互不读取。
> 不部署 MCP Server 也不影响本 skill 的任何功能。
