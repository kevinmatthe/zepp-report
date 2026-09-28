# Zepp Grafana 看板

本目录提供原生 VictoriaMetrics 数据源配置和 `dashboards/zepp-health.json` 健康看板。既可随仓库的一体化 Compose 启动，也可导入已有 Grafana。

## 可选的一体化 Grafana

先完成根目录 [部署配置](../README.md)，再启用 profile：

```sh
sudo install -d -m 700 -o 472 -g 472 grafana-data
chmod -R a+rX grafana
docker compose --profile grafana pull
docker compose --profile grafana up -d --no-build
```

服务名为 `zepp-grafana`，profile 名为 `grafana`；端口映射或服务级命令应使用服务名。默认拉取已发布镜像，无需本地构建。

Compose 自动安装 `victoriametrics-metrics-datasource` 原生插件，并通过 provisioning 加载数据源和看板。插件首次安装需要网络。数据源通过 `VM_QUERY_URL` 配置，默认指向同网络的 `http://zepp-vm:8428`，UID 为 `zepp-victoriametrics`，不会设为 Grafana 全局默认。

默认仅 expose 容器端口 `3000`，没有宿主机端口。自行添加端口映射或反代后访问。初始用户名为 `admin`；密码为 `GRAFANA_ADMIN_PASSWORD`，未配置则使用 `ADMIN_PASSWORD`。已有 Grafana 数据库不会随环境变量自动重置密码。

`./grafana-data` 持久化 Grafana 数据，属主 UID/GID 为 `472:472`。仓库中的 `grafana` 配置目录须对容器 UID 472 可读，可执行 `chmod -R a+rX grafana`；该目录仅放公开配置，不放凭据。若存在继承 ACL，检查其是否阻止读取或目录遍历。不要对 `.env` 或持久数据目录执行此公开权限命令。看板文件由仓库管理；界面编辑不会写回 JSON。修改仓库文件后由 provider 定期重载。

## 使用已有 Grafana 或外部 VM

1. 安装插件 `victoriametrics-metrics-datasource`。
2. 创建该类型的数据源，填写 **Grafana 容器可达**的查询根地址。单机示例：`http://zepp-vm:8428`；集群示例：`http://vmselect:8481/select/0/prometheus`。不要填写导入端点。
3. 在 **Dashboards → New → Import** 上传 `dashboards/zepp-health.json`。
4. 在顶部「数据源」选择原生 VictoriaMetrics 数据源，并选择与应用 `ZEPP_ACCOUNT` 一致的账号标签。

不要求已有数据源使用本项目 UID。使用文件 provisioning 时，将 `provisioning/datasources/zepp.yaml` 与 `provisioning/dashboards/zepp.yaml` 挂载到 Grafana 对应 provisioning 目录，将看板目录挂载到 provider 指定的 `/etc/dashboards/zepp-report`。仓库数据源配置使用 `${VM_QUERY_URL}`，使用外部 VM 时应设置 Grafana 容器的该环境变量；复制到已有 Grafana 时也可改为实际查询地址，不要覆盖其他项目配置。

## 面板与数据含义

看板包含今日概览、活动与步数、心率/压力/血氧、睡眠、训练及同步状态，使用原生 Stat、Time series 和 Row 面板。

- 今日卡片固定展示今天，不随历史时间范围改变；旧快照不会冒充今日数据。
- 日报按本地日期展示，缺失日期保持空白。实际睡眠与包含清醒或缺段的记录跨度不同。
- 心率与压力 P10/P50/P90 使用前 24 小时原始观测的滚动分位数，最小查询步长 1 小时；不是 Web UI 自然日统计。
- 分钟明细每条序列目标约 2000 点，最小区间 1 分钟。步数使用区间求和，心率、压力和血氧使用区间均值、最低值和最高值；长范围自动增大区间，放大到单日恢复分钟精度。
- 缺失区间不补零，真实零步数保留；时间戳保护避免旧值延续到没有观测的区间。完整原始时间和值可在 Web UI 单日分页表查看。
- `zepp_steps_minute` 是该分钟步数，不是累计 counter。日常活动片段与运动记录分别统计，不能直接相加。
- 训练保留负 TSB；未识别字段和未采集数据不构造虚假值。所有健康查询按 `account` 过滤。
- 同步状态只回看短时间窗口，导出器停止后显示未知。HTTP 投递成功并不证明 VM 已持久保存；读回核对、补投和冲突状态以 Web UI 同步页为准。

看板日界线固定为 **Asia/Shanghai (UTC+8)**。原生插件须支持 `utcOffsetSec`；通过 Query Inspector 检查日报 `step=86400`、起点为当地零点。修改应用时区时，应同时调整看板时区、查询中的固定偏移 `28800` 和目标 `utcOffsetSec`；夏令时区域还需处理日长变化。

不要将分钟面板 `maxDataPoints` 大幅提高以强行返回长范围原始点；实际查询步长受插件取整影响，可能超过 VM 每序列点数限制。应缩短时间范围或保持自适应区间聚合。

## 保留期、冲突与恢复

内置单机 VM 默认保留 **3650 天（10 年）**，由 `VM_RETENTION_DAYS` 控制，容器内存上限 `VM_MEMORY_LIMIT` 默认为 `512m`；外部 VM 必须自行配置实际保留期。超期日期在应用中属于正常过期，不是同步失败。SQLite 原始归档仍保留，但看板无法查询已经被 VM 删除的样本。

应用周期读回并补投缺失样本；同时间戳值冲突不会通过删除历史自动解决。重建时从 Web UI 导出所需完整日期区间，导入保留期足够的新实例或新租户，核验后切换数据源。推荐截止昨天，避免进行中的当日汇总。不要通过清空共享 VM 修复单个账号。

备份与恢复遵循根目录说明；SQLite 在线备份不包含 VM 或 Grafana 数据。持久目录冷备份前停止相应服务。

## 故障排查与校验

先检查数据源连接、账号标签和时间范围，再使用 Query Inspector 查看实际查询。HTTP 422 可由点数上限或查询参数造成；不要先把缺失替换为零。旧插件忽略时区偏移时升级原生插件。插件安装失败时检查 Grafana 容器日志和网络；目录写入失败时检查 UID 472 权限。

```sh
python3 -m pytest tests/test_grafana.py -q
```

配置测试覆盖指标 schema、账号过滤、缺失与跨日保护、原生数据源、布局和聚合口径。可选真实插件回归：

```sh
python3 scripts/integration_grafana.py \
  --image <本地Grafana镜像> \
  --plugin-dir <已安装VM插件目录> \
  --network <Docker网络> \
  --vm-url <VM查询地址>
```

该脚本创建隔离临时 Grafana，只读查询目标 VM，不发布宿主机端口，结束后清理测试资源。配置测试不能替代真实插件与数据源验证。

参考：[VictoriaMetrics 原生数据源](https://docs.victoriametrics.com/victoriametrics/victoriametrics-datasource/)、[Grafana provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/)、[MetricsQL](https://docs.victoriametrics.com/victoriametrics/metricsql/)。
