# Profiling 接入

人和 agent 的统一离线报告入口现为 `profile report/compare`，详见
[接口说明](profile-cli.md)。下文说明底层采集及上游分析器来源。

用户提供的 `profiling-tool.md` 对应 BLAS `d1f3909`。该提交把 profiling 移出 BLAS，文档指向父级 `xsai-env/scripts/xsai-blas/`。当前可获取的 xsai-env master `2dc0f078` 没有该目录；已检查的 dev-release 和 mem-profiling 也未提供这一入口。因此本工程保留该接口的优先发现能力，并固定 BLAS 前一提交 `d5a2f913` 的 `roi_hotspots.py` 作为可运行 fallback。

## 两种分析器

| 项目 | 文档指定分析器 | 固定 ROI fallback |
| --- | --- | --- |
| 发现路径 | `XSAI_ENV_HOME/scripts/xsai-blas/analyze_perfcct.py` | `vendor/xsai-blas-profiling/roi_hotspots.py` |
| 输入 | DB、同次构建 ELF、可选 run log | DB、同次构建 ELF |
| 输出 | PC JSON、PC Markdown、ROI 页面（依具体上游版本） | 热点 JSON/CSV/TXT、HTML、SVG flamegraph、collapsed stacks |
| 验证状态 | CLI 按说明文档接入，当前缺失真实脚本，尚未实跑 | fixture 检查通过；2026-10-10 真实 XSAI RTL trace + 同次 ELF 分析通过 |
| 额外选项 | 遵循该脚本的版本接口 | `--window`、`--top`、`--objdump`、`--objdump-mattr` 等 |

历史 `profile_perfcct.sh` 仅保留来源，不直接执行：其路径和顶层 `run-emu-debug` 假设不匹配当前环境。适配器负责同样的 build → copy BIN/ELF → collect DB → analyze 流程，并优先发现新分析器。

## 采集与归因

`rtl --mode trace` 在性能循环两侧启用 `0x5A100013` / `0x5A200013` marker，启用调试信息和 `--dump-db --dump-select-db lifetime`。它保存本次 BIN/ELF，并检测 emulator build 目录本次新建或变化的 DB；不是恰好一个时拒绝配对。构建和采集使用文件锁，不会移动已有数据库。其他非 KDA 进程不能同时向该目录采集。

Fallback 按动态 SN 选择 ROI，合并同一指令的微操作，并采样验证 ELF 指令编码。RVC 在 trace 中可能已经解压成 32 位编码，不能直接与 ELF 的 16 位编码比对；AME 需要匹配的反汇编工具。采样一致只是一部分配对证据，保存同次构建 ELF/DB 的来源和哈希仍是必要条件。

`retirement_cycles` 把相邻提交的周期差归到后提交指令，可加总为 ROI 周期，但不代表函数独占运行时间。fetch-to-commit 是重叠的流水线停留时间。调用栈基于动态函数转换重建，受内联、间接调用、递归、tail call 和符号缺失影响。

`rtl --mode hpm` 使用 BLAS 原有 `memstall` 或 `default` 事件集，保留原始 counter 输出。事件编码必须与实际 RTL `printEventCoding` 一致。该入口不重新定义硬件事件，也不把缺失 counter 当作 0。

2026-10-10 的实际展开发现 BLAS 的 backend 76、77 标签与锁定 RTL 不匹配，详见 [RTL 构建记录](https://github.com/LeleCheung/XSAI-KDA/blob/main/docs/rtl-bringup.md)。如果 `--rtl-config` 的 JSON 包含本次展开的 `hpm_event_coding`，适配器在 `hpm_measurements` 保存每个 CSR 的四个事件 ID、实际 RTL 名称、信号和组合运算，并在 `hpm_labels.mismatched_counters` 标出过期单事件标签。组合事件应按四个 selector 与运算解释；没有编码表时 `encoding_resolved` 为 false，原始标签的含义尚未核实。

构建 receipt 可以包含 `emulator.sha256` 和 `runtime_inputs`（外部 DRAM 配置的绝对路径与 SHA-256）。适配器在运行前后核验这些输入，保存外部配置副本，拒绝 emulator 或内存模型参数发生变化后的结果。

性能排名使用 `rtl --mode perf` 的未插桩周期。trace 和 HPM 单独运行，避免把 debug/marker 配置当作正常运行性能。2026-10-10 已在锁定 XSAI 的 DefaultMatrixConfig emulator 上实跑三种入口：RVV softmax case 1（256 个 FP32 元素），并生成 [真实 ROI 报告](https://github.com/LeleCheung/XSAI-KDA/blob/main/runs/20261010T051747Z-rtl-_xgy_979/roi/index.html)。构建、计数器标签与结果见 [RTL 构建记录](https://github.com/LeleCheung/XSAI-KDA/blob/main/docs/rtl-bringup.md)；`runs/profiling-fixture/` 仍仅为合成测试输入，不是 RTL 证据。

首个 [softmax 优化实验](https://github.com/LeleCheung/XSAI-KDA/blob/main/docs/softmax-experiment.md) 已验证两种减少寄存器 spill 的候选：数值检查通过，但未插桩 RTL 周期均退步。ROI 热点与 HPM 用于形成假设；动态指令数或 spill 减少不能替代最终周期判定。

[多 shape 实验](https://github.com/LeleCheung/XSAI-KDA/blob/main/docs/softmax-shapes.md) 使用统一四 case harness 比较 n=32/256/1024/4096，完成三种实现的两轮未插桩 perf，并单独完成 n=32/4096 的基线与 LMUL=4 候选 HPM/ROI。单 case 诊断可能改变随机输入序列和堆布局，因此不与四 case perf 的周期作同次对应；结果只能检验机制趋势。每个 trace 保存同次性能 ELF，核验 `profile.elf` 与 `perf.elf` 哈希一致，并在汇总中检查全部 ROI 原生 32 位 PC 的编码；压缩/更宽编码的跳过数量也会记录。
