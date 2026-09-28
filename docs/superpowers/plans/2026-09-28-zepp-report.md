# Zepp Report Implementation Plan

**Goal:** 定期归档 Zepp 健康数据，提供中文 UI 和 VictoriaMetrics/Grafana 集成。
**Architecture:** 单实例 Python 服务、SQLite 事务与持久队列、后台同步、同源静态 UI。
**Tech Stack:** FastAPI、requests、SQLite、原生 JavaScript/SVG、Docker Compose。

在当前新建功能分支执行；用户已批准设计并要求开始实现，不再为执行步骤重复确认。独立 UI 工作按 subagent-driven-development 技能委派，其余在主会话实现。

- [x] 1. `tests/test_normalize.py` 先覆盖 Base64 心率、缺失读数、Asia/Shanghai 日期边界、跨日睡眠、压力和训练字段。运行 `.venv/bin/python -m pytest tests/test_normalize.py -q` 观察失败，实现 `zepp_report/normalize.py` 后通过。
- [x] 2. `tests/test_store.py` 覆盖 SQLite upsert、原始响应存档、事务入队、重复同步、历史修订、重启任务恢复。实现 `zepp_report/store.py`，使用唯一键及 WAL。测试数据库使用临时路径。
- [x] 3. `tests/test_client.py` 以本地假响应验证 Token 失效、超时/限流重试、业务错误、分页保护与时区。实现 `zepp_report/client.py`，记录原始响应并按日请求，事件超限时拆分时间窗口。
- [x] 4. `tests/test_sync.py` 覆盖首次回填、部分失败、失效暂停、更新凭据后恢复、VM 故障后重试。实现 `zepp_report/sync.py`、`settings.py`、`metrics.py`，确认不重叠运行。
- [x] 5. `tests/test_api.py` 覆盖登录、配置不回显 Token、非法日期/区域、CSRF、同步提交、API 结果。实现 `zepp_report/app.py`；先定义 UI 使用的 API 合约再实现前端。
- [x] 6. `zepp_report/static/{index.html,app.js,style.css}` 实现登录、概览、图表、同步、设置，按 375/768/1440px 验证；只显示 API 真实数据或明确空状态。
- [x] 7. `grafana/` 生成数据源 provisioning 与看板 JSON，检查指标与后端映射一致，稀疏日指标使用显式回看窗口。
- [x] 8. `Dockerfile`、`compose.yaml`、`.env.example`、`README.md`、`THIRD_PARTY_NOTICES.md`：固定依赖，提供 Traefik、持久化、备份和导入说明。配置不包含真实凭据。
- [x] 9. 完整 pytest、JS 语法、Compose config、Docker build、隔离 VM 写入查询、浏览器交互检查；进行规格与代码审查，修复后复测。没有真实 Token 不声称真实账号已验证。

## UI API 合约

- `POST /api/login` `{password}` → `{ok:true}` 设置 HttpOnly 会话 cookie；`POST /api/logout`。
- `GET /api/settings` → `{user_id,account,region,timezone,interval_minutes,initial_days,lookback_days,token_configured,configured,vm_url}`。
- `PUT /api/settings` 接受 `{user_id,region,timezone,interval_minutes,initial_days,lookback_days,token}`；空 token 保持原值。账号别名由环境配置，已有数据时 user_id/timezone 不允许变更。
- `GET /api/status` → `{configured,auth_required,worker_alive,last_success,next_sync,pending_exports,conflicts,vm_error,tasks:{pending,running,failed,done},recent_tasks:[{day,kind,status,error,updated_at}]}`，时间为 Unix 秒或 null。
- `POST /api/sync` `{from_date,to_date}`（两个都省略表示最近几天；显式日期默认跳过成功项，`force:true` 强制重新获取）→ `{queued}`，日期 ISO 格式。
- `GET /api/data?from_date=YYYY-MM-DD&to_date=YYYY-MM-DD` → `{timezone,days:[{date,heart_rate:[{time,value}],stress:[{time,value}],summary:{steps,distance_meters,calories,sleep_score,sleep_minutes,resting_hr,stress_avg,atl,ctl,tsb,trimp,sport_load,weekly_load,vo2_max},sleep_stages:[{start,end,stage}],updated_at}]}`；采样/阶段时间均为 Unix 毫秒，缺失汇总键省略。
- `GET /api/export?from_date=...&to_date=...` 下载当前归档的指标 JSONL，用于新租户的修订重建。
- 401 显示登录；其他错误 JSON `{detail:中文或可理解消息}`。

## 验证记录

- 41 项 pytest 通过（含备份/恢复、凭据更新中断、临时磁盘故障、历史修订、看板检查）。
- 隔离 VM 三组件集群：真实 JSONL 写入/查询、丢失确认后重启重试、34 条看板表达式、跨日缺失值检查通过。
- 浏览器 fixture 和真实 API 的登录/配置/回溯/退出通过；375–1440px 响应式与12万采样绘图检查通过。
- Docker 镜像与 Compose 构建通过；隔离非 root 容器的健康检查、登录、任务恢复、重启与在线备份均通过。
- 已完成独立规格/代码复核；未连接真实 Zepp 账号、未部署到现有 Traefik/Grafana 实例。
