# Zepp Grafana 健康看板

`dashboards/zepp-health.json` 可直接导入，也可由现有 Grafana 文件 provisioning 加载。
本目录只提供配置，不会修改正在运行的 Grafana 或 VictoriaMetrics。

## 直接导入（复用现有数据源）

1. 在 Grafana 安装官方 **VictoriaMetrics** 插件，插件 ID 为 `victoriametrics-metrics-datasource`。
2. 已有该类型数据源时直接复用；新建时填写集群查询地址 `http://vmselect:8481/select/0/prometheus`（tenant 0）。这必须是 **Grafana 容器可达**的地址。
3. 在 **Dashboards → New → Import** 上传 `dashboards/zepp-health.json`。
4. 导入后，在看板顶部「数据源」下拉框选择已有的原生 VictoriaMetrics 数据源，再选择账户（默认 `personal`）并保存。
   下拉框使用数据源变量，不要求已有数据源使用本项目 UID；勿选择 Prometheus 类型的数据源。

## 文件 provisioning（复用现有挂载）

现有宿主机 provisioning 目录为：

- `/mnt/RapidPool/DockerStacks/stacks/homelab/grafana/provisioning/datasources`
- `/mnt/RapidPool/DockerStacks/stacks/homelab/grafana/provisioning/dashboards`

将本目录 `provisioning/datasources/zepp.yaml`、`provisioning/dashboards/zepp.yaml` 分别放入以上目录，保留其他服务的文件。
若已手动配置数据源，可只安装 dashboard provider，在看板中选择现有数据源。
数据源 provisioning 默认创建 `Zepp VictoriaMetrics`，固定 UID 为 `zepp-victoriametrics`，不会设为全局默认。

现有 Grafana 已将宿主机 `homelab/grafana/panels` 挂载到 `/etc/dashboards`。
在宿主机 panels 目录中新建 `zepp-report` 子目录，放入 `dashboards/zepp-health.json`，即可对应 provider 的 `/etc/dashboards/zepp-report`，无需修改现有挂载。

在现有 Grafana 实例安装插件后，按现有运维流程重启该 Grafana 服务以加载数据源配置；dashboard provider 每 30 秒检查文件。
文件管理的看板请修改仓库 JSON；Grafana UI 的修改不会写回文件。

插件安装、数据源格式参考 [VictoriaMetrics 官方文档](https://docs.victoriametrics.com/victoriametrics/victoriametrics-datasource/)，provider 机制参考 [Grafana 官方 provisioning 文档](https://grafana.com/docs/grafana/latest/administration/provisioning/)。

## 数据语义与面板

- 顶部六张卡片：今日步数、距离、热量、睡眠评分、静息心率、平均压力。
- 心率与压力：设备观测数据，查询点回看 5 分钟；查看单日时可看到更多细节。
- 睡眠：总时长、深睡／浅睡／REM／清醒时长、评分。睡眠按醒来日期归档。
- 日常活动：步数、距离、热量的每日柱图。
- 训练：ATL、CTL、TSB、TRIMP、运动负荷、周负荷、最佳区间、VO₂ max；保留负 TSB。
- 同步：待同步任务、失败任务、认证状态、导出积压、冲突和距上次成功的时间。

所有查询按 `account` 过滤。无数据保持为空，不用零替代。
历史 `*_daily` 是每天本地零点的一条汇总；使用 `last_over_time(...[1d])` 并校验原样本仍属于查询点的同一天，避免缺失日沿用前一天。
历史查询最小步长为 `1d`，较大 `maxDataPoints` 保留日粒度，柱图不连接空白。
`*_current` 卡片使用 `@ now()` 的即时查询和当日零点过滤；选择历史范围也仍展示真正的今日快照，昨天的旧快照不会混入今日。
同步状态只回看 3 分钟，导出器停止后呈现未知而不是永久显示正常。

本看板日界线固定为 **Asia/Shanghai (UTC+8)**，与默认应用时区一致。
原生插件应支持按看板 UTC offset 对齐范围查询；用 Query Inspector 确认每日查询 `step=86400`，`start` 为上海时间零点。
当前环境已安装该原生插件 0.24.0，并包含 `utcOffsetSec` 支持；本次没有修改或重启现有 Grafana。
旧版插件若忽略时区对齐，请升级；否则图上采样时刻可能为上海时间 08:00。
修改应用时区时，须同时修改看板 `timezone`、查询中的 `28800` 和目标的 `utcOffsetSec`；有夏令时的时区还需专门处理日长变化，不能只替换固定偏移量。
[MetricsQL 的 rollup 和时间函数说明](https://docs.victoriametrics.com/victoriametrics/metricsql/)描述了这些查询的基础语义。

## 保留期与重建

现有 VictoriaMetrics 保留期为 **180 天**。看板不能恢复已经超出保留期的数据；SQLite 原始归档是长期历史来源。
通过应用的归档导出器导出 SQLite 历史，再导入到**新 tenant**，然后为该 tenant 新建／修改 Grafana 数据源。
集群导入地址为 `http://vminsert:8480/insert/<新tenant>/prometheus/api/v1/import`，查询地址对应 `http://vmselect:8481/select/<新tenant>/prometheus`。
重建时目标 VM 保留期也必须覆盖所导出的历史，否则旧样本可能立即被丢弃。
既有 tenant 中相同时间戳的修正可能冲突，不应假设重复导入能安全覆盖。
本项目不会自动删除 VM 数据；不要为重建清空已有 tenant。

## 校验

```sh
python3 -m pytest tests/test_grafana.py -q
```

测试验证指标与导出 schema 一致、全部日报指标覆盖、账户过滤、稀疏数据与跨日保护、原生数据源配置以及面板布局。
配置文件检查不替代真实 Grafana 插件渲染验收：部署后还需检查数据源连接、账户选项，以及有数据／缺失日的查询结果。
