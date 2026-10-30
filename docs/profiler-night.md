# xsai-prof 夜间扩展

目标是对齐 NCU 与 msOpProf simulator 的算子调优闭环。msprof 的应用/设备全栈范围
更宽，不能把此处的算子功能列等同为完整 msprof/NCU 替代品。
0.4.0 已通过软件、独立安装、真实 RTL、迁移和浏览器验收；
[验收收据与案例](https://github.com/LeleCheung/XSAI-KDA/blob/main/reports/profiler-night/README.md)保留逐项证据与剩余缺口。

## 采集与任务

```bash
xsai-prof collect --config config.json --output bundle
xsai-prof status bundle
xsai-prof collect --config config.json --output bundle --resume
xsai-prof batch --config shapes.json --output matrix --retries 1
xsai-prof batch --config shapes.json --output matrix --resume
```

`stage_timeout` 是可选的单阶段墙钟秒数，覆盖 lock wait、build、correctness 和测量。
超时/中断时清理工具拥有的整个子进程组，保留失败日志与 attempt；不会保留后台运行的
同一个 simulator 后又启动第二次采集。心跳每约5秒记录 PID、经过时间、日志大小。
`status` 是只读的进度快照，完成计数是 job 状态，不能替代原始证据重校验。

Batch 仍然顺序调度。`--retries N` 允许每个失败case额外尝试N次（0..20）。
恢复时核对配置、输入文件身份、已保存报告和其原始artifact，复用成功的side；
失败attempt逐次保存。不同shape不合并成一个加速比，失败与未测不记为0。

## 调用与阶段

在collection配置中加入：

```json
{
  "max_runs": 2,
  "ranges": {
    "invocations": [2, 2],
    "stages": [{
      "name": "rvv-update",
      "file": "kernel/riscv64/rvv/flash_attention_update.c",
      "begin": "  for (int64_t i = 0; i < rows; i++) {",
      "end": "      d += (int64_t)vl;\n    }\n  }"
    }]
  }
}
```

这些字段添加在正常的collection配置中；`ranges`要求trace诊断。
调用号是每个测量loop内从1开始的闭区间，warmup在外。begin/end是各匹配一次的
精确源码边界；工具仅修改私有快照，并保存原始identity、生成header和annotation receipt。
阶段边界需在该函数所有执行路径上正确配对；不能用有early-return的任意文本片段
冒充完整范围。分析时拒绝不闭合或错误嵌套的动态marker。

采用独立调用marker和每阶段ID，保留上游整体ROI marker。perf/HPM不执行这些trace
marker，trace的interval包含插桩和重叠工作，不能当成未插桩耗时或独占函数时间。
当前保留完整原始lifetime trace，选调用/阶段发生在记录后的分析中；尚不能据此减少
模拟器执行时间或原始DB体积。阶段列表为空时仍可只选择调用。

发现的上游兼容问题：这版test.h将PERF_MAX_RUNS写死为8，环境变量只参与object目录名。
新collection会在快照中显式设置并记录宏。历史run的实际调用数必须看raw log，不能
按旧config的请求值回填。`max_runs`是上限；flops目标可能让实际次数更少。

## 自选硬件事件

```json
{
  "hpm_events": [
    {"counter": 11, "events": ["EXEC_STALL_CYCLE"]},
    {"counter": 19, "events": [99, 106, 113, 0],
     "operators": ["add", "add", "add"]},
    {"counter": 27, "events": [14]}
  ]
}
```

要求启用hpm诊断。名称/编号必须从当前RTL receipt的event coding精确解析：
3..10 frontend、11..18 backend、19..26 MemBlock、27..31 L2，各组不能互换。
每counter最多4个event；默认3个or，支持and/xor/add/or，组合树为
`((e0 op0 e1) op2 (e2 op1 e3))`。同一counter不得重复。
使用非连续counter时，读取和打印按counter-3索引，不能按descriptor下标取值。

事件可解析不代表谓词已审计。针对固定RTL的原29个默认计数器，扩展解释契约补全了
源码谓词，尤其IBuffer_full是`numValid.andR`；counter16/17也保留其与上游标签
不符的真实解释。其他RTL或新增事件无审计时保持partial/reference_only。
当前没有自动跨轮事件复用；用户用多个配置采集，不把多轮数据标为同次执行。

## 时间桥与AME活动

observer build只重编logger并relink，复用原Verilator模型和其余对象，未重新生成RTL。
CUTE writer回调记录同一时刻的`global_tick_acc`和原CUTE STAMP，额外保存到
XSAIClockSync。工具以确切emulator/logger/base hashes识别此实现，并限定单核。
只有同次DB的锚点完整覆盖全部CUTE事件、数量和跨度足够、所有offset一致时，才输出
`CPU = CUTE + offset`的validated映射。空表、缺锚点、多核或不一致仍为unproven。

映射适用于该run已观测的span；不由数值相似推定同步，不推断亚周期执行顺序。
AME activity额外报告明确task范围内的计数、区间并集、峰值未完成task区间数、原始
issue字段。它们含控制器等待/传输，不能改称矩阵阵列占用率或实测字节数。

## 迁移与统一分析

```bash
xsai-prof export bundle/report --output evidence.zip
xsai-prof import evidence.zip --output relocated
xsai-prof analyze relocated/report --output analysis
xsai-prof analyze candidate/report --baseline baseline/report --output analysis-pair
```

Export保留原报告、raw manifests、记录的artifact、source receipt/archive的原字节。
Import核验文件清单/hash，拒绝越界路径、symlink、重复项、额外项和不完整依赖；
重新核验raw evidence并生成路径更新后的新报告。原报告不被改写成假的原始身份。
有trace时本机仍需可解码该ISA的objdump/readelf等工具，可用import对应选项指定。
受限于已记录的artifact：历史run本来未归档的文件，export不会假装补齐。

`analyze`生成agent可读analysis.json，以及可直接双击打开的离线index.html。
性能、硬件谓词、命名阶段、时间线、源码和可选baseline比较共享一个入口。
时间线事件可点击跳转到PC/源码，阶段可选取对应范围。最多展示请求的指令前缀，
truncated与完整匹配数量保留；展示lane不是硬件pipeline occupancy。
有命名阶段时，统一分析页的CPU时间线先聚焦已观测阶段的commit跨度；只有调用标记时
聚焦选定调用跨度。多个阶段之间的空隙可能包含其他代码，点击具体阶段可进一步筛选。
CUTE仍使用独立task scope。完整外层ROI可通过单独的`timeline`命令查看。

## 参考吞吐模型

```bash
xsai-prof model target/report --config reference-model.json --output model
```

配置包括`work`（按fp32_lane_flop/int8_mac/int8_to_fp32_element/algorithmic_byte
分单位）、`references`（每单位一个已验证、归档源码、至少两次独立perf的参考report及
声明工作量）、`assumptions`（缓存/工作量/复用假设）。各reference必须同RTL/工具链。
输出实测reference work/cycle和target工作量的等效参考周期；max/sum均不是已经证明的
延迟界。不会将cache-hot微基准冒充硬件峰值或DRAM带宽，也不会给出假的硬件效率。
夜间微基准源码位于experiments/profiler-night/cases_prof_microbench.c。

## 仍保留的能力边界

- 没有真实硅片采集、GPU/NPU硬件专属metric等价性或应用全栈跟踪。
- 没有真实DRAM流量、RVV/AME资源占用、自动因果critical path或可靠Roofline上限。
- 当前range选择不控制trace落盘量；无自动多轮counter replay合并。
- 参考吞吐只能校准可观察工作，不能用来证明某算子已接近硬件性能上限。
- 完整GUI平台、远程服务和任意第三方程序注入不在当前实现中。

事件发现示例：

```bash
xsai-prof query events --rtl-config /path/rtl-config.json --format json
```

返回该receipt内的group/id/name/signal与解释状态，不会把查询本身标成已执行采集。


## 本轮真实验收

- 101项软件回归、12项独立安装、23项真实RTL/历史证据复核、7项浏览器检查通过。
- FA q5/kv17/d19：实际2次测量，仅标记第2次调用；rvv-update动态区间为2431诊断周期，
  对应1054条内部指令。区间归因守恒；它不能代替未插桩cycles/call或独占阶段耗时。
- 同次48个CPU/CUTE锚点全部覆盖且一致：CPU=CUTE+1，残差0；此前actual8 run为144锚点。
- 自选counter11/19/27均有同构建源码谓词；L2 noEvent也以实际IO wrapper编码审计。
- FMA参考微基准7970/7970 cycles，转换参考15425/15425 cycles；trace工作量符合声明。
- 安装版从工程外恢复已完成采集，成功attempt与manifest/report身份保持；原采集目录
  暂时不可访问时仍可导入、分析并生成参考模型，最后恢复原路径。
- 本轮没有新增算子加速比；历史FA1.3721×、GEMM1.0398×和softmax负例仅用于工具案例复核。
