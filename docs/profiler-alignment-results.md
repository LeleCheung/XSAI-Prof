# xsai-prof 产品化 goal 验收

当前状态：goal 已完成，最终验收通过 124 项检查；软件测试 78 项通过。

本阶段以工具交付为目标，参照 NCU 的 metric/section/set 与源码分析方式，
以及 msOpProf simulator 的仿真时间线/热点分析方式。没有新增算子优化，
也没有宣称功能等价或新的论文结论。

## 交付

| 项目 | 已实现 |
| --- | --- |
| 独立安装 | Python wheel/source distribution，安装入口 xsai-prof；analyzer 与上游 LICENSE 随包分发，离线不需要原工程、skill 或模型 |
| 环境检查 | doctor 检查离线资源；带 collection config 时验证外部 RTL、runtime 和编译器身份 |
| 指标/分区/集合 | query metrics/sections/sets；定义来源/单位/scope/所需模式/限制，带 report 时解析实际 HPM selector；basic/counters/detailed 或显式 sections 控制原生采集模式 |
| 分区报告 | 保留 JSON/MD/HTML、源码/汇编和基线对比，增加 metrics.json/sections.json |
| 时间线 | 对原 DB/ELF/ROI 再验证；CPU residence 与 CUTE task 分域展示，函数/commit周期、stage/SEQID 筛选，JSON/CSV/可缩放 HTML 和显式截断 |
| 批处理 | report/spec/collect 三种输入，各 shape 单独基线；顺序执行、失败保留，输出 JSON/CSV/HTML 结果矩阵 |
| 安装样例 | demo 生成随包可用的 synthetic fixtures，数值明确不能作为仿真结果；测试附有真实目标 ISA ELF + synthetic DB 生成方法 |

## 验证范围

- 软件测试覆盖旧命令、新指标缺失状态、集合选择、时间戳、截断、时钟独立、
  证据篡改、批处理不可比/失败/未测/退化等行为。
- 隔离安装检查先创建 sdist，再从 sdist 构建 wheel；在无 PYTHONPATH、项目外
  的独立 venv 中运行命令和 fixture 分析。
- 真实数据回放复用 FA/GEMM/softmax 已完成的 RTL 运行。新报告除输出链接外
  指标内容与历史报告一致，时间线保留 ROI 指令总数，批量对比保留历史收益与退步。
- 安装后 CLI 的小规模 RTL collect 另行记录；它只验证采集链路，不能用于
  宣称重复性能或新的优化加速比。

原始 DB/ELF/源码 ZIP 未随 Git 完整分发，参见 [仓库范围](https://github.com/LeleCheung/XSAI-KDA/blob/main/docs/repository-layout.md)。
可分发的软件测试和 demo 不依赖这些历史数据。

## 验收记录

- [最终验收 JSON](https://github.com/LeleCheung/XSAI-KDA/blob/main/reports/profiler-alignment/final-acceptance.json)：
  覆盖当前代码/测试身份、release wheel 内容一致性、历史报告/时间线校验、
  非空 RTL 正确性与 perf，以及安装后项目外恢复。
- [78 项软件测试](https://github.com/LeleCheung/XSAI-KDA/blob/main/reports/profiler-alignment/software-tests-final.log)。
- [sdist → wheel → 独立 venv 安装检查](https://github.com/LeleCheung/XSAI-KDA/blob/main/reports/profiler-alignment/install-acceptance-product-final.json)：8 项通过。
- [既有真实报告回归](https://github.com/LeleCheung/XSAI-KDA/blob/main/reports/profiler-alignment/legacy-real-evidence.json)：93 项通过；
  [新界面真实数据验收](https://github.com/LeleCheung/XSAI-KDA/blob/main/reports/profiler-alignment/real-acceptance.json)：10 项通过。
- [三类算子的批量报告](https://github.com/LeleCheung/XSAI-KDA/blob/main/reports/profiler-alignment/real-evidence-final/real-batch/index.html)；
  [同一 FA 两个 shape 的结果矩阵](https://github.com/LeleCheung/XSAI-KDA/blob/main/reports/profiler-alignment/multi-shape-batch/index.html)。
- [FA 时间线示例](https://github.com/LeleCheung/XSAI-KDA/blob/main/reports/profiler-alignment/real-evidence-final/fa-timeline/index.html)：
  1000 条 CPU 指令前缀，保留全 ROI 数量与截断提示，CUTE 单独时钟展示。
- [安装后非空 RTL 采集报告](https://github.com/LeleCheung/XSAI-KDA/blob/main/reports/profiler-alignment/installed-rtl-nonempty-collection/report/index.html)：
  上游 softmax case 1，n256 FP32、scale=1；1 次 perf 和新鲜正确性门通过。
  仅作工具采集链路验收，单次数字不构成重复性能或新加速比结论。
- 本地已生成 wheel，文件与哈希见
  [release receipt](https://github.com/LeleCheung/XSAI-KDA/blob/main/reports/profiler-alignment/release-wheel.json)；
  wheel 放在 dist/，不提交构建二进制。

重放软件检查使用 tests/verify_profiler_install.py；本机历史证据检查使用
tests/verify_profiler_real.py；最终本机 gate 为 tests/verify_profiler_goal.py。
前者不需要历史 RTL 数据，后两者需要保留的原始产物。

## 溯源修正

首次安装后采集通过，但源码快照在本工程新建 Git 仓库后继承了外层项目 revision；
这不是快照自身的 BLAS revision。文件级/整树哈希未变，原记录不改写，说明见
[首次 smoke 限制](https://github.com/LeleCheung/XSAI-KDA/blob/main/reports/profiler-alignment/smoke-01-provenance-limit.md)。
现在只为精确的 Git repo/worktree 根记录 revision，内部快照为 null，另有回归测试。
修正后的第二次记录通过，但复核发现其标签误写 n32，实际为上游 case 0
（n=0），仅作为空输入/API 路径检查保留，见
[第二次 smoke 限制](https://github.com/LeleCheung/XSAI-KDA/blob/main/reports/profiler-alignment/smoke-02-workload-limit.md)。
最终验收使用第三次、明确断言实际 shape 的非空 n256 FP32 采集。

## 能力边界

1. 采集仍需外部 XSAI-BLAS、AM、LLVM、emulator/config；安装包不提供这些依赖。
2. 分区决定需要的原生 perf/HPM/trace 模式，不实现任意 HPM 事件寄存器重编程。
3. 时间线的 CPU 柱是 fetch→commit residence，RVV 轨按指令分类，不是管线
   占用；CUTE 只展示记录的 task interval。两个时钟未经对齐，不推断关键路径。
4. 不提供任意函数独占计时、实测 DRAM 带宽、Roofline、GPU occupancy 或自动
   因果瓶颈结论；缺证据时明确 unavailable/partial/unresolved/unscoped。
5. 批处理为串行版本，无 batch 级自动恢复；失败保留，collect 仍支持显式 resume。
6. 没有新增 GUI 应用；HTML 可离线查看，有缩放、滚动、搜索与 exact-event 表。
   不声称与 NCU/MS 工具的报告格式兼容。

使用方式见 [CLI 文档](profile-cli.md)，实现范围见 [对齐计划](profiler-alignment-roadmap.md)。
