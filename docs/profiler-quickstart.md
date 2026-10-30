# Install and use xsai-prof 0.8 beta

Requires Linux and Python 3.10 or newer. The profiler is independent of the KDA
skill and model API. It has no third-party Python runtime dependencies.

## Installation

Download a versioned wheel from the project's release artifacts, or build one
from the source checkout. Public PyPI publication has not been performed.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install /path/to/xsai_prof-0.8.0b1-py3-none-any.whl
xsai-prof --version
xsai-prof doctor
```

For source installation use `pip install .`; for development use
`pip install -e .`. Upgrade with `pip install --upgrade /path/to/new.whl`, and
uninstall with `pip uninstall xsai-prof`. Keep old evidence and reports when
upgrading. Schema and observer compatibility are explained in
[supported targets](profiler-supported-targets.md).

## First report without an RTL environment

```bash
xsai-prof demo --output demo
xsai-prof analyze demo/baseline --output analysis
```

Open analysis/index.html. Demo data is explicitly synthetic and is suitable for
learning the commands, not reporting XSAI performance.

## Set up real collection

Collection additionally requires XSAI-BLAS, nexus-am, a compatible RISC-V LLVM
toolchain, xsai-env and a built emulator with its accurate RTL receipt. These
are external dependencies; pip does not install them. Offline source/assembly
analysis also needs tools that decode the target ISA.

On a restricted system, set XSAI_PROF_STATE_HOME to a writable directory for
shared build/collection locks; the default is ~/.cache/xsai-prof. Workers that
share a runtime must use the same state directory.

```bash
xsai-prof init --output softmax.json \
  --blas /path/to/xsai-blas --noop-home /path/to/XSAI \
  --rtl-config /path/to/rtl-config.json --xsai-env /path/to/xsai-env \
  --am-home /path/to/nexus-am --llvm-home /path/to/llvm
xsai-prof doctor --config softmax.json
xsai-prof collect --config softmax.json --metrics cycles_per_call --dry-run -o preview-only
xsai-prof collect --config softmax.json --output softmax
xsai-prof status softmax
xsai-prof analyze softmax/report --output softmax-analysis
```

The default is RVV softmax upstream case 1 (n256 FP32), two independent perf
repeats, and no diagnostic trace. Check the actual shape recorded by your
selected harness. Override --kernel, --case and --backend explicitly for other
operators. Add --memory only with a reviewed memory observer to request scoped
trace as a separate diagnostic run. Keep an explicit target/config per bundle.

## Compare and recover

```bash
xsai-prof compare baseline/report candidate/report --output comparison
xsai-prof analyze candidate/report --baseline baseline/report --output analysis
xsai-prof collect --config softmax.json --output softmax --resume
```

Resume checks the original config, source and completed artifacts and keeps
failed attempts. Use a new bundle when changing inputs. status is a progress
snapshot; completed output is revalidated by report/compare/analyze.

Only independent uninstrumented RTL cycles establish performance. The overview
shows observed events and separately labels proposed validation experiments.
Null/unavailable values mean missing evidence, and must not be read as zero.

For NCU-style discovery aliases, metrics/section selection, read-only text/JSON/CSV
views and the browser opener, see [the 0.8 CLI workflow](profiler-cli-workflow.md).

See [FA/GEMM case studies](profiler-case-studies.md) for real evidence and
[memory definitions](profiler-ame-read.md) for read-return boundaries.
