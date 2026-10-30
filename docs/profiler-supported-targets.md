# Supported target and compatibility

The 0.7 beta reviewed memory target is one single-core XSAI
DefaultMatrixConfig model with DRAMsim3, ChiselDB and eight emulator threads.
The original emulator SHA256 is
189681b2f3aa6fe9f51891acd9df0bb51b250305ecd970f2d0b26a619541adfd.
Source revision alone is insufficient: the recorded configuration and local
changes are retained in the build receipt. Private observers change C++
observation only, linking unchanged Verilator RTL model objects.

| Observer | Requests and writes | CPU/RVV ordinary LSU/PMA | AME read returns |
| --- | --- | --- | --- |
| Reviewed 0.5 | AME near_cute | unavailable | unavailable |
| Reviewed 0.6 | AME near_cute | available, partial coverage | unavailable |
| Reviewed 0.7 beta | AME near_cute | available, partial coverage | matrix_data_in |

Exact receipt/source/emulator identities are checked by kda_observer.py. Use
`xsai-prof doctor --config CONFIG` to see the target match and coverage. Another
build is unreviewed even if it has the same filename or configuration label.
Ordinary collection may support it, but reviewed memory semantics do not apply.
New targets need their own protocol review and real calibration.

The profiler package does not include the large emulator, BLAS checkout,
compiler, DRAM model or runtime. The reviewed receipts and build/calibration
evidence live under experiments/profiler-release locally. They are not supplied
by installing the wheel. A recipient must provision a supported environment or
use offline evidence. Installing the tool alone cannot enable RTL collection.

## Evidence compatibility

The existing profile/v1, collection/v1 and analysis/v1 containers remain readable.
New overview and memory fields are additive. Preserve the emitting version,
checksums and original DB/ELF. Legacy captures keep unavailable read-return
metrics; no data is backfilled from request size or instruction counts.

Comparisons check workload, hardware, build/runtime and source/harness identity
according to each metric's contract. A receipt hash or producer version change
is not silently accepted as a comparable measurement. Observation-only replays
of old images explicitly retain the original independent perf identity and do
not establish new speedups. Unknown DRAM and architectural latency remain null.

## Release process

`python tools/build_release.py --output NEW_DIR` builds an sdist and a wheel
from that sdist, without network access, and records SHA256s. Build dependencies
are setuptools>=61 and wheel. GitHub Actions defines Python 3.10/3.12 offline
regression/install jobs; local execution is recorded separately and does not
claim that hosted CI has run. Public release/PyPI publication is a separate
maintainer action. Verify artifacts before publishing; no credentials are
embedded in the release script.
