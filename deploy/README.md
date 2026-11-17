# 一键部署

发行包解压后，项目根目录应包含 `server/`、`web/`、`config/` 和本 `deploy/` 目录。

## Windows

双击：

```text
deploy\one-click-deploy.bat
```

脚本会检查 Python 3.10+，启动本地服务并打开 <http://127.0.0.1:8765>。关闭最小化的
`Meridian News Timeline` 窗口即可停止服务。

## macOS / Linux

```bash
bash deploy/one-click-deploy.sh
```

也可以直接运行：

```bash
python3 server/app.py
```

## Docker

```bash
docker compose up -d
```

打开 <http://127.0.0.1:8765>。数据持久化在 `./data/news.db`。

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `PORT` | `8765` | 本地端口 |
| `HOST` | `127.0.0.1` | 监听地址；局域网访问可设为 `0.0.0.0` |
| `NEWS_NO_FETCH` | 空 | 设为 `1` 时只启动界面，不抓取新闻 |
| `NEWS_DB` | `data/news.db` | SQLite 数据库路径 |
| `CUSTOMIZATION_PATH` | `data/customization.json` | 图形化自定义的覆盖层路径 |
| `ADMIN_TOKEN` | 空 | 设置后自定义中心写操作需要令牌；局域网暴露时建议设置 |
| `TRANSLATE_PROVIDER` | `auto` | 主翻译接口；选中的接口同时用于手动和自动翻译 |

付费翻译 Key 可以在“运行设置”里填写（推荐），也可以用 `DEEPL_API_KEY`、`OPENAI_API_KEY`、`AZURE_TRANSLATOR_KEY`、`BAIDU_TRANSLATE_KEY` 等环境变量注入；完整列表见主 README。公网部署时请限制 `/api/translate`，避免他人消耗付费额度。

## 常见问题

- **Python 未找到**：安装 Python 3.10+，Windows 安装时勾选 “Add Python to PATH”。
- **端口被占用**：设置 `PORT=9000` 后重新运行。
- **首次打开较慢**：首次抓取通常需要 30–90 秒，取决于信源响应；界面会先生成空库再增量填充。
- **重置数据**：停止服务后删除 `data/news.db`，下次启动会重新抓取。
