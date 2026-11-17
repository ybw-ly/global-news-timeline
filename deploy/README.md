# 部署与更新手册

适用于 **Global News Timeline / 经纬** v1.16.0 及之后的版本。

- Release：<https://github.com/ybw-ly/global-news-timeline/releases>
- 当前版本安装包：`global-news-timeline-v1.16.0.zip`
- 当前版本 SHA256：`9fdf2abaee78a898f25799b2467eae11588570e78cd40409d7cc3093349f8f80`

---

## 1. 部署前须知

### 运行环境

- Python **3.10+**（开发和测试使用 3.12）
- **不需要 pip 安装任何第三方包**，只用 Python 标准库
- 首次启动需要能访问 RSS / API 信源
- 默认端口 `8765`，默认只监听 `127.0.0.1`

### 目录与数据

```text
global-news-timeline/
├── server/                 # Python 服务端
├── web/                    # 前端页面
├── config/                 # 内置信源、选举、词典等配置
├── data/                   # 运行时数据（重点备份）
│   ├── news.db             # SQLite 新闻库
│   ├── customization.json  # GUI 自定义覆盖层；可能包含 API Key
│   └── geo/                # 地图等静态数据
├── deploy/                 # 本手册与一键部署脚本
├── Dockerfile
├── docker-compose.yml
├── run.bat / run.sh
└── launch-desktop.bat
```

**升级时最重要的原则：只替换程序文件，保留 `data/` 和 `.env`。**

`data/customization.json` 里可能保存 DeepL / OpenAI 兼容 / Azure 等 API Key，不要提交到 Git、不要发给别人；建议权限设为仅服务账户可读。

### 环境变量

在启动前设置，或写进 `.env` / systemd 的 `Environment=` / Docker Compose 的 `environment:`。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `HOST` | `127.0.0.1` | 监听地址；公网/局域网部署见第 8 节 |
| `PORT` | `8765` | 端口被占用时会尝试 8766–8784 |
| `NEWS_DB` | `data/news.db` | SQLite 路径 |
| `CUSTOMIZATION_PATH` | `data/customization.json` | 自定义覆盖层路径 |
| `NEWS_NO_FETCH` | 空 | 设为 `1` 只启动界面，不抓取新闻 |
| `ADMIN_TOKEN` | 空 | 设置后自定义中心写操作需 `X-Admin-Token`；对外暴露时强烈建议设置 |
| `TRANSLATE_PROVIDER` | `auto` | 主翻译接口；选中后手动和自动翻译都用它 |
| `OLLAMA_URL` / `OLLAMA_MODEL` | `http://127.0.0.1:11434` / `qwen3-vl:8b` | 本地 Ollama 翻译 |
| `LIBRETRANSLATE_URL` / `LIBRETRANSLATE_API_KEY` | 空 | LibreTranslate |
| `DEEPL_API_KEY` | 空 | DeepL |
| `GOOGLE_TRANSLATE_API_KEY` | 空 | Google Cloud Translation |
| `AZURE_TRANSLATOR_KEY` / `AZURE_TRANSLATOR_REGION` | 空 | Azure Translator |
| `OPENAI_BASE_URL` / `OPENAI_API_KEY` / `OPENAI_MODEL` | `https://api.openai.com/v1` / 空 / `gpt-4o-mini` | OpenAI 兼容接口（也可填 DeepSeek / Moonshot / Qwen / vLLM 等） |
| `BAIDU_TRANSLATE_APPID` / `BAIDU_TRANSLATE_KEY` | 空 | 百度翻译 |
| `YOUDAO_APP_KEY` / `YOUDAO_APP_SECRET` | 空 | 有道智云 |
| `SEARCH_TRANSLATE` | `1` | 设为 `0` 关闭搜索词跨语言翻译 |
| `SEARCH_TRANSLATE_LANGS` | 空 | 逗号分隔的目标语言；空表示全部支持语言 |

完整的翻译接口与 Key 说明见主 README 的“翻译提供链与 API Key”一节。API Key 优先在网页“运行设置”里填写，也可以走上面的环境变量。

---

## 2. 全新部署

### 方式 A：Windows 一键包

1. 下载并解压 `global-news-timeline-v1.16.0.zip`。
2. 双击 `deploy\one-click-deploy.bat`。
3. 脚本会检查 Python 3.10+、启动服务并打开浏览器。
4. 关闭最小化的 **Meridian News Timeline** 控制台窗口即可停止服务。

也可以直接：

```bat
run.bat
```

或：

```bat
python server\app.py
```

桌面入口：双击 `launch-desktop.bat`，服务未启动时会自动启动并打开浏览器。

### 方式 B：macOS / Linux 直接运行

```bash
cd global-news-timeline
bash deploy/one-click-deploy.sh
```

或：

```bash
./run.sh
# 或
python3 server/app.py
```

打开 <http://127.0.0.1:8765>。

首次启动会在后台抓取全部启用信源，通常需要 1–2 分钟；页面先显示骨架屏，抓取完成后自动更新。

### 方式 C：Docker Compose

```bash
cd global-news-timeline
docker compose up -d --build
```

打开 <http://127.0.0.1:8765>。

- `docker-compose.yml` 默认只把端口绑定到宿主 `127.0.0.1`。
- `./data` 挂载到容器 `/app/data`，数据库和 API Key 持久化。
- `./config` 只读挂载；修改内置配置后 `docker compose restart`。
- 容器内通过 `host.docker.internal:11434` 访问宿主 Ollama；Linux 的 `host-gateway` 已写入 compose。
- 不要把 `docker compose down -v` 当成普通停止命令；如果你改成了命名卷，`-v` 会删除数据卷。

### 方式 D：Linux systemd 常驻

示例 unit（按实际路径修改）：

```ini
[Unit]
Description=Global News Timeline
After=network.target

[Service]
Type=simple
User=news
WorkingDirectory=/opt/global-news-timeline
Environment=HOST=127.0.0.1
Environment=PORT=8765
Environment=NEWS_DB=/opt/global-news-timeline/data/news.db
Environment=CUSTOMIZATION_PATH=/opt/global-news-timeline/data/customization.json
# 对外暴露时设置，并在自定义中心填写同一令牌
# Environment=ADMIN_TOKEN=change-me
ExecStart=/usr/bin/python3 server/app.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now global-news-timeline
sudo systemctl status global-news-timeline
curl http://127.0.0.1:8765/api/health
```

---

## 3. 首次启动后检查

```bash
curl -fsS http://127.0.0.1:8765/api/health
```

应返回包含：

```json
{"ok": true, "version": "1.16.0"}
```

Windows PowerShell：

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/health
```

然后打开：

- 首页：<http://127.0.0.1:8765>
- 自定义中心：<http://127.0.0.1:8765/customize.html>
- 运行设置：<http://127.0.0.1:8765/customize.html#runtime>

---

## 4. 更新原则

1. **先停服务**，不要在写入数据库时直接覆盖。
2. **备份 `data/`**（至少 `news.db` 和 `customization.json`）。
3. **保留 `.env` / systemd 环境变量 / Docker Compose 的自定义环境变量**。
4. **只替换程序文件**：`server/`、`web/`、`config/`、`deploy/`、根目录脚本、Dockerfile 等。
5. **不要用新包的 `data/` 覆盖旧 `data/`**；新包通常不包含数据库和自定义 JSON。
6. 启动后检查 `/api/health` 的版本号。
7. 保留旧目录或旧镜像，出问题可以回滚。

### 备份命令

Linux/macOS（建议停服务后执行）：

```bash
cd /path/to/global-news-timeline
tar czf ../gnt-backup-$(date +%F-%H%M).tar.gz data
```

Windows PowerShell：

```powershell
Compress-Archive -Path .\data -DestinationPath ..\gnt-backup-$(Get-Date -Format yyyyMMdd-HHmm).zip
```

如果服务无法停止，至少同时复制 `news.db`、`news.db-wal`、`news.db-shm`，否则可能拿到不一致的快照。

---

## 5. 从旧版本更新到 v1.16.0

### 方式 A：zip 部署（Windows / Linux 通用，最稳）

以 Linux 为例：

```bash
# 1. 停服务
sudo systemctl stop global-news-timeline
# 或手动结束原来的 python server/app.py

# 2. 备份旧数据
cd /opt/global-news-timeline
tar czf /opt/gnt-data-backup-$(date +%F).tar.gz data

# 3. 下载并校验新包
curl -L -o /tmp/gnt-v1.16.0.zip \
  https://github.com/ybw-ly/global-news-timeline/releases/download/v1.16.0/global-news-timeline-v1.16.0.zip
sha256sum /tmp/gnt-v1.16.0.zip
# 应为 9fdf2abaee78a898f25799b2467eae11588570e78cd40409d7cc3093349f8f80

# 4. 解压到新目录
unzip -q /tmp/gnt-v1.16.0.zip -d /opt/gnt-new

# 5. 复制旧 data 到新目录（不要反过来覆盖旧数据）
mkdir -p /opt/gnt-new/global-news-timeline/data
cp -a /opt/global-news-timeline/data/. /opt/gnt-new/global-news-timeline/data/

# 6. 复制 .env（如果有）
cp -a /opt/global-news-timeline/.env /opt/gnt-new/global-news-timeline/.env 2>/dev/null || true

# 7. 切换目录
sudo mv /opt/global-news-timeline /opt/global-news-timeline-old
sudo mv /opt/gnt-new/global-news-timeline /opt/global-news-timeline
sudo systemctl start global-news-timeline
curl http://127.0.0.1:8765/api/health
```

Windows：

1. 停掉原来的服务窗口 / Python 进程。
2. 备份旧 `data` 文件夹。
3. 解压新 zip 到新文件夹。
4. 把旧 `data` 整个复制到新文件夹。
5. 如果有 `.env`、自定义 `HOST`/`PORT`/`ADMIN_TOKEN`，一并带过去。
6. 运行新文件夹的 `launch-desktop.bat` 或 `python server\app.py`。
7. 旧文件夹先保留，确认无误后再删除。

### 方式 B：git 部署

```bash
cd /path/to/global-news-timeline
git status                 # 确认没有未提交的本地改动
cp -a data data.backup-$(date +%F)
git pull --ff-only origin main
# 如果使用 systemd：
sudo systemctl restart global-news-timeline
# 如果手动运行：
python3 server/app.py
```

如果本地改过源码，先 `git stash` 或备份，不要直接 `git reset --hard`。

### 方式 C：Docker 部署

```bash
cd /path/to/global-news-timeline

# 1. 停服务（不要加 -v）
docker compose down

# 2. 备份 data
cp -a data data.backup-$(date +%F)

# 3. 更新源码
git pull --ff-only origin main
# 或：下载 v1.16.0 zip，覆盖程序文件但保留 data/、.env、docker-compose.yml 的自定义配置

# 4. 重建并启动
docker compose build --pull
docker compose up -d

# 5. 检查
docker compose logs -f --tail=50
curl http://127.0.0.1:8765/api/health
```

`./data` 是宿主目录，重建镜像不会删除它。不要使用 `docker compose down -v`。

### 方式 D：Windows 一键包更新

1. 关闭旧服务窗口。
2. 下载 v1.16.0 zip，解压到新目录。
3. 把旧目录的 `data` 文件夹复制到新目录。
4. 把旧的 `.env` / 自定义启动参数带过去。
5. 双击新目录的 `deploy\one-click-deploy.bat` 或 `launch-desktop.bat`。
6. 打开页面，确认版本 1.16.0；旧目录留作回滚。

### v1.16.0 的配置变化

- 运行设置从“多个免费/付费策略开关”简化为 **直接选择翻译接口**；手动翻译和浏览自动翻译使用同一个接口。
- 旧的 `free_only`、`fallback`、`local_first`、`auto_paid` 字段会被忽略，并在下次保存时清理。
- 旧配置里的 `libre_key` 会在保存时迁移到新的 provider 结构。
- 如果旧配置是 `libre` 但 `libre_url` 为空，页面会显示“未配置”；请填 LibreTranslate 地址，或改选 DeepL / OpenAI 兼容 / MyMemory 等接口。
- 本版本没有数据库 schema 迁移；`data/news.db` 可以直接沿用。
- API Key 只保存在 `data/customization.json`，读取接口只返回是否已保存，默认导出不含密钥。

---

## 6. 更新后验证清单

```bash
curl -fsS http://127.0.0.1:8765/api/health
```

- [ ] 返回 `version` 为 `1.16.0`
- [ ] 首页能打开，新闻列表正常
- [ ] `customize.html#runtime` 能打开
- [ ] 运行设置只剩“翻译接口”下拉框，没有旧的免费/付费策略开关
- [ ] 当前接口显示“已配置”；Key 字段显示“已保存”（空白是掩码，不是丢失）
- [ ] 点“测试当前接口”后按钮显示“测试中…”，随后出现成功/失败结果
- [ ] 浏览器如果仍显示旧界面，按 **Ctrl+F5** 强制刷新
- [ ] `docker compose logs` / `journalctl` 没有持续报错

---

## 7. 回滚

### zip / systemd

```bash
sudo systemctl stop global-news-timeline
sudo mv /opt/global-news-timeline /opt/global-news-timeline-new
sudo mv /opt/global-news-timeline-old /opt/global-news-timeline
sudo systemctl start global-news-timeline
```

数据仍在 `data/`；v1.16.0 没有改数据库 schema，旧版本可以继续读取。

### Docker

```bash
docker compose down
docker compose up -d --build
# 或者把旧镜像 tag 回来，再 up -d
```

如果更新前备份了 `data`，回滚后再按需恢复。

---

## 8. 对外访问与安全

默认 `HOST=127.0.0.1`，只允许本机访问。需要局域网 / 公网时：

1. 最好让反向代理指向 `127.0.0.1:8765`，不要直接把 Python 服务暴露到公网。
2. 设置 `ADMIN_TOKEN`，自定义中心写操作需要 `X-Admin-Token`。
3. 在反向代理层加认证（Nginx Basic Auth、Tailscale、Cloudflare Access 等）。
4. 限制或保护 `/api/translate`：它为了首页自动翻译不要求管理员令牌，配置付费 Key 后，任何能访问服务的人都可能消耗你的额度。
5. 定期备份 `data/news.db` 和 `data/customization.json`。
6. `data/customization.json` 权限建议 `600`，不要提交到 Git、不要发给别人。
7. 不要把 `ADMIN_TOKEN` 写进公开的 Compose 文件或截图。

---

## 9. 常见问题

### Python 未找到

安装 Python 3.10+，Windows 安装时勾选 **Add Python to PATH**。Linux 确认 `python3 --version`。

### 端口被占用

服务会自动尝试 8766–8784；也可以显式设置：

```bash
PORT=9000 python3 server/app.py
```

Windows：

```bat
set PORT=9000
python server\app.py
```

### 页面打不开 / 更新后还是旧界面

1. 确认 `/api/health` 返回 `1.16.0`。
2. 浏览器按 **Ctrl+F5**。
3. 检查是否有多个 Python 进程占用不同端口：

```bash
# Linux/macOS
ps aux | grep 'server/app.py'
# Windows PowerShell
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'server\\app.py' }
```

### 翻译测试没有反馈

1. 确认已保存运行设置。
2. 确认当前接口显示“已配置”。
3. 按 Ctrl+F5 加载新 JS。
4. 打开浏览器 F12 → Console / Network，查看 `/api/translate` 的响应。
5. 如果是 DeepL/OpenAI 等外部接口，检查 Key、额度、网络和 Base URL。

### Key 输入框看起来是空的

这是安全设计：保存后只返回 `key_set`，不回显明文。字段旁会显示“已保存”，占位文字为“已保存，留空保持不变”。留空保存不会覆盖旧 Key；要删除请勾选“清除该接口已保存的密钥”。

### Docker 数据没有保存

确认 `docker-compose.yml` 中有：

```yaml
volumes:
  - ./data:/app/data
```

不要使用 `docker compose down -v`；检查 `data/` 目录权限。

### 首次启动很慢

首次抓取通常需要 1–2 分钟，取决于信源响应；页面会先显示骨架屏。可以看 `/api/health` 或服务日志确认抓取进度。

---

## 10. 可选：外部定时抓取

服务内置调度器，默认不需要额外配置。若想用 cron / systemd timer / NAS 任务：

```bash
python3 scripts/ingest_once.py
```

它只跑一轮抓取后退出；Web 服务可以单独常驻或只做只读展示。

---

## 11. 版本与校验

```bash
# Linux
sha256sum global-news-timeline-v1.16.0.zip

# Windows PowerShell
Get-FileHash .\global-news-timeline-v1.16.0.zip -Algorithm SHA256
```

当前版本：

```text
SHA256 9fdf2abaee78a898f25799b2467eae11588570e78cd40409d7cc3093349f8f80
```

下载页：<https://github.com/ybw-ly/global-news-timeline/releases/tag/v1.16.0>
