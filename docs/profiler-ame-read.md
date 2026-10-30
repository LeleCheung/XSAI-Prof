# AME read-return observation

The 0.7 beta observer samples the actual accepted 512-bit matrix_data_in path
from the L2-bank arbiter to Cute2TL. It retains source ID and full payload on
every valid cycle, including backpressure. The source/RTL/header anchors and
original object hashes are recorded under experiments/profiler-release.

The reviewed model sends fixed 64-byte Get requests. A source ID stays busy
until a read return or write acknowledgment; the decoder tracks both kinds
together and rejects premature reuse, wrong-kind or unmatched completions.
Read completion is the valid/ready handshake on matrix_data_in. Raw source-ID
width differences are retained and out-of-contract values are rejected.

| Metric | Meaning |
| --- | --- |
| read_payload_bytes | 64 observed bus payload bytes per matched accepted return for requests initiated in scope |
| read_completion_latency | Mean Get-to-CUTE-acceptance service time in CPU cycles; min/max/histogram are separate |
| read_outstanding_max / mean | Source-paired reads pending during the selected timestamp interval, including entering requests |
| read_return_backpressure_cycles | Valid cycles in scope when the return consumer is not ready |

Returns arriving within scope and completions of requests initiated in scope
are distinct selections. Requests can enter or leave an interval; full-run
events remain available to reconstruct them. Missing end-of-capture returns
stay pending. All valid-cycle payload observations count once only on handshake.

These are interface service times and bytes. They include queueing and consumer
backpressure, and do not identify DRAM latency, useful matrix element bytes,
instruction ownership or a causal bottleneck. Denied/corrupt are not carried on
this bypass and remain unknown. CPU/RVV read payload and architectural latency
are still unavailable. Old observers retain their original unknown fields.

Use `xsai-prof memory REPORT --output NEW_DIR` or the unified analyze overview.
The timeline includes AME read service intervals in the CPU stamp domain. An
instruction-function filter hides these asynchronous requests because their
source IDs do not establish a PC.

The real calibration in experiments/profiler-release/known-acceptance.json
passed fresh RTL correctness and checked all eight warmup/measured return
payloads against FP32 values at their request addresses. The measured call
returned four 64-byte beats (256 B), with 7-cycle service time and peak four
pending reads. Warmup returns exercise out-of-order source-ID pairing. A
subinterval also validates entering/leaving reads. This benchmark observed no
nonzero consumer backpressure; synthetic decoder coverage is identified
separately. Source review and synthetic tests alone are insufficient.
