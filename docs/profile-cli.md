# XSAI profiling：人和 agent 共用的接口

`xsai-prof` 将已有的 perf、HPM 和 ChiselDB 分析组织成统一报告。
借鉴 Nsight Compute 的分区报告、源码/汇编关联和 baseline 对比方式；指标仍来自
XSAI，使用 XSAI 的含义。实现只依赖 Python 标准库，反汇编和符号定位调用 ELF 工具。

2026-10-26 增加独立安装、指标/分区查询、CPU/CUTE 独立时钟时间线与多 shape
批处理，见 [NCU / MindStudio 对齐范围](profiler-alignment-roadmap.md)。时间线是
已有事件的表达，不代表任意函数独占计时。后续扩展支持在同次同步锚点验证通过后
关联 CPU/CUTE 时钟，见[范围采集、事件选择、迁移与统一分析](profiler-night.md)。

使用时不需要启动 skill、agent 或模型。现在可安装 Python 包并直接运行 xsai-prof，
无需保留原工程目录；离线分析资源和固定版本 ROI analyzer 随包分发。采集仍需外部
BLAS、AM、LLVM 和匹配的 RTL emulator/config，不随包安装。源码入口为
bin/xsai-prof → scripts/cli.py，旧 python3 scripts/xsai_kda.py profile ... 兼容。
采集、报告/对比、诊断继续复用相同的适配器与证据校验。

## 安装与快速体验

在项目根目录执行：

```sh
python3 -m venv /path/to/profiler-venv
/path/to/profiler-venv/bin/python -m pip install .
# 激活 venv 后，从任意目录执行：
xsai-prof --version
xsai-prof doctor
xsai-prof query metrics
xsai-prof demo --output /path/to/new-demo
xsai-prof batch --config /path/to/new-demo/batch-config.json --output /path/to/new-matrix
```

安装依赖 setuptools/wheel，运行时分析只用 Python 标准库。Python 需 >=3.10，
当前支持 Linux；安装不等于 native 编译。`demo` 在本地生成明确标为 synthetic
的 perf/HPM 测试数据，不执行模拟器；没有 trace 时明确 unavailable。真实 ELF
符号/反汇编还需要支持目标 ISA 的 readelf/objdump/addr2line。

`xsai-prof doctor --config COLLECTION.json` 额外校验 RTL、runtime、编译器和
配置身份；缺失时返回非零退出码。默认 doctor 只检查离线运行资源，RTL 为
not_checked，不会暗示仿真依赖已齐全。`XSAI_KDA_ROOT` 可指定外部工作区
默认路径，资源本身仍取安装包中的固定 analyzer。

## 指标、分区与采集集合

```sh
xsai-prof query metrics --format json
xsai-prof query sections
xsai-prof query sets
xsai-prof query metrics --report /path/to/verified-report --format json
```

指标目录注明来源、单位、scope、所需采集模式和解释限制。无 report 时显示
requires_evidence；带 report 时验证原始输入，加入这次 RTL 的实际 HPM selector、
事件名和解析状态。未记录的 elements/cycle 或无源码行号不能记成可用，更不能
当零；未解析 HPM 不提供伪硬件事件值。

集合 `basic` 只采 perf；`counters` 采 perf+HPM；`detailed` 采 perf+HPM+trace。
也可在 collect 中指定 `--sections performance rvv ame source`。分区选择决定
所需原生模式；RVV、hotspots、source、AME 复用同一次 trace，不分别追加仿真。
这是按模式选择；具体事件由额外的 `hpm_events` 配置选择，须遵守该 RTL 的
counter 分组与组合规则，见[自选事件](profiler-night.md#自选硬件事件)。不能与 `--diagnostics` 混用，
`--set` 与 `--sections` 也互斥。配置文件内对应字段为 `set` / `sections`。

新 report 自动增加 `metrics.json` 和 `sections.json`，原 JSON/MD/HTML、
源码搜索、原始证据验证与 compare 保留。缺少的分区明确说明原因。

## RTL 硬件解释

```sh
xsai-prof hardware /path/to/verified-report --output /path/to/new-hardware
```

0.3.0 新增硬件解释报告，输出 JSON/MD/HTML/checksums，复核原始证据后展示
HPM selector 的实际组合、RTL 谓词和信号、打印标签差异、近似事件率的同次 HPM
分母、CUTE task 子阶段、ROI 热点/源码和不可观测项。构建身份及 event coding
匹配已审计契约才应用谓词解释；其他构建保留 reference_only/partial。
缺证据不记零，不自动推断 cache miss rate、occupancy 或跨引擎关键路径。
具体事件问题、时钟定义和 FA/GEMM 案例见 [硬件分析说明](hardware-analysis.md)。

## 时间线：CPU 指令与 CUTE 阶段

```sh
xsai-prof timeline /path/to/verified-report --output /path/to/new-timeline \
  --function flash_attention_update_i8 --max-instructions 10000
xsai-prof timeline /path/to/verified-report --output /path/to/new-stage \
  --cute-stage compute --cute-task-range 1 8
```

输入为带 trace 的 profile report；导出前重新核对原 DB、ELF、ROI 和 PC。
输出 `timeline.json`、`events.csv`、可缩放/滚动/搜索 HTML 和 checksums。
CPU 事件包含 SN、PC、函数、源码行、汇编上下文及归档源码（有时），支持
函数子串、`--cpu-cycle-range BEGIN END`（按 commit timestamp）筛选。CPU ROI
来自输入报告；要选择另一动态 marker 窗口，先用 report 的 `--window N`
和 `--recompute-roi` 生成对应报告。窗口并不保证一一对应单次算子调用。

CPU 柱表示合并 uops 后的 earliest fetch 到 latest commit 的 residence，
没有 fetch 时仅绘制 commit 点；issue/FU 无效值标缺失。它不是指令执行独占
周期，也不是计算单元利用率。RVV/Scalar 轨是按指令名分类，不是硬件管线。
最多展示 `--max-instructions` 条（上限 100000），按动态 SN 取前缀并显式报告
完整匹配数量和截断，不能当作热点采样或完整流水覆盖。

CUTE 仅用原始 Issue/Finish timestamp 和报告中明确的 task scope，支持
load/compute/store 与 SEQID 范围选择。其 task scope 和 CPU ROI 独立；CPU
函数/周期过滤不改变 CUTE scope。无 scope 时保留 unscoped 标记，不能据此
做测量调用的阶段结论。CPU/CUTE 分别用自身 timestamp cycles 绘图，不换算
为秒。默认保留各自坐标；仅同次 observer 锚点完整且 offset 校验通过时增加
CPU 对齐坐标。不推断跨引擎关键路径，也不把重叠区间相加。
0.3.0 的 timeline.json 增加 clock_contract，记录计数器来源、构建适用性及
缺少的同步锚点；RVV 指令使用 CPU lifetime 计数器。

## 多 shape / 多实现批处理

```json
{
  "cases": [
    {
      "id": "fa-q8",
      "baseline": {"report": "fa-baseline"},
      "candidate": {"report": "fa-candidate"}
    },
    {
      "id": "gemm-128",
      "baseline": {"collect": "gemm-baseline-collection.json"},
      "candidate": {"collect": "gemm-candidate-collection.json"}
    }
  ]
}
```

```sh
xsai-prof batch --config /path/to/batch.json --output /path/to/new-batch
```

每侧任选一个 `report`（已有报告）、`spec`（已有证据 spec）或 `collect`
（采集配置）；路径相对 batch 配置。ID 唯一且只含字母数字、下划线和连字符，
首字符为字母数字，最长 80 个字符。先校验配置，再串行处理各 case，采集保留
已有源码、runtime 构建和 emulator 锁，避免共享产物冲突。新旧源码入口与
安装入口共享 runtime 构建锁，默认在 `~/.cache/xsai-prof/locks`；如设置
`XSAI_PROF_STATE_HOME`，并发调用必须使用相同目录。源码入口同时保留历史锁。

输出 `batch.json`、`batch.csv`、HTML、逐 case 比较或 failure 记录。输入配置/
harness/shape 不可比、采集失败或校验失败时，该 case 为 failed、speedup=null，
继续处理后续 case，命令最终返回非零。缺少一侧为 unmeasured，不虚构性能。
有两侧独立重复且记录区间不重叠时标 improved/regressed；重叠或缺少重复为
inconclusive，周期相同为 unchanged。这些标签不是统计显著性检验。
多 shape 各自保留基线，不自动合成一个总体加速比。

批处理输出逐 case 持久化，中断保留当前状态与原始尝试。`--resume` 核验配置、
输入身份和原始证据后复用成功 side；`--retries N` 允许每个失败 case 额外
尝试 N 次（0..20）。改变输入需使用新输出目录，不能通过恢复覆盖历史结果。

## 采集 → 报告 → 对比 → 优化

1. 固定算子、shape、harness、工具链和 RTL 配置，保留候选源码快照。
2. `rtl --mode perf`：先过正确性门，再采集未插桩 cycles/call；独立重复。
3. `rtl --mode hpm` / `rtl --mode trace`：同一实现分别采集诊断数据。
4. `profile report`：绑定各次运行，校验原始证据，生成分区报告。
5. `profile compare`：比较 baseline/candidate；先看周期变化，再看热点和指令变化。
6. 人或 agent 提出候选，继续正确性、复测、消融、选择；有依据的结论写回 wiki。

`xsai-prof collect` 接入原有 RTL 采集；`report/compare` 可完全离线读取
已有 `runs/`。原有 `analyze`、单 run `compare` 均继续可用。

## collect：冻结源码并自动完成采集和报告

```sh
source env.sh
ulimit -s 65536
xsai-prof collect --blas /path/to/candidate \
  --noop-home /path/to/validated-rtl --rtl-config /path/to/rtl-config.json \
  --backend ame --rvv-enable yes --kernel flash_attention --case 4 \
  --perf-repeats 2 --max-runs 8 --diagnostics hpm trace \
  --cute-warmup-tasks 1 --cute-measured-tasks 8 \
  --output experiments/my-candidate
```

`AM_HOME`、`LLVM_HOME` 等环境变量与原 RTL 入口一致；AME 要选择匹配编译器和正确的
store-fixed RTL。子命令的 `--blas` 等路径放在 `collect` 后。命令先检验依赖，再将源码复制到
bundle 的私有 `source/`，保留执行权限并排除 Git 元数据与构建产物，从该快照构建和采集。
原 checkout 的后续变化不会进入这一份采集。`source.json` 保留原 revision 与整个源码的哈希；
快照 manifest 的 revision 可能为 null，不会把快照冒充原 Git checkout。

每次独立采集仍先构建 test 镜像并通过 RTL 正确性门，然后才测量。默认两次 perf、一次 HPM、
一次 trace；`--diagnostics` 后不接值可只采 perf。`--perf-repeats` 是独立仿真次数，
`--max-runs` 是每次镜像内最多调用次数，两者不同。保留原 harness 的 warmup 规则，工具不重写算子输入。
AME trace 同时采 CPU lifetime 和 CUTE；CUTE task scope 需由实际 tile 数与调用规则给定。
所有模式使用已有 BLAS、AM 构建锁和 emulator 锁，trace 不绕过串行采集。
若已有经过验证的相同 emulator 副本，可设置 `--non-trace-home`（JSON 为 `non_trace_home`），
仅 perf/HPM 路由到该副本并启用每阶段 DRAMsim3 输出隔离；trace 保持使用 `noop_home`。
工具要求副本与原 emulator 的字节哈希、记录的 RTL revision 和配置相同，不自动创建或替换副本。
显式恢复时允许只变更这一采集路由，并记录 `routing_history`，同时复核工作量和构建身份；
运行中的任务先正常结束，再恢复，锁会拒绝两个 owner。不同路径本身不计为性能优化。

成功后自动生成 `spec.json` 与 `report/`，可直接对比：

```sh
xsai-prof compare experiments/my-baseline/report experiments/my-candidate/report \
  --output reports/my-comparison
```

可以用配置文件完整保存路径、环境和 scope：

```sh
xsai-prof collect --config experiments/fa-collect-loop/baseline-config.json \
  --output experiments/my-baseline
```

JSON 配置字段对应命令行参数，将连字符改为下划线；额外支持 `environment` 和 `cute`。
路径相对于配置文件，`environment` 中的路径也一样。环境值为字符串或 null，null 表示清除该变量；
未指定的受支持变量从当前环境捕获进 collection 记录。配置示例显式固定所有相关值，便于换会话后恢复。
`--config` 不与单独采集参数混用。采集配置与离线 report spec 是两种文件：前者描述如何运行，后者描述已有证据位置。

bundle 目录结构：

```text
collection.json          # 状态、配置、前提身份、每阶段与各次尝试
source/                  # 构建用私有源码；build 子目录可由构建生成
source.json / source.zip # 原始来源、逐文件哈希和快照档案
runs/perf-1/attempt-1/…   # 完整原生 run manifest / ELF / 日志
runs/perf-2/attempt-1/…
runs/hpm/attempt-1/…
runs/trace/attempt-1/…
logs/                    # 每次 adapter 调用日志
spec.json                # 自动生成、相对 bundle 的证据路径
report/                  # 与离线 report 相同的输出
```

`collection.json` schema 为 `xsai-kda.collection/v1`，status 为 preparing/running/passed/failed；
`active_stage` 指示当前阶段，执行日志路径保存在相应 attempt。各阶段逐次写入 manifest/日志哈希。
采集状态更新使用原子替换；原始 run 和失败尝试保留。stdout 成功输出 JSON，进度写 stderr，详细日志写文件。

中断或失败后，使用完全相同的配置显式恢复：

```sh
xsai-prof collect --config experiments/fa-collect-loop/baseline-config.json \
  --output experiments/my-baseline --resume
```

恢复会核对快照、RTL/config、runtime、编译器、已完成 run 和命令日志，复用已通过阶段；
失败阶段创建新的 attempt，不覆盖旧尝试。已完成 bundle 可再次恢复，核验后不重复仿真。
同一 bundle 的锁由 collector 和 adapter 子进程持有，仍有任务运行时拒绝重复启动。
准备阶段未完成快照时应保留原尝试并使用新目录；工作量、环境或实现变化时也使用新 bundle。

## diagnose：事实、假设与验证实验

```sh
xsai-prof diagnose experiments/my-baseline/report --level trace \
  --output reports/my-diagnosis
```

`--level cycles|hpm|trace` 控制诊断可见的证据，默认 `trace`。
cycles 仅包含算子、shape、计算单元标签和未插桩周期；不包含 instret、
HPM、trace、历史实验路径或从这些数据推导的假设。hpm 增加计数器与解析状态；
只解释已解析的 RTL 事件。trace 再增加函数/指令/CUTE 数据。
输入必须是已通过原始证据校验的 profile report，comparison 不作为输入。

输出为 `diagnosis.json`（schema `xsai-kda.diagnosis/v1`）、`diagnosis.md`、
`index.html` 和 `checksums.json`。三种视图来自同一数据模型：

- `observations`：已观测事实、JSON 证据位置、具体值和适用范围。
- `hypotheses`：待检验解释，统一标记 untested/hypothesis_only；包含
  validation_experiment、predicted_observations、falsifying_observation、
  missing_evidence。
- `missing_evidence` / `limitations`：缺失数据和不可支持的结论。

诊断的启发式规则只提示下一项实验，不宣称已建立瓶颈因果。
例如 memset 热点需要检查读写覆盖与 padding，再做毒化 workspace/tail 验证；
多行 update 的转换复用需要源码证明输入相同，trace 没有提供地址相等证明；
whole-register 指令需要确认栈操作数，不能直接认定 spill。
减少指令、spill 或某个 stall counter 都不保证周期改善。

反馈实验使用 allowlist 构造可见视图，限制函数数与每函数 PC 数并显式报告截断；
它不直接把包含完整诊断的报告删减后当作独立实验输入。这里的视图是实验条件，
并非隔离恶意输入的安全边界。参见 [诊断研究 goal](https://github.com/LeleCheung/XSAI-KDA/blob/main/docs/diagnosis-goal.md)。

## report / compare 命令

执行 `source env.sh` 后可直接使用 `xsai-prof`；也可在项目根目录运行
`./bin/xsai-prof`。这是 Python profiling 接口的可执行入口，参数、输出和退出码相同，
原有 `python3 scripts/xsai_kda.py profile ...` 调用继续可用。

```sh
source env.sh
xsai-prof report \
  --perf runs/PERF_1 --perf runs/PERF_2 \
  --hpm runs/HPM --trace runs/TRACE \
  --label 'FA baseline' --output reports/fa-baseline

xsai-prof compare \
  reports/fa-baseline reports/fa-candidate --output reports/fa-comparison
```

只传 `--perf` 也可生成报告，缺少的诊断部分明确显示 unavailable。
成功时 stdout 是结果路径与 warnings 的 JSON，失败时非零退出并在 stderr 写原因。
`--output` 必须不存在；失败不留下半份报告，已有运行目录和 dependencies 不允许作为输出位置。

需要源码片段或复用长路径时，用 JSON spec：

```json
{
  "label": "FA baseline",
  "perf": [
    {"run": "../../runs/PERF_1", "source_receipt": "../../experiments/fa/perf1-source.json"},
    {"run": "../../runs/PERF_2", "source_receipt": "../../experiments/fa/perf2-source.json"}
  ],
  "hpm": {"run": "../../runs/HPM", "source_receipt": "../../experiments/fa/hpm-source.json"},
  "trace": {"run": "../../runs/TRACE", "source_receipt": "../../experiments/fa/trace-source.json"},
  "cute": {"warmup_tasks": 1, "measured_tasks": 8}
}
```

```sh
python3 scripts/xsai_kda.py profile report \
  --spec examples/profiling/fa-baseline.json --output reports/my-fa-baseline
```

spec 内路径相对于 spec 所在目录。run 可用字符串或对象；`source_archive` 可指定 zip，
默认与 receipt 同名 `.zip`。receipt 使用现有实验格式：`identity` 加 `files`（相对文件名→SHA-256）。
工具重算 whole-tree identity，逐文件验证 zip，不会读取当前可变 checkout 来充当历史源码。
源码档案可选；缺失时显示来源限制，源码/反汇编定位仍可使用保存的 ELF。

`cute` 是**每个 load role、compute、store 的任务数量**，不是 CPU 调用数。
FA 归档为 1 次 warmup + 8 次任务；GEMM 每次调用有两个 tile，所以是 2 + 16。
这是这两组实验的显式配置，工具没有八次调用等固定假设。
直接命令可用 `--cute-warmup-tasks 1 --cute-measured-tasks 8`。
无 scope 时只展示全部任务的 unscoped 统计，并禁止用于 CUTE 阶段对比。

默认复用 manifest 中已哈希的 `roi/hotspots.json`，同时从原始 DB 重算每个 PC 的指令数、
微操作数和 retirement gap，从配对 ELF 重读函数符号、汇编和行号，核对热点报告。
没有旧报告或指定 `--recompute-roi` 时，调用固定的 ROI analyzer，在新输出目录生成完整 ROI 页面。
这条统一接口固定使用 `vendor/xsai-blas-profiling/roi_hotspots.py` 的已知 schema；原有
`analyze` 仍保留优先发现 xsai-env 新分析器的行为。

`--window N` 选择第 N 对动态 BEGIN/END marker，旧报告窗口不同需加 `--recompute-roi`。
可指定 `--objdump`、`--addr2line`、`--readelf`；默认从运行记录的 LLVM_HOME 和系统工具发现。
AME 解码支持的工具可加 `--objdump-mattr +matrix-xuantie-0.6`。无 addr2line 时行号不可用。

## 输出与指标

| 文件 | 用途 |
| --- | --- |
| `report.json` | agent 消费的唯一数据模型；schema `xsai-kda.profile/v1` |
| `report.md` | 同一模型生成的可归档文字报告 |
| `index.html` | 同一模型生成的分区报告和导航，可直接浏览 |
| `source-assembly.html` | trace 可用时生成；搜索全部 PC、函数、指令和源码，展开汇编上下文和已验证源码片段 |
| `checksums.json` | 输出文件 SHA-256；compare 会复核报告及原始运行 |
| `roi/`、`roi-analysis.log` | 重新分析模式的底层 ROI 输出 |

JSON 的 `kind` 为 `profile` 或 `comparison`。共同字段为 `schema`、`label`、`sections`、
`warnings`、`metric_semantics`、`validation` 和 `producer`（分析脚本哈希）。
profile 额外保存 `spec`、`options`、构建 `identity`、原始 `inputs` 路径和 manifest/源码档案哈希。
comparison 保存两份报告位置与哈希。文件校验用于发现归档变化，不是数字签名。

`sections.performance` 保存每个 op/unit 的各次 cycles/call、median、min/max 和 instret；
comparison 为 baseline/candidate cycles、speedup、cycle reduction，以及已保存重复中的稳定性。
**speedup = baseline median / candidate median**，仅接受未插桩 RTL 数据。
重复稳定只描述这些样本，不代替跨 shape 验证或统计置信区间。

`sections.hpm` 按 frontend/backend/memblock/L2 分组，保存原始 selector、RTL 事件名、
组合运算和计数。事件含义按这次 RTL 的 event coding 解析，旧上游标签也保留供核对；
未解析时不凭标签推断含义，对比 delta 为 null。缺计数不是零。

`sections.trace` 保存 window、函数、全部 PC、按函数的 `instruction_mix` 和精确 `mnemonics`、
ELF 校验范围、反汇编工具身份与 CUTE。动态指令计数能验证发出的 load、扩展、转换等是否减少；
它不是实测 DRAM 字节。retirement gap 将周期归到下一条提交指令，不能称为函数独占耗时；
fetch→commit 流水线停留可重叠。比较的是同选定窗口的原始计数，不默认换算成单次调用。

CUTE 按表和 load role 分别给 issue→finish 的各任务持续周期与 median/min/max。
阶段之间可能重叠，工具不相加；CPU/CUTE 时钟偏移未经证明，不自动按 CPU ROI 时间戳裁剪。
任务数量不符合显式 scope、事件不完整或重复时拒绝统计；未提供 CUTE 表时显示 unavailable。

## 证据绑定

所有输入都检查通过状态、正确性门和 manifest 中的文件哈希。perf repeats、HPM、trace 必须有相同
source identity、selection、op/unit、backend、RTL、编译器、runtime、构建参数、RVV 设置和 harness。
baseline/candidate 允许修改源码，要求测试工作量与配置一致。仪器化周期不参与性能排名。

trace 要求保存的 `profile.elf` 与同次 `perf.elf` 完全相同，所有 ROI 中出现的 PC 在 ELF 中存在。
逐个 PC 核对 native 32-bit 编码，验证统计守恒和函数映射；RVC 在 trace 可能已解压，
16 位和宽指令不直接核对编码，报告给出跳过数量。这不能替代同次采集的来源证据。

历史 softmax 缺少 harness 独立哈希和源码 zip，工具保留并展示限制；不能把可显示的历史比较
当成新候选已完整验收。缺少这些证据时应补采集后再做正式选择。

## 已验证实例

[真实报告与验收结果](https://github.com/LeleCheung/XSAI-KDA/blob/main/docs/profiling-goal.md) 覆盖 FA、GEMM、softmax。可重放的六份 spec
位于 `examples/profiling/`；可复核报告：

```sh
python3 scripts/verify_profile_examples.py reports/profiling-20261022
make test-adapter
```

下一步优化时，先读取 JSON 的 warnings/validation，再从 performance → trace 热点 →
源码/汇编 → HPM/CUTE 解释变化。工具提供证据，人或 agent 负责假设与消融，报告本身不自动证明因果。
# Capture-side scope and actual interface traffic (0.5)

See [scope/memory definitions](profiler-memory.md) for reviewed observer
requirements, capture_scope and memory_trace config, and xsai-prof memory.
The memory section is opt-in and requires a reviewed actual-interface observer.
Only selected CPU lifetime DB insertion is filtered; markers/CUTE/interface
events remain available to validate in-flight boundaries. Missing read return,
CPU/RVV traffic and DRAM bytes are unknown, never zero.
# 0.8 workflow additions

Use `xsai-prof collect --config CONFIG --metrics cycles_per_call --dry-run -o NEW_RUN`
to preview actual acquisition stages before launching RTL. NCU-style discovery
aliases, metric/section overrides, filtered read-only report pages, CSV/JSON/text
exports and verified browser opening are documented in
[the CLI workflow](profiler-cli-workflow.md). Existing commands below remain valid.

