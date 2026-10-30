# XSAI-Prof

Independent XSAI operator profiling for humans and agents. The `xsai-prof` command collects and validates RTL measurements, binds HPM/ChiselDB evidence to the matching ELF and source, and provides terminal, JSON/CSV and offline HTML analysis.

XSAI-Prof runs without XSAI-KDA, a skill, an LLM or a model API. [XSAI-KDA](https://github.com/LeleCheung/XSAI-KDA) uses it as a separately versioned dependency to optimize kernels.

## Install

Linux, Python >=3.10. From this checkout:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
xsai-prof --version
xsai-prof doctor
```

The Python runtime uses the standard library. Building needs setuptools/wheel. Installation from this repository or a built wheel is supported; PyPI publication is not assumed.

## Try offline

```sh
xsai-prof --query-metrics
xsai-prof --list-sections
xsai-prof --list-sets
xsai-prof demo -o demo
xsai-prof view demo/baseline --format csv -o perf.csv
xsai-prof analyze demo/baseline -o analysis
xsai-prof open analysis
```

Demo values are synthetic fixtures. Existing real reports and exported evidence can be analyzed without simulation. Target ISA source/assembly views require matching readelf/objdump/addr2line tools.

## Collect actual RTL evidence

```sh
xsai-prof doctor --config operator.json
xsai-prof collect --config operator.json --metrics cycles_per_call --dry-run -o run
xsai-prof collect --config operator.json -o run
xsai-prof view run --page memory
xsai-prof compare baseline/report run/report -o comparison
```

Collection uses the XSAI-BLAS harness and explicit external BLAS, AM/runtime, toolchain, emulator and RTL configuration paths. These dependencies are not bundled. Each measurement stage first passes a correctness run. Only independent uninstrumented RTL performance establishes speedup; HPM and trace are diagnostic captures. Unknown/partial coverage stays explicit. AME interface bytes are not DRAM bytes, and request service time is not architectural instruction latency.

## Documentation and development

- [Quickstart and external configuration](docs/profiler-quickstart.md)
- [CLI selection, dry-run, filtered reports and offline UI](docs/profiler-cli-workflow.md)
- [Full profiling interface](docs/profile-cli.md)
- [Supported targets and coverage](docs/profiler-supported-targets.md)
- [Source provenance and upstream notices](docs/provenance.md)
- [Repository split record](docs/repository-split.json)

```sh
python3 -m unittest discover -s tests -v
python3 tools/build_release.py --output release
python3 tests/verify_cli_workflow_install.py --wheel release/*.whl --output workflow-install
```

Browser tests optionally use Playwright/Chromium as development dependencies. External real RTL acceptance is separate from portable software/fixture checks.

The 0.8.1 beta moves the previously validated 0.8 implementation into this independent repository. Historical operator experiments and raw captures stay in XSAI-KDA; their original identities and limitations are retained. The split does not establish any new kernel speedup.
