# xsai-prof 硬件分析

0.4.0 已补全原默认29个counter谓词审计，并验证特定observer构建的同次CPU/CUTE
锚点映射；见[扩展验收](profiler-night.md)。下文保留0.3.0阶段的案例与边界。

`xsai-prof hardware` 将已有的性能、HPM 和 ChiselDB 证据解释到 RTL 谓词、
时间戳来源和源码，供人和 XSAI-KDA 共用。它是离线分析命令，不启动仿真。
本阶段借鉴 NCU 的指标解释和 msOpProf simulator 的阶段分析，版本为 0.3.0。

```sh
xsai-prof hardware /path/to/profile-report --output /path/to/new-hardware
xsai-prof timeline /path/to/profile-report --output /path/to/new-timeline
```

输出 hardware.json、hardware.md、HTML 和文件校验。导出前复核原报告、manifest、
DB/ELF 配对、动态 ROI 和 HPM 原始日志；不修改历史报告或冻结的诊断反馈。
缺 HPM/trace 时对应能力为 unavailable，仍能解释已有的 perf 结果和缺证据项。

## 本次增加了什么

| 功能 | 行为 |
| --- | --- |
| RTL 构建绑定 | 已审计的 emulator、build log、配置与 core/utility/CUTE/L2 源码身份全部匹配后才应用解释；每个事件还核对 group、ID、名字和实际信号 |
| 事件解释 | 展示打印标签、四路 selector、真实组合表达式、RTL 谓词、单位、信号和带行号的源码摘录 |
| 分母解释 | 只用同次 HPM 运行的 cycles/call 计算近似诊断事件率；不除以 perf/trace 周期，不输出精确 stall 百分比 |
| CUTE 子阶段 | 在原 task scope 内按 SEQID 配对 allocation/issue/read-A/read-B/write-C/finish；保留缺失和 unscoped |
| 时间戳解释 | timeline 增加 clock_contract，解释 CPU/RVV 与 CUTE 的计数器来源及缺少的对齐证据 |
| 源码与证据缺口 | 保留 ROI 热点及关联 PC/归档源码；明确 DRAM 带宽、occupancy、独占函数时间和跨引擎关键路径不可观测 |

当前固定构建的 29 个已采集计数器中，20 个的全部输入事件具有已审计谓词；
其余保留 partial。它不是通用 Scala 解析器，也不会仅凭相同名字接受另一版 RTL。
独立安装包自带审计契约，不要求用户保留 RTL checkout；原始报告的 DB/ELF 等
证据仍然需要保留。更换硬件构建后，应添加经过审计的新契约，不能放宽匹配。

## 三个实际解释问题

本次审计针对已有 FA/GEMM 使用的 DefaultMatrixConfig 单核构建，emulator
SHA256 为 189681b2f3aa6fe9f51891acd9df0bb51b250305ecd970f2d0b26a619541adfd。
构建生成的 event coding 与软件打印标签存在差异：

| 软件标签 / RTL 名字 | RTL 实际定义 | 对分析的影响 |
| --- | --- | --- |
| ISSUE_GE_4_UOPS → IssueQueueAluCsrFenceDivMcfg_full | Scheduler.scala 的 lastCycleIqFullVec 实际为 RegNext(enq.head.ready)，没有取反 | 既不是“每周期至少发射 4 个 uop”，也不是该队列的 full 周期 |
| VF_UOPS_ISSUED → Scheduler_1 的 issueQueue_enq_fire_cnt | FP scheduler 入队 fire 的 PopCount | 不是 RVV 执行/发射量 |
| l1D_write_dcache_miss | s2_fire AND (s2_isStore OR (s2_isAMO AND isWrite(cmd) AND NOT s2_hit)) | !s2_hit 只约束 AMO 分支，普通 store 不受命中条件约束，不能据此算传统 L1 miss rate |

此外，EXEC_STALL_CYCLE 的谓词是发射 uop 数小于 4，包含发射 1～3 个的周期；
MEMSTALL_STORE 可以在其他工作发射时成立；L1/L2/L3 stall 谓词层层包含。
这些计数不能相加成互斥的 stall 饼图，也不能单凭名字证明因果瓶颈。

源文件、完整哈希和带行号摘录保存在
[审计契约](../scripts/kda_hardware_contract.py)。构建来源使用原 producer 的
git diff HEAD -- src build.sc 哈希规则；exact emulator/build-log 哈希绑定实际产物，
不声称实现了独立可重复构建。每个报告都记录本次解释使用的契约哈希。

## 时钟和分母

CPU 的 LifeTimeCommitTrace 使用 PerfCCT.global_tick_acc，由 Rob 中 reset-gated
negedge DPI 回调递增；RVV 指令使用同一 CPU lifetime 计数器，不存在这里单独记录的
RVV 引擎时钟。CUTE 的 STAMP 来自 TaskController 各 Table.log 的 RegInit(0)
本地计数器，由 positive-edge writer 记录。不同计数器和 reset/edge 机制尚无
同次运行的同步锚点，因此不能直接平移叠加两条时间线。

同一 CUTE task 的站点差值可细化观测：load allocation→issue 是控制器等待，
compute issue→read-A/read-B/write-C finish 是三个共享起点的区间；它们重叠。
不能把 515、515、521 cycles 相加，更不能把最后差的 6 cycles 当作纯矩阵计算延迟。
站点缺失记 null；明确记录的零间隔仍保留零。

HPM 与 cycle CSR 的读取/使能边界并不完全相同，事件也有流水寄存器延迟；
日志里的每调用数值还有舍入。因此事件数除同次 HPM 周期仅为 approximate，
可能略大于 1。例如 GEMM counter 16 为 52354.38 / 52354 ≈ 1.000007，
不能截成“100% 利用率”，更不能拿 50344 的候选 perf 周期当分母。

## FA：从周期到指令与源码

固定 q=8、kv=128、d=64，已有独立未插桩 perf 为 77286→56328 cycles/call，
即 1.3721×。以下指令计数来自各自 trace 中覆盖 8 次调用的整个 ROI：

| flash_attention_update_i8 指令 | 原版 | 两行复用版 |
| --- | --- | --- |
| vle8.v | 16384 | 8192 |
| vsext.vf2 | 16384 | 8192 |
| vfwcvt.f.x.v | 16384 | 8192 |
| vfmacc.vf | 16384 | 16384 |

分析顺序是：perf 确认收益 → ROI 热点落在 update → 同次 ELF 确认加载/转换序列
→ 归档源码确认两行 query 共享 V 的数据流 → 比较指令计数验证预期。
update 的 retirement-gap attribution 从 421668 降到 254131 cycles；这是归因，
不是独占执行时间。CUTE load/compute/store 的对应区间中位数保持不变，
与本次改变 RVV update 的机制相符，不据此证明任意硬件瓶颈已消失。

报告：[原版](https://github.com/LeleCheung/XSAI-KDA/blob/main/reports/hardware-analysis/release-evidence/fa-baseline/index.html)、
[两行复用版](https://github.com/LeleCheung/XSAI-KDA/blob/main/reports/hardware-analysis/release-evidence/fa-row-pair/index.html)、
[性能对比](https://github.com/LeleCheung/XSAI-KDA/blob/main/reports/hardware-analysis/release-evidence/fa-comparison/index.html)。

## GEMM：减少清零，保留矩阵计算

固定 M=K=N=128，已有 perf 为 52348→50344 cycles/call，即 1.0398×。
基线 ROI 中 memset 有 58016 条指令、19331 个归因周期；候选 ROI 中不再出现。
源码逻辑是在有效 tile 会被后续 packing 完整覆盖时跳过清零，边缘 padding
仍需清零。这是 CPU packing 阶段的变化，不是去掉 AME 累加器初始化。

HPM 的 stDeqCount 从 8327.88 降到 4216.12 events/call；其定义是 store-address
valid 计数，不能说成精确减少了同样数量的存储事务。compute issue→write-C
finish 中位数均为 521 cycles，store issue→finish 均为 2070 cycles，符合
“此次没有改善 AME 任务本身”的观测；不能把这些阶段相加还原端到端时间。

报告：[原版](https://github.com/LeleCheung/XSAI-KDA/blob/main/reports/hardware-analysis/release-evidence/gemm-baseline/index.html)、
[去冗余清零版](https://github.com/LeleCheung/XSAI-KDA/blob/main/reports/hardware-analysis/release-evidence/gemm-no-clear/index.html)、
[性能对比](https://github.com/LeleCheung/XSAI-KDA/blob/main/reports/hardware-analysis/release-evidence/gemm-comparison/index.html)。

## 负例和验证

softmax 保留 1519→1586 cycles/call 的退步，speedup 为 0.9578×，未选为优胜实现。
其历史 RTL 构建未匹配本契约，硬件解释为 reference_only；原有源码/harness
证据限制仍在。见 [负例报告](https://github.com/LeleCheung/XSAI-KDA/blob/main/reports/hardware-analysis/release-evidence/softmax-lmul/index.html)。

本轮使用已有 DB/ELF/运行记录验证工具，没有运行新的 emulator 或新增算子优化。
软件、隔离安装和真实证据验收见
[验收索引](https://github.com/LeleCheung/XSAI-KDA/blob/main/reports/hardware-analysis/README.md)。上一轮 0.2.0 的验收记录保留为
历史版本记录；本轮当前代码身份以新验收为准。

后续要实现可信的 CPU/AME 合并时间线，需要在同次运行中记录两个计数器都能
观察的同步事件，验证 exact build 的 reset/edge/多核行为和映射残差；当前报告
明确保留这一缺口。
