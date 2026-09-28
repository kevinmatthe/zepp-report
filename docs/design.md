# Zepp Report 设计草案

状态：用户已确认整体设计及 Token 接入方式；实现与验证已完成，真实 Zepp 账号接入待配置凭据。

## 目标与范围

单个 Zepp 账号的定时健康数据同步、持久化、中文 Web UI，以及使用 VictoriaMetrics 的 Grafana 数据源配置与看板。首版覆盖上游已有接口：心率、睡眠阶段与评分、步数、距离、热量、压力、训练负荷、TRIMP、运动负荷和 VO2 Max。设备未提供的数据展示为空，不合成为零。血氧、体温等上游尚未实现的接口不承诺支持。

## 已确认环境

- 开始时仓库只有 README；现已实现应用、部署配置及测试。
- 参考实现：https://github.com/EvanCooke/zepp-export，MIT 许可；复用代码须保留许可及出处。
- VictoriaMetrics 配置：`/mnt/RapidPool/DockerStacks/stacks/victoria/vm.compose.yaml`。
- 集群使用 `vminsert:8480`、`vmselect:8481`，现有租户为 0，保留期 180 天，去重间隔 15 秒。
- Grafana 与 VictoriaMetrics 已运行于 `homelab-v2` 外部网络。
- Grafana 已有数据源 provisioning 和 dashboard bind mounts，可交付独立配置及导入文件。

## 方案比较与推荐

1. SQLite 存档 + VictoriaMetrics 指标：推荐。原始响应、结构化数据、同步状态和待发送记录有持久化保障；Grafana 使用既有时序系统。
2. 全部只存 VictoriaMetrics：组件更少，但不适合原始响应、同步任务和需要修订的业务记录，且目前只保留 180 天。
3. PostgreSQL + VictoriaMetrics：适合未来多用户场景，当前单用户增加独立数据库的运维成本。

## 组件与数据流

Python 后端提供 Zepp 适配器、同步调度、SQLite 存储、VictoriaMetrics 推送器和 Web API；同一服务交付中文 Web UI。首次默认回填最近 30 天，随后每 30 分钟同步最近 3 个自然日，允许修改间隔和手动指定补数日期。手动回溯默认跳过已完成项，支持强制重取与仅重试失败项；任务持久化并在重启后续传。使用可配置的 Asia/Shanghai 时区，修正参考实现中固定 America/Chicago 及依赖进程本地时区的行为。

Zepp → 原始响应及规范化记录入 SQLite → 持久化待发送队列 → VictoriaMetrics → Grafana。UI 从本地 API 查询归档数据与任务状态。数据库持久化在明确的 bind mount 中；服务采用单调度实例，防止手动与自动同步重叠。

写入地址：`http://vminsert:8480/insert/0/prometheus/api/v1/import`，使用 JSON Lines 与原始采样时间戳。查询数据源 URL：`http://vmselect:8481/select/0/prometheus`。地址与租户均可配置。

指标统一使用 `zepp_` 前缀，标签只保留账号别名、指标分类等有限维度，不放凭据、原始 JSON 或每次同步的唯一 ID。日指标按业务日期生成稳定时间戳；心率和压力保留采样粒度。跨午夜睡眠按醒来日期归属，并保留各阶段真实时间段。

SQLite 使用唯一键更新业务记录。VM 发送采用至少一次交付，承认网络超时重试可能重复；不把现有 VM 去重当成数据库更新机制。可变的当日汇总在 VM 中记录为同步时刻的快照，历史已结束日期的汇总按稳定业务时间发送；看板明确区分日汇总与原始采样，不对每日总数使用 rate。上游修订导致的历史指标重建必须显式处理，不能声称重复导入能可靠覆盖旧值。

## 认证与错误处理

用户已确认首版手动配置 Token、用户 ID、区域，并在 UI 更新 Token。参考仓库没有自动续期保证。Token 不回显，不写日志或示例，凭据文件限制权限，管理 UI 提供认证。

请求设置超时；网络故障及限流有界退避；Token 失效暂停对应同步并在 UI 明示。按日期和数据类型记录完成状态，部分失败可重试，不能把失败标记成空数据或成功。VM 故障不影响已获取数据归档，待发送队列恢复后重试。

## Web UI 和 Grafana

UI 包含健康概览、日期范围、心率/压力趋势、睡眠阶段、活动与训练负荷，以及同步状态、立即同步、历史补数、配置入口。缺失和异常状态单独显示。

Grafana 交付 VictoriaMetrics 原生数据源 provisioning 配置与可导入看板 JSON；看板包含健康总览、睡眠、活动、训练及同步运行状态。数据源 UID 可配置。采样稀疏的日指标按合理查询窗口展示，避免默认回看窗口导致空面板。

## 部署与验证

交付 Dockerfile、Compose、环境变量示例和部署说明。遵循 stacks/AGENTS.md：接入 homelab-v2、Web 经 Traefik 的 zepp-report 子域名前缀访问、默认不映射宿主机端口、明确持久化挂载。不更改共享 VictoriaMetrics 的保留期或重建现有服务。

验证涵盖真实格式样例解码、时区和跨日睡眠、增量同步与断点恢复、Token 失效、缺失数据、VM 失败重试和时间戳/单位转换。使用隔离测试依赖验证写入与查询、UI 构建与基本交互、Compose 静态校验。缺少真实 Zepp 凭据时，清楚区分离线验证与真实账号端到端验证。
