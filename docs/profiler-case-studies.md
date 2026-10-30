# FA and GEMM: from profiling evidence to a verified change

Both cases use actual RTL evidence, frozen source snapshots and paired ELF/DB.
The large local evidence is not bundled in the wheel. Do not expect the paths
below to exist on another machine. Run your own collection with explicit
source/build identities or import an exported evidence archive.

## FA: reuse V loads for two query rows

Baseline and candidate implement xsai_flash_attention_i8. The RVV online
softmax update uses the same V values for multiple query rows. The candidate
updates two rows together so a V load and INT8-to-FP32 conversion can be reused.

The historical q=8, kv=128, d=64 case reached 1.37x under its recorded hardware
and harness; this is not a general shape guarantee. A separate diagnostic
case q=5, kv=17, d=19 on the reviewed 0.6 observer recorded 7,099 -> 6,484
ordinary RVV request enabled bytes (8.66% reduction). These include request
attempts/replay/speculation and partial source attribution. They are not a
complete measurement of V-only or DRAM bytes.

1. Freeze separate baseline and row-pair BLAS source trees.
2. Use xsai-prof init with the intended kernel/case/backend and explicit paths.
3. Pass doctor and collect each implementation under matching settings. For
   memory diagnostics, provision the reviewed observer and add --memory.
4. Compare reports, then open analyze with --baseline. Follow the hotspot to
   verified source/assembly and inspect the CPU/RVV memory changes.
5. State the predicted mechanism before further edits. Verify numerical
   correctness, independent perf repeats and a one-change ablation.

Local 0.6 evidence: reports/profiler-cpu-memory/fa-baseline and fa-row-pair.
The 0.7 observation replays are under reports/profiler-release: both return
16,384 actual AME interface bytes while retaining the RVV request reduction.
Their diagnostics use a newer observer than the original independent perf;
diagnostics_bound_to_perf remains false. Portable import preserves that
distinction and verifies software identities, identical correctness images
and the exact reviewed observer. It does not treat replay cycles as new perf.

## GEMM: remove redundant packing clears for regular tiles

The xsai_gemm_i8_f32 candidate removes a tile buffer clear only when the packing
loops overwrite every location the AME will read. Padding/edge cases still
require the appropriate initialization. Inspect those source contracts before
changing another shape or packing path.

For M=K=N=128, the historical case reached 1.04x under its recorded setup. The
separate 0.6 diagnostic replay observed 32,768 -> 0 PMA store enabled bytes in
memset. Total selected PMA bytes changed 197,164 -> 164,428, retaining other
execution/boundary differences. AME traffic did not change. This supports the
clear-elimination mechanism; diagnostic cycles do not establish that speedup.

Use the same freeze/doctor/collect/compare/analyze workflow with each GEMM
source tree. Inspect memset source attribution, PMA events, unchanged AME
traffic and uninstrumented perf separately. Preserve any tails or failing
cases. Local evidence is under reports/profiler-cpu-memory/gemm-baseline and
gemm-no-clear.
The 0.7 replays additionally verify 32,768 actual AME read-return bytes in
each implementation, with the same memset event change and unchanged AME
totals. These are interface beats, not measured DRAM or useful-element bytes.

## How to report a result

Report the operator, exact shape, baseline/candidate identity, correctness,
repeat cycles and speedup, then observed event changes and remaining unknowns.
The overview labels new scheduling ideas as untested hypotheses with an
experiment and falsifier. It does not automatically turn a byte reduction or
hotspot into a causal performance diagnosis.
