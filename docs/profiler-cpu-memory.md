# CPU/RVV memory observation (xsai-prof 0.6)

The memory-trace collection option now records ordinary scalar/RVV LSU requests
as well as AME requests on the exact reviewed observer build. The same JSON
evidence feeds Memory reports, baseline comparisons and CPU timeline memory tracks.

~~~bash
xsai-prof memory REPORT --output NEW_MEMORY_DIR
xsai-prof memory REPORT --cpu-cycle-range BEGIN END --output NEW_STAGE_DIR
xsai-prof timeline REPORT --output NEW_TIMELINE_DIR
xsai-prof compare BASELINE_REPORT CANDIDATE_REPORT --output NEW_COMPARISON
~~~

The reviewed observer receipt and private emulator are under
experiments/profiler-cpu-memory/rtl-observer-v2/. Collection rejects an
unreviewed or changed receipt/emulator. The hardware model and original RTL
objects are unchanged; a private C++ sampler reads existing Verilator fields.

## What the numbers mean

| Observation | Hardware boundary | Meaning |
| --- | --- | --- |
| Read request enabled bytes | Three ordinary LoadUnit → L1 request handshakes | Popcount of the accepted 16-byte flow mask, including replay and speculative attempts |
| RVV request bytes | Same boundary, vector flag and active flow | Actual lane masks, including tails; no multiplication by vector instruction width |
| L1 statuses | LoadPipe response valid; ready is always true | Hit/miss/replay status, paired by port and two-edge pipeline |
| Local status latency | Request edge → L1 status edge | Two cycles on validated microbenchmarks; excludes refill and architectural completion |
| PMA store enabled bytes | Accepted PMA store event, delayed two edges | Enabled store lanes; special whole-line byte count remains unknown |
| Store-buffer completion bytes | L1 store hit completion, delayed one edge | Merged cacheline mask; separate from PMA stores and never summed with them |

Read payload, architectural load latency, total CPU/RVV coverage, cacheline fill
bytes and DRAM bytes remain **unknown**. Ordinary LoadUnits do not cover atomics,
all vector-segment paths or uncached/MMIO operations. No bandwidth or roofline
claim is derived from these partial observations.

Each request retains raw flags, mask, virtual address, sequence number,
element/offset, response status and boundary state. Missing responses can be
killed requests; they are retained without calling them completed loads. Missing
S1 metadata prevents byte attribution. Replay attempts are not deduplicated away.
Split/misaligned flags are retained; this release does not claim a nonzero split-flow
microbenchmark calibration.

## Scope and source mapping

A call/stage selects events by marker commit timestamp interval, or an explicit
CPU cycle range. Responses to selected requests are followed beyond the end.
Entering/leaving statuses are reported. Timestamp scope can include speculative
work from another call; it does not imply instruction ownership.

Scalar source mapping uses the same database's retirement SN and PC when
available. This model carries unusable small PC fields on RVV flows. A unique,
nonzero dynamic SN present in this database's retirement records can recover the
ELF PC; raw PC and attribution method remain in JSON. Missing/zero SNs stay
unattributed. Filtered lifetime collection can omit vector retirement; use full
capture when source completeness is needed. ELF instructions and source archives
are checked by the established ROI adapter. The RTL instruction field is
preserved as raw metadata and is not treated as instruction encoding.

## Real acceptance evidence

experiments/profiler-cpu-memory/known-acceptance.json validates:

- Scalar 1/2/4/8-byte loads and stores: 15 bytes each.
- RVV tail masks: 16+3 bytes each.
- Alternating mask: four data bytes plus one mask-load byte, four store bytes.
- Exact two-edge L1 status pairing and constant CPU stamp/EPOCH offset.
- Correctness, same-image ELF mapping, and explicit missing coverage.

FA and GEMM use new observation-only replays of frozen, paired image/ELF inputs.
Reports preserve the original independent perf evidence and original emulator
identity. They do not rebind old cycles to this observer or establish a new speedup.

In this diagnostic run, FA (q=5, kv=17, d=19) RVV request bytes decrease
7,099 → 6,484 (8.66%). Some RVV source ownership remains unknown, so this is
whole selected-call traffic, not a complete V-only byte measurement. GEMM
(128³) removes 32,768 observed PMA bytes from memset (32,768 → 0); total
PMA store bytes decrease 197,164 → 164,428, with other execution differences
and timestamp boundaries retained. AME request traffic remains unchanged.

## Reproducibility and cost

Source/RTL anchors, retained fields, observer sources, object hashes, compilation
attempts, signed-DPI mask correction and failed benchmark selection are retained
under experiments/profiler-cpu-memory/. The first observer identified a
signed-short DPI mask ABI mismatch; that capture is a negative calibration
artifact, not accepted store-byte evidence. No dependency or original RTL build
is regenerated. Full CPU event collection increases capture size and host work;
consult the cost receipt.

The reviewed 0.6 observer retains CPU event rows whenever lifetime dumping is
enabled. Lifetime scope filtering currently limits instruction-row insertion,
while CPU memory rows are kept across the run for boundary reconstruction. The
memory-trace option requests/validates this interface view; it does not make
CPU event retention sparse. This capture cost is explicit in the cost receipt.
