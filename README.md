# Zepp Report

定期把 Zepp 健康数据归档到 SQLite，提供中文 Web UI，并将指标写入已有的 VictoriaMetrics，供 Grafana 看板查询。
参考 [EvanCooke/zepp-export](https://github.com/EvanCooke/zepp-export) 的接口及编码格式；许可与参考版本见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 功能

- 心率、睡眠阶段与评分、步数/距离/热量、压力、ATL/CTL/TSB、TRIMP、运动负荷的采集与展示。
- 默认每 30 分钟回看 3 天；首次回填 30 天，可在设置中调整。
- **手动历史回溯**：Web UI → 数据同步 → 历史补数，选择起止日期。默认跳过完成项；勾选「重新获取已完成数据」才强制重新请求。
- **可恢复**：任务按日期 × 接口持久化，断点续传、Token 失效暂停、失败项重试、VM 持久队列、在线备份。
- 中文响应式界面，支持日期范围、趋势、睡眠阶段、同步状态、凭据更新及 JSONL 导出。
- 原生 VictoriaMetrics Grafana 数据源与 28 个面板（含分区）的健康看板。

VO₂ Max 的接口会采集并保留原始响应，已识别 `vo2Max` 数值时展示；上游尚无确认的非空样例，不保证所有设备的 VO₂ 格式兼容。血氧、体温接口暂未实现。没有数据展示「—」，不会填零。客户端使用非官方接口，真实兼容性取决于账号区域和设备。

## Docker 部署

本仓库的 `compose.yaml` 已适配现有 `homelab-v2`、Traefik 和 VictoriaMetrics 集群；默认不映射宿主机端口。

```sh
cp .env.example .env
chmod 600 .env
# 编辑 .env：设置 ADMIN_PASSWORD（至少 12 字符）
install -d -m 700 -o 1000 -g 1000 data
docker network inspect homelab-v2
docker compose config --quiet
docker compose up -d --build
```

通过已有 Traefik 访问 `https://zepp-report.<你的域名>`，使用 `.env` 中的管理密码登录。域名需解析到现有 Traefik 入口，证书由现有配置覆盖；HostRegexp 路由不会自动创建 DNS。

第一次进入设置，填写 Zepp 用户 ID、Token 和区域。Token 获取方法见[参考仓库](https://github.com/EvanCooke/zepp-export#authentication)：登录 `user.huami.com` 后读取 `apptoken`。不要把凭据提交到 Git。Token 过期时页面提示，填写新 Token 后自动继续。

环境变量 `ZEPP_USER_ID`、`ZEPP_TOKEN`、`ZEPP_REGION`、`ZEPP_TIMEZONE` 仅用于没有 `data/settings.json` 时的初始配置；设置文件存在后，以 Web UI 保存值为准。默认时区 `Asia/Shanghai`，区域 `global`。已有归档后不允许改变用户 ID、区域或时区；不同账号应使用独立数据目录和账号标签。

主要配置：

| 配置 | 默认 / 用途 |
| --- | --- |
| `ADMIN_PASSWORD` | 必填，至少 12 字符；重启应用后生效 |
| `ZEPP_ACCOUNT` | `personal`，指标的账号标签；建立归档后保持稳定 |
| `VM_IMPORT_URL` | `http://vminsert:8480/insert/0/prometheus/api/v1/import` |
| `VM_BEARER_TOKEN` | 可选，写入端鉴权 |
| `COOKIE_SECURE` | `true`；仅本机 HTTP 开发设为 `false` |
| `DATA_DIR` | 容器固定 `/app/data`，宿主机 `./data` |

容器以 UID/GID `1000:1000` 运行。只需给本服务 `data` 目录对应权限，不要修改其他服务目录。只运行一个实例和一个 Uvicorn worker；数据目录有进程文件锁防止双调度。

本机 Docker 默认构建网络的 DNS 无法解析 PyPI，因此 `.env.example` 设置 `BUILD_NETWORK=host`，Compose 构建时直接使用宿主机网络。其他环境可设为 `default`。这只影响镜像构建时的联网方式，运行容器仍使用 `homelab-v2`。
构建阶段可继承当前 shell 的 `http_proxy` / `https_proxy`（或大写变量），使用 Docker 预定义代理构建参数，不写入运行容器环境或镜像配置。

## 回溯与恢复行为

| 场景 | 行为 |
| --- | --- |
| 服务重启、进程被终止 | SQLite 中未完成的任务继续；遗留 `running` 状态恢复为待处理 |
| 数据已存储但进程立刻终止 | 数据、指标待发送记录、完成检查点在同一事务提交；不会丢检查点 |
| 某天某类接口失败 | 该项保留为失败，其他任务继续；「重试失败项」或下个定时周期重试 |
| Token 失效 | 持久化暂停采集；VM 待发送队列仍可排空；更新 Token 后恢复失败与待处理任务 |
| 更新 Token 过程中重启 | 通过凭据指纹核对恢复状态，避免永久暂停 |
| VM 不可用 | 已采集数据仍在 SQLite；最多间隔 5 分钟退避重试；重启后待发送记录仍在 |
| VM 已接收、网络丢失确认 | 按原始时间戳重试相同样本，语义为至少一次交付；复用现有 15 秒去重配置 |
| 临时磁盘满／写入异常 | 页面显示后台错误；存储恢复后重新领取遗留任务，不需要手动修改数据库 |
| 再次提交相同回溯范围 | 默认只补未完成项；明确勾选强制时才重新采集完成项 |

每次 HTTP 请求有连接/读超时；网络错误、限流和服务端错误最多尝试 3 次。事件查询达到单页上限时拆分时间窗口；无法完整获取则记为失败，不把截断响应当成功。历史回溯一次最多 3650 天；UI 图表查询一次最多 366 天。

原始响应版本按内容去重保存；解析失败的原始响应也保留。数据库结构：`records` 最新规范化记录、`raw_versions` 原始响应、`tasks` 日期/类型检查点、`samples` 指标队列及投递状态、`metadata` 调度/认证状态。任务表显示每个日期/类型的最新状态，而不是每次运行的无限日志。

服务只会采集已同步到 Zepp 云端的数据，无法代替手环/手表与手机的同步。

## VictoriaMetrics 与 Grafana

- 应用直接推送带原始毫秒时间戳的 JSON Lines，不需要给 vmagent 增加健康数据抓取任务。
- Grafana 查询地址：`http://vmselect:8481/select/0/prometheus`。
- 配置及导入说明见 [grafana/README.md](grafana/README.md)。可以复用已有的原生 VictoriaMetrics 数据源，无需新建 Grafana。
- `zepp_heart_rate_bpm`、`zepp_stress` 保留采样时间。`zepp_*_daily` 为结束日期的日汇总，时间为该日零点；今天的数据使用独立 `zepp_*_current` 快照。每天补数时生成前一天的日汇总。
- `zepp_sync_*` 每分钟推送同步状态（正在执行的慢请求可能推迟刷新）；Grafana 对过期状态显示无数据。
- 标签只使用账号别名，不使用 Token、原始响应或每日唯一标签。睡眠阶段精确时间段保存在 SQLite，由 Web UI 展示；Grafana 展示阶段时长。

当前共享 VM 配置保留 **180 天**；SQLite 不自动删除历史。回溯更早数据仍会本地归档，VM 可能按保留期丢弃旧样本。应用不会改变共享 VM 的保留期。

**历史修订**：SQLite 更新为新值。如果同一个指标/时间戳已投递（或投递结果不确定），不会假设重复导入能覆盖旧值，而会增加「数据冲突」计数。Web UI 展示最新归档，Grafana 可能仍是旧值；两边因此可能不同。

需要重建时，用 Web UI 的「导出 JSONL」导出指定区间的最新归档，在有足够保留期的**新 VM 租户**中导入，并建立对应 Grafana 数据源。导出仅包含选定区间；若替换完整历史数据源，应导出所需的全部日期。导出不含同步遥测，并把当天现有汇总作为该日的部分汇总；推荐重建到昨天。应用不会删除共享库的数据，冲突计数不会因下载导出文件自动清零。

## 备份与恢复

在线备份使用 SQLite backup API，会包含 WAL 中已提交的数据及持久化任务队列：

```sh
docker compose exec zepp-report python -m zepp_report.admin backup /app/data/backups/2026-09-28
```

目标目录必须不存在。检查备份内 `BACKUP_COMPLETE`；备份包含 Token，妥善保管。把备份复制到另一块存储，并单独保管本地 `.env`（管理密码及启动环境配置不在数据库内）。不要在运行时只复制 `zepp.sqlite3` 而忽略 WAL。

恢复步骤：停止本服务，保留原 `data` 目录作为回退，在新 `data` 目录放入备份的 `zepp.sqlite3` 和 `settings.json`，调整为 UID/GID 1000、目录 700/文件 600，再启动。恢复后未完成任务继续；登录会话不恢复，需要重新登录。请勿复制正在运行实例的 `worker.lock`。正常停止/重启不会删除归档。

## 本地开发与验证

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
export ADMIN_PASSWORD='至少12字符的本地测试密码'
export COOKIE_SECURE=false
.venv/bin/uvicorn zepp_report.app:create_app --factory --host 127.0.0.1 --port 8000
```

```sh
.venv/bin/python -m pytest -q
node --check zepp_report/static/app.js
# 需要已安装 Playwright/Chromium，可通过环境变量指定路径：
PLAYWRIGHT_MODULE=/path/to/playwright CHROMIUM_PATH=/path/to/chrome node tests/ui_browser.cjs
# 可选真实 API 浏览器联调，仅对独立的测试实例运行（会写入测试账号配置）：
UI_LIVE_URL=http://127.0.0.1:18187 UI_LIVE_PASSWORD=test-password-long \
  PLAYWRIGHT_MODULE=/path/to/playwright CHROMIUM_PATH=/path/to/chrome node tests/ui_live_browser.cjs
# 隔离的三组件 VM 测试，复用本机已有镜像，不连接现有集群：
.venv/bin/python scripts/integration_vm.py
# 已构建镜像的非 root 运行、持久化重启和在线备份检查：
.venv/bin/python scripts/container_smoke.py zepp-report:local
```

测试覆盖解码、时区/跨日睡眠、事务与恢复、Token 更新中断、存储失败、VM 超时、同源写入限制、凭据不回显、备份恢复和看板指标。实际 Zepp 账号验证需要真实 Token；测试数据与浏览器 fixture 不代表真实账号已连接。
