# Capture-side scopes and actual AME interface observations

This stage extends the independent xsai-prof command used by humans and XSAI-KDA.
Acceptance is tracked in experiments/profiler-memory; unfinished RTL runs are
not evidence of a completed feature validation or a new kernel speedup.
The [acceptance report](https://github.com/LeleCheung/XSAI-KDA/blob/main/reports/profiler-memory/README.md) links the real
microbenchmark, operator cases, retained failures, scope equivalence and costs.

## Collection

Use an exact reviewed observer receipt/emulator. The isolated observer only
relinks logger and lifetime C++ objects against unchanged RTL model archives.
The original emulator and objects are hashed before and after relinking.
No hardware RTL is regenerated; this is an observation change.

Add to an ordinary collection config:

```json
{
  "diagnostics": ["trace"],
  "ranges": {"invocations": [2, 2], "stages": []},
  "capture_scope": "invocation",
  "memory_trace": true
}
```

capture_scope accepts full (the default), invocation, or stage:NAME for one
stage declared in ranges. Full retains the original outer ROI interpretation;
filtered modes report only a selected captured call/stage, never fabricate the
missing instructions from its enclosing call or outer ROI.

All pipeline metadata stays active, including instructions fetched before a
begin marker retires. Lifetime SQLite insertion is filtered in retirement SN
order. All range markers remain, and retained loads keep their lifetime IDs.
The collector records seen/kept metadata rows, complete opens/closes, final
state and mode in the DB. An absent end marker or an empty selected capture
fails analysis. CUTE tasks and compact memory handshakes remain full capture
so asynchronous work crossing a scope boundary can be reconstructed.

Perf and HPM builds do not enable these markers. Only uninstrumented perf
cycles/call can rank an optimization. Trace marker cycles include overhead.

## Interface and byte definitions

The reviewed near_cute monitor observes actual A/D fire handshakes on a
64-byte-wide interface between Cute2TL and the width adapter toward L2.
Generated RTL confirms 64 byte-mask bits, 512 payload bits, six source-ID bits,
and A/D callbacks with the local hardware timestamp. Each callback also records
the current PerfCCT CPU timestamp; reports check the same-run offset histogram.

- Get: requested bytes = 2^size per accepted A request. This is not returned
  payload bytes, cache misses, DRAM traffic, or a bandwidth measurement.
- PutFull/PutPartial: actual outgoing payload byte enables = popcount(mask).
  Repeated addresses count again because this measures interface traffic.
- AccessAck: pairs to a pending write source ID. Source reuse is allowed after
  completion, including the same observed cycle. Denied/corrupt are retained.
- Full 64-bit masks use SQLite hex integer literals; a floating mask is rejected
  because decimal values above signed INT64 may otherwise lose precision.
- This reviewed interface uses at most one 64-byte data beat per transfer.
  Unsupported opcodes, oversized/multibeat cases and incompatible sites fail
  validation rather than guessing their bytes.

Important hardware boundary: matrix_data_in can deliver read data directly to
Cute2TL outside the monitored D channel. Thus full read payload, read completion
latency and outstanding-read counts are unknown. CPU/RVV traffic is also
unobserved at this AME-only point. These fields stay null, including for a
softmax run with zero AME handshakes. This observer cannot by itself measure
the RVV V reuse that explains the historical FA improvement.

Scope accounting selects requests initiated at CPU stamps in [begin,end).
It follows observed write completions outside the interval and separately
reports entering/leaving writes. Timestamp overlap does not establish which
instruction owns an asynchronous request or which operation is on a critical
path. Existing CUTE task intervals retain their independent explicit task scope.
When same-run clock anchors validate the CPU/CUTE mapping, memory reports also
list recorded tasks intersecting the selected interval and mark tasks entering
or leaving the interval. This preserves asynchronous boundary context without
assigning individual requests to instructions or tasks.

## Commands and reports

After collect, use xsai-prof memory REPORT --output NEW_DIR to obtain
memory.json, Markdown, and an offline HTML view. An optional
--cpu-cycle-range BEGIN END changes the diagnostic timestamp interval. The
command revalidates raw artifacts, same-build ELF and observer receipt.
Without selected interface tables it reports unavailable, never measured zero.
xsai-prof analyze also exposes a Memory tab and the lifetime collector scope.
Baseline comparison reports include interface request/byte deltas only when
both reviewed observations select the same invocation/stage scope. Unknown
CPU/RVV, read-return and DRAM metrics keep null deltas. A byte delta is not
a measured bandwidth or a performance attribution.

The acceptance suite compares the same image/ELF on the same emulator in full,
invocation and stage modes, checking every retained pipeline timestamp and all
interface events. It also records database size, analysis cost and simulator
wall time. Smaller databases need not produce faster RTL simulation.
Same-cycle callbacks can have different SQLite insertion IDs across runs;
equivalence compares channel/site, both timestamps, opcode, source, address,
size, mask and error flags with exact multiplicity. No subcycle ordering is
inferred from the observer insertion ID.

## Validation and unsupported cases

The known fullmask microbenchmark passes RTL correctness and emits four
64-byte writes, 256 enabled bytes and four AccessAck responses in one selected
call. The boundary interval preserves a write initiated before its beginning
and completions after its end. The softmax negative case records no AME
requests while keeping CPU/RVV and DRAM bytes unknown.

A partial-column store attempt did not complete correctness and was stopped.
Source review shows the current CMemoryLoader emits an all-ones RequestMask;
that attempt cannot establish a 60-byte masked transfer. Its failed collection,
command, source hash and unsupported-case explanation are retained. Decoder
unit tests cover partial masks, but those are not a real partialmask hardware
validation. See experiments/profiler-memory/partialmask-negative.json.

## Completed acceptance, 2026-10-27

All six required real collection bundles and the final acceptance gates passed.
The same-image full/invocation/stage suite passed 25 checks: DB sizes were
93,351,936 / 6,164,480 / 790,528 bytes, retaining the selected instruction
timestamps and every compact interface event. This is a diagnostic storage
improvement; it does not establish a stable simulator speedup.

The real operator suite passed 13 checks. For GEMM 128x128x128, the packing
candidate reduced ROI memset instructions from 7,252 to zero, with both versions
recording 32,768 read-request bytes and 131,072 write-enable bytes at near_cute.
For FA q5/kv17/d19, each of vle8.v, vsext.vf2 and vfwcvt.f.x.v fell from 85 to
51 dynamic instructions. Both FA versions retained 16,384 read-request bytes
and 65,536 write-enable bytes. The AME monitor does not measure the eliminated
CPU stores or RVV V traffic. These cases each have one independent perf sample
per implementation and do not establish a new stable kernel speedup.

Validation also passed 119 software tests, 12 packaging/install checks and the
installed real-evidence offline UI/portability checks. Final byte verification
matched all 25 recorded Python files across source, wheel and installation;
all 53 original RTL objects/archives and the original emulator stayed unchanged.
The retained failure attempts and all 16 collection attempts are included in
acquisition-costs.json. Attempt wall time includes lock waits, builds and fresh
correctness; only the same-image scope suite separately measures simulator wall
time. Exact evidence and report links are in the acceptance report above.


## CPU/RVV extension

Version 0.6 adds separately observed ordinary LSU requests, lane masks, L1 status
responses and PMA stores. See [CPU/RVV definitions and validation](profiler-cpu-memory.md).
The 0.5 AME-only evidence and its unknown CPU metrics retain their original meaning.
