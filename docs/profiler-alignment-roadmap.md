# xsai-prof：对齐 NCU / MindStudio 算子分析能力

2026-10-26：根据用户调整，下一阶段优先完善 xsai-prof 的独立使用与算子分析
能力。按需 profiling 与研究对照保留为后续工作，不再作为下一阶段主验收目标。
本 goal 已完成，五项首批功能、独立安装、离线 fixture、三类算子历史真实
证据复核和安装版非空 softmax RTL 采集均通过验收。最终状态与证据见
[验收说明](profiler-alignment-results.md)。

0.4.0 后续扩展另见[夜间交付与边界](profiler-night.md)，包括调用/阶段、事件选择、
任务恢复、可迁移证据、统一分析、实测参考模型和经同次锚点验证的时钟关联。
0.5.0 进一步增加采集端 lifetime 调用/阶段过滤和实际 AME 接口观测，
见[范围与访存说明](profiler-memory.md)及[当前验收](https://github.com/LeleCheung/XSAI-KDA/blob/main/reports/profiler-memory/README.md)。
以下首批验收保留其0.2.0时期的范围。

## 0.5.0 之后的缺口

- 当前实际流量只覆盖 AME near_cute 接口；CPU/RVV 的实际请求、有效字节和
  读返回旁路尚未覆盖。FA 的 V 复用可以用动态指令核对，仍不能报告 RVV 实测字节收益。
- 读返回、完整延迟和 outstanding 需要补观测点与配对协议；不能由 Get 请求数推算。
- 端到端 DRAM 流量、缓存层级命中/未命中和带宽利用率需要各层独立观测与校准，
  不能由当前接口字节换名得到。
- 当前保留跨范围任务和写完成上下文；按时间重叠尚不能分配指令所有权或判定关键路径。
- 范围过滤已减小 DB，但完整 CUTE/接口事件仍保留；后续降低采集成本需要继续验证
  异步任务边界与证据完整性，不能直接截断全部事件。

优先补齐 CPU/RVV 访存和读返回证据，再讨论硬件利用率、瓶颈归因与自动评分。
这份缺口列表是后续候选方向，不将新工作隐式加入当前 goal。

## 参照范围

- NVIDIA Nsight Compute：参考 CLI 的 metric/section/set 查询与选择、算子调用
  筛选、采集/导入/导出，以及已有源码关联与对比工作流。
- MindStudio msProf：参考统一采集、解析和报告的使用方式。
- MindStudio msOpProf simulator：更直接对应本项目的仿真算子分析场景。官方
  README 明确区分真机和 simulator 模式，提供算子性能采集与自动解析。

这是能力和交互方式的对齐，不承诺兼容其文件格式或命令参数。XSAI 指标仍以
自身 RTL 事件定义为准；GPU occupancy、warp 等概念不直接移植。

## 当前起点

已实现 collect/report/compare/diagnose，可独立于 agent 使用；但命令分发、
适配器和部署仍依赖当前项目。已具备 perf/HPM/ChiselDB 数据绑定、源码与
汇编关联、分区报告、CUTE scope 和基线对比。以下能力已在此基础上补齐，当前部署支持独立安装。

## 首批交付

| 顺序 | 能力 | 拟交付与边界 |
| --- | --- | --- |
| 1 | 独立安装与环境检查 | 安装后可直接执行 xsai-prof；离线分析不依赖 skill，RTL 采集明确检查其外部依赖。Python 可继续作为实现，不要求 native binary |
| 2 | 指标目录与采集分区 | 查询 metrics/sections/sets；为每个指标标注来源、单位、统计范围、所需配置与不可用原因；按分区选择所需采集 |
| 3 | ROI/阶段选择与时间线 | 对指定调用/ROI 与受支持的 CPU/RVV/AME 事件生成时间线；标明各轨的时钟/范围，缺少可靠时间戳时不绘制伪时间或推断重叠 |
| 4 | 分区报告与对比完善 | 汇总 cycles、已验证 HPM、热点、源码/汇编和可观测 CUTE 阶段；分别展示未插桩性能与插桩诊断，保留证据校验 |
| 5 | 多 shape 批处理 | 对一组实现/shape 执行或导入采集，输出收益/退化/失败矩阵及 JSON/CSV/HTML，隔离构建和测量冲突 |

时间线复用已保存的 LifeTimeCommitTrace 与 CUTE 事件，提供函数/CPU commit
周期和 CUTE stage/SEQID 筛选；CPU/CUTE 独立时钟绘制。未增加任意函数独占
计时，不推断两个引擎的统一时钟或关键路径。

## 验收

1. 在独立环境安装并执行帮助、环境检查、离线报告与已有 collect 流程；保留
   旧命令兼容路径。
2. 使用可随仓库分发的测试样例验证指标查询、缺失/不支持事件、ROI 范围、
   时间单位、跨轨时钟和比较可比性；不能依赖本机被忽略的原始产物完成安装。
3. 复用 FA/GEMM/softmax 原始证据检查新报告与原数据一致，明确这些证据未随
   Git 完整分发；仅在新增采集能力需要时安排最小真实 RTL 验证。
4. 多 shape 结果逐项区分成功、退化、失败和未测，不改变原有正确性与最终
   性能验证标准。工具测试与算子性能验收分别报告。

首批不以新算子加速比或研究方法优越性作为验收条件。Roofline、带宽利用率
与自动瓶颈评分待有明确的硬件上限、流量事件和校准后再纳入。

## 官方依据

官方页面原文与抓取哈希保存在
[来源记录](research-sources/20261026/profiler-alignment/retrieval.json)：
NCU CLI、Ascend msProf README、Ascend msOpProf README 和 simulator 使用指南。
对照基于本次成功抓取的版本，不表示已复现这些工具或建立完整功能等价。


## 0.6 CPU/RVV ordinary memory boundary

The next observed boundary is implemented: actual scalar/RVV LoadUnit request
masks, L1 status pairing, PMA store enabled lanes and separate merged sbuffer
completion masks. See [coverage and acceptance](profiler-cpu-memory.md).
This does not supply DRAM bytes, architectural load latency or complete memory
coverage. Real negative captures and partial RVV source attribution stay explicit.

## 0.7 beta：独立发布与 AME 读返回

已完成可独立安装的 wheel/sdist、init/doctor 配置与支持范围说明、AME
matrix_data_in 实际读返回、接口服务延迟/outstanding，以及统一分析总览。
总览区分已观测变化与带验证实验、预测和反证条件的待验证假设。
真实报告可导出、迁移和重新分析，独立诊断回放保留原始性能身份。

145 项软件测试、FA/GEMM 四组真实 RTL 回放、精确 wheel 清洁安装与项目外
全新采集验收通过。见[0.7 交付说明](https://github.com/LeleCheung/XSAI-KDA/blob/main/reports/profiler-release/README.md)、
[验收记录](https://github.com/LeleCheung/XSAI-KDA/blob/main/reports/profiler-release/acceptance.json)和
[安装指南](profiler-quickstart.md)。未执行公开发布或推送。

剩余边界包括 DRAM/缓存各层流量、架构指令延迟、完整 CPU/RVV 覆盖及通用
硬件利用率模型；本版不宣称与 NCU/msOpProf 全功能等价，也不新增算子加速比。

## 0.8 beta：CLI 与离线报告工作流

已完成指标发现别名、统一 `-o`、只读 `collect --dry-run` 采集计划、按
metric/section/set 选择实际采集模式，以及筛选后的 text/JSON/CSV 报告。
`view` / `report REPORT` 读取既有证据，`open` 校验后打开离线分析页面。
现有 HTML 增加访存表格/图形、源码搜索、范围与时间线交互、比较、未知值
和带预测/反证条件的待验证实验。

155 项软件回归、干净安装、历史真实 FA/GEMM 报告复核、项目外全新 RTL
流程及三份报告的真实 Chromium 验收均通过。实际采集 64 B AME 读返回、
7 cycle 接口服务时间、峰值 1 个未完成读请求；共 4 次 emulator 调用。
最后修正只涉及离线 UI CSS，最终包与采集包的采集代码哈希一致；最终包
已复验报告、比较、迁移和 resume，保留原采集身份与全部失败记录。

见 [0.8 交付说明](https://github.com/LeleCheung/XSAI-KDA/blob/main/reports/profiler-cli/README.md)、
[验收记录](https://github.com/LeleCheung/XSAI-KDA/blob/main/reports/profiler-cli/acceptance.json)和
[CLI 工作流](profiler-cli-workflow.md)。本轮 goal 已闭合；安装包位于 dist/。
未公开发布或推送，不新增算子加速结论。原有 DRAM、完整 CPU/RVV 覆盖、
指令延迟与硬件利用率边界仍适用。
