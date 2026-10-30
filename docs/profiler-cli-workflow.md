# xsai-prof 0.8: CLI and offline report workflow

The tool adopts NCU's discovery/selection/report workflow and msOpProf
simulator's collect/parse/view organization. Commands and metrics remain XSAI
specific. Existing 0.7 commands and saved evidence remain supported.

## Discover and preview

```sh
xsai-prof --query-metrics --filter ame_read --format text
xsai-prof --list-sections
xsai-prof --list-sets
xsai-prof query metrics --section memory --format csv -o memory-catalog.csv
xsai-prof collect --config operator.json --metrics cycles_per_call --dry-run -o planned-run
xsai-prof collect --config operator.json --section memory --dry-run -o planned-memory
```

The three top-level discovery flags are aliases for query metrics/sections/sets.
Use `--section` or `--sections`, `--set`, and space/comma separated `--metrics`
to request supported measurements. Explicit metrics extend a selected section
or set. Shared modes execute once, not once per requested metric. HPM requests
use the configured native HPM profile/custom event selection, not arbitrary
GPU-style counter names. Native stages may record additional metrics.

Selectors can accompany --config. They replace its previous selection and
diagnostics; environment, operator, shape, backend, perf repeats and build
settings remain fixed. Trace-only ranges/capture/CUTE settings are removed
when this explicit override does not select trace; memory capture is removed
when it does not select memory. Requesting a different capture policy may
change source annotation identity; compare checks still apply.

Dry-run reads configuration and prerequisite identities. It does not create
the output bundle, take collection locks, freeze sources, compile, or run an
emulator. Exit 0 means the preview's checks passed, not measured correctness
or performance; exit 1 means a requirement is blocked. Unknown metrics are
rejected; unreviewed memory capabilities are explained rather than inferred.
Wall-time estimate stays null. Fresh stage counts include one correctness
and one measurement emulator invocation per stage; harness repetitions are
different. Resume can reuse successful stages only after full revalidation.

## Collect and read

```sh
xsai-prof collect --config operator.json --metrics ame_read_payload_bytes,ame_read_service_cycles -o run
xsai-prof status run
xsai-prof view run --page memory --format text
xsai-prof report run --page memory --metrics ame_read_payload_bytes --format json
xsai-prof view run --page source --function update --top 30
xsai-prof view run --metrics cycles_per_call --format csv -o perf.csv
xsai-prof view candidate --page comparison --baseline baseline --format csv -o changes.csv
```

`view` and `report REPORT` read existing verified report/collection evidence;
they never recollect. `report --spec ... -o NEW_DIRECTORY` retains the previous
report-building behavior. View -o writes a new file, while collection/analysis
-o creates a new directory. No outputs overwrite saved reports or raw runs.
Filters omit unrelated global rows instead of assigning them to a function.
`--top` is an explicit display limit. JSON records matched/shown row counts;
text announces truncation. CSV keeps unavailable numeric cells empty with an
explicit status/reason column. Comparison cycles use medians of independent
perf samples; speedup has its own dimensionless column. Missing data is not 0.

## Open and inspect

```sh
xsai-prof analyze run/report --baseline baseline/report -o analysis
xsai-prof open analysis
xsai-prof open analysis --no-browser
```

Open verifies local report/analysis hashes and raw input identities before
attempting browser launch. On a remote host, --no-browser prints the location;
copy/import the data to a host with a browser as needed. No server is started.
The offline HTML uses embedded data, works through file://, and requires no
network/CDN. New views show performance, hotspot tables, actual AME return
bytes/service/outstanding, separate CPU/RVV request/PMA metrics, comparisons,
and explicitly untested experiments with predictions and falsifiers.

The timeline caps display by event type so asynchronous AME returns remain
visible beside instruction residence. Cap counts are explicit. Clicking an
asynchronous AME event opens memory details; no PC ownership is fabricated.
Unaligned CUTE task clocks remain independent of CPU range selection.

Only original independent uninstrumented RTL cycles establish speedup. AME
interface beats are not DRAM bytes, and service time is not architectural
instruction latency. CPU/RVV coverage remains partial. Observation-only replays
retain their original independent performance identity and warning.

## CLI correspondence

| Task | xsai-prof | Reference workflow |
| --- | --- | --- |
| Discover | query metrics/sections/sets and discovery aliases | NCU query/list flags |
| Select | collect --metrics / --section / --set | NCU metrics/section/set selection; msOpProf metric modes |
| Preview | collect --dry-run | Explicit XSAI simulation stage plan |
| Inspect | view/report REPORT --page ... --format ... | NCU report pages and CLI/CSV output |
| Visualize | analyze, then open | NCU UI or msOpProf results + MindStudio Insight |
| Migrate | export/import | Offline report/trace workflows; XSAI archive identity checks |

This does not implement NCU file formats, NVIDIA counters, arbitrary CUDA
application launches or msOpProf's full feature set. Collection currently uses
the supported XSAI-BLAS harness and explicit external RTL/toolchain dependencies.
