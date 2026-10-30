#!/usr/bin/env python3
"""XSAI BLAS correctness and RTL profiling adapter (Python standard library)."""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from kda_paths import ROOT, VENDOR, SOURCE_TREE, runtime_locks
BLAS = ROOT / "dependencies/xsai-blas"


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, data):
    path = Path(path)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as f:
        json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")
        temporary = f.name
    os.replace(temporary, path)


def revision(path):
    # A private snapshot inside a Git workspace must not inherit the containing
    # project's revision. Only an exact repository/worktree root has a revision.
    path = Path(path).resolve()
    top = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"],
                         text=True, capture_output=True)
    if top.returncode != 0 or Path(top.stdout.strip()).resolve() != path:
        return None
    result = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                            text=True, capture_output=True)
    return result.stdout.strip() if result.returncode == 0 else None


def source_identity(path):
    """Include working source changes, not only the upstream Git revision."""
    h = hashlib.sha256()
    files = sorted(p for p in path.rglob("*") if p.is_file()
                   and p.name != ".xsai-kda.lock"
                   and not set(p.relative_to(path).parts) & {".git", "build", "profile", "__pycache__"})
    for p in files:
        h.update(str(p.relative_to(path)).encode() + b"\0")
        h.update(bytes.fromhex(digest(p)))
    return {"revision": revision(path), "sha256": h.hexdigest()}


class Run:
    def __init__(self, args, kind):
        base = Path(args.runs).resolve()
        base.mkdir(parents=True, exist_ok=True)
        self.path = Path(tempfile.mkdtemp(prefix=dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + kind + "-", dir=base))
        self.data = {"schema_version": 1, "kind": kind, "status": "running",
                     "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                     "source": source_identity(Path(args.blas).resolve()), "commands": [],
                     "artifacts": {}, "selection": {"kernel": args.kernel, "case": args.case},
                     "backend": args.backend, "performance_eligible": False}
        self.save()

    def save(self):
        write_json(self.path / "manifest.json", self.data)

    def command(self, command, name, cwd=None, env=None):
        command = [str(x) for x in command]
        entry = {"argv": command, "cwd": str(cwd or ROOT), "log": name + ".log"}
        self.data["commands"].append(entry)
        self.save()
        print("+", " ".join(command), flush=True)
        with (self.path / entry["log"]).open("w") as output:
            result = subprocess.run(command, cwd=cwd or ROOT, env=env,
                                    stdout=output, stderr=subprocess.STDOUT)
        entry["exit_code"] = result.returncode
        self.data["artifacts"][entry["log"]] = {"sha256": digest(self.path / entry["log"])}
        self.save()
        text = (self.path / entry["log"]).read_text(errors="replace")
        if result.returncode:
            print(text[-5000:], file=sys.stderr)
            raise RuntimeError(f"{name} failed ({result.returncode}); see {self.path / entry['log']}")
        return text

    def artifact(self, source, name=None):
        source = Path(source)
        target = self.path / (name or source.name)
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        self.data["artifacts"][target.name] = {"sha256": digest(target)}
        self.save()
        return target

    def finish(self):
        self.data["status"] = "passed"
        self.save()
        print(f"Run: {self.path}")


def check_correctness(text):
    match = re.search(r"---\s+(\d+) passed,\s+(\d+) failed,\s+(\d+) skipped\s+---", text)
    if not match:
        raise RuntimeError("No BLAS correctness summary in output")
    passed, failed, skipped = map(int, match.groups())
    if failed or not passed:
        raise RuntimeError(f"Correctness gate rejected: {passed} passed, {failed} failed, {skipped} skipped")
    # Upstream counts every case outside KERNEL/CASE as skipped as well.
    return {"passed": passed, "failed": failed, "reported_skipped": skipped}


def performance_rows(text):
    rows = []
    # The operator description can contain spaces; parse numerical columns from the right.
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 10 or fields[-9] not in {"RVV-FP32", "CUTE-INT8", "SCALAR"}:
            continue
        try:
            numbers = list(map(float, fields[-8:-1]))
            peak = float(fields[-1].rstrip("%"))
        except ValueError:
            continue
        rows.append(dict(zip(["op", "unit", "cycles_per_run", "instret_per_run", "ipc",
                              "modeled_gops", "effective_gbps", "arithmetic_intensity",
                              "elements_per_cycle", "modeled_peak_pct"],
                             [" ".join(fields[:-9]), fields[-9], *numbers, peak])))
    if not rows or any(r["cycles_per_run"] <= 0 or not all(math.isfinite(v) for v in r.values() if isinstance(v, float)) for r in rows):
        raise RuntimeError("No positive BLAS performance measurements found")
    return rows


def qemu_path():
    return os.environ.get("QEMU_RISCV64") or shutil.which("qemu-riscv64") or str(ROOT / ".tools/qemu/usr/bin/qemu-riscv64-static")


def hpm_measurements(text, event_coding=None):
    """Resolve selectors against this RTL build; preserve upstream labels as claims."""
    coding = {(r["group"].casefold(), int(r["id"])): r for r in (event_coding or [])}
    rows = []
    pattern = (r"\[xsai-blas-hpm\] counter=(\d+) event=(\S+)\s+config=0x([0-9a-fA-F]+)"
               r"\s+total=\s*(\d+)\s+per_run=\s*([\d.eE+-]+)")
    for match in re.finditer(pattern, text):
        counter, label, encoded, total, per_run = match.groups()
        counter, selector = int(counter), int(encoded, 16)
        group = next((g for lo, hi, g in [(3, 10, "frontend"), (11, 18, "backend"),
                     (19, 26, "memblock"), (27, 31, "l2 cache")] if lo <= counter <= hi), None)
        ids = [(selector >> shift) & 1023 for shift in (0, 10, 20, 30)]
        events = [coding.get((group, event_id), {}) for event_id in ids]
        names = [event["name"].strip() if event.get("name") is not None else None
                 for event in events]
        operators = []
        for shift in (40, 45, 50):
            op = (selector >> shift) & 31
            operators.append("and" if op & 1 else "xor" if op & 2 else "add" if op & 4 else "or")
        value = float(per_run)
        if not math.isfinite(value) or value < 0:
            raise RuntimeError("Invalid HPM per-run count")
        resolved = all(name is not None for name in names)
        simple = ids[1:] == [0, 0, 0] and operators == ["or"] * 3
        rows.append({"counter": counter, "upstream_label": label, "group": group,
                     "config": "0x" + encoded, "total": int(total), "per_run": value,
                     "event_ids": ids, "rtl_event_names": names, "operators": operators,
                     "rtl_event_signals": [event.get("signal") for event in events],
                     "encoding_resolved": resolved,
                     "upstream_label_matches_rtl": label == names[0] if resolved and simple else None})
    if not rows:
        raise RuntimeError("HPM mode produced no parseable hardware counter rows")
    return rows


def validate_rtl_inputs(config, emu):
    """Check an optional build receipt's emulator and external memory-model inputs."""
    try:
        receipt = json.loads(Path(config).read_text())
    except (ValueError, UnicodeError):
        return {}
    if not isinstance(receipt, dict):
        return {}
    expected = receipt.get("emulator", {}).get("sha256")
    if expected and digest(emu) != expected:
        raise RuntimeError("RTL build receipt does not match the emulator binary")
    for item in receipt.get("runtime_inputs", []):
        path = Path(item["path"])
        if not path.is_file() or digest(path) != item["sha256"]:
            raise RuntimeError(f"RTL runtime input changed or missing: {path}")
    return receipt


def selected(args):
    flags = ["--kernel", args.kernel] if args.kernel else []
    if args.case is not None:
        flags += ["--case", str(args.case)]
    return flags


def blas_lock(args):
    directory = Path(args.blas).resolve() / "build"
    directory.mkdir(parents=True, exist_ok=True)
    return (directory / ".xsai-kda.lock").open("a")


def std_test(args, run):
    blas = Path(args.blas).resolve()
    cross = args.target == "qemu"
    build = run.path / "build"
    configure = ["cmake", "-S", blas, "-B", build, "-DRUNTIME=std", f"-DBACKEND={args.backend}",
                 "-DXSAI_BLAS_BUILD_REF=ON", "-DXSAI_BLAS_ENABLE_FAST_MATH=OFF", "-DCMAKE_BUILD_TYPE=Release"]
    if cross:
        configure += [f"-DCMAKE_TOOLCHAIN_FILE={blas / 'cmake/riscv64-linux.cmake'}", "-DTOOLCHAIN_TYPE=GCC", "-DMARCH=rv64gc"]
    run.command(configure, "configure")
    run.command(["cmake", "--build", build, "--parallel", str(args.jobs)], "build")
    compiler = "riscv64-linux-gnu-gcc" if cross else "cc"
    elf = run.path / "test-ops.elf"
    command = [compiler, "-O2", "-g", "-DRUNTIME_STD"]
    if cross:
        command += ["-static", "-march=rv64gc"]
    for directory in ("include", "kernel", "kernel/riscv64", "platform/include"):
        command += ["-I", blas / directory]
    command += sorted((blas / "test").glob("*.c"))
    command += [build / "xsai-blas.a", build / "xsai-blas-ref.a", "-lm", "-o", elf]
    run.command(command, "link")
    run.artifact(elf)
    invocation = [qemu_path(), elf] if cross else [elf]
    if cross:
        run.data["runner"] = {"path": qemu_path(), "sha256": digest(qemu_path())}
    result = run.command([*invocation, "test", *selected(args)], "correctness")
    print(result.strip())
    run.data.update({"target": args.target, "mode": "test", "fast_math": False,
                     "correctness": check_correctness(result),
                     "metric_semantics": "correctness only; host and QEMU timing are not XSAI RTL cycles"})


def image(args, run, mode, instrument="none"):
    # Independent BLAS checkouts still share nexus-am's generated archives.
    # Keep the lock outside AM_HOME so it does not change runtime provenance.
    lock_directory = runtime_locks()
    lock_directory.mkdir(parents=True, exist_ok=True)
    with (lock_directory / ".image-build.lock").open("a") as shared_lock:
        fcntl.flock(shared_lock, fcntl.LOCK_EX)
        # Preserve the checkout's historical lock for callers on earlier versions.
        if SOURCE_TREE or (ROOT / "scripts/xsai_kda.py").is_file():
            legacy = ROOT / "runs"
            legacy.mkdir(parents=True, exist_ok=True)
            with (legacy / ".image-build.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                return _image(args, run, mode, instrument)
        return _image(args, run, mode, instrument)


def _image(args, run, mode, instrument="none"):
    if not os.environ.get("AM_HOME"):
        raise RuntimeError("AM_HOME must point to a nexus-am checkout; source xsai-env/env.sh or set it explicitly")
    blas = Path(args.blas).resolve()
    command = ["make", "-C", blas, "image", f"MODE={mode}", f"BACKEND={args.backend}",
               f"TOOLCHAIN={args.toolchain}", f"ARCH={args.arch}", f"RVV_ENABLE={args.rvv_enable}",
               f"HPM={'yes' if instrument == 'hpm' else 'no'}", f"HPM_PROFILE={args.hpm_profile}",
               f"PERFCCT_MARKERS={'yes' if instrument == 'trace' else 'no'}",
               f"PROFILE_DEBUG_INFO={'yes' if instrument == 'trace' else 'no'}"]
    if args.kernel:
        command += [f"KERNEL={args.kernel}"]
    if args.case is not None:
        command += [f"CASE={args.case}"]
    run.command(command, f"image-{mode}")
    stem = blas / f"test/build/test-ops-{args.arch}"
    binary = run.artifact(stem.with_suffix(".bin"), f"{mode}.bin")
    elf = run.artifact(stem.with_suffix(".elf"), f"{mode}.elf")
    if instrument == "trace" and (blas / ".xsai-prof-capture.json").is_file():
        import kda_capture
        capture = json.loads((blas / ".xsai-prof-capture.json").read_text())
        if capture.get("ranges"):
            import kda_profile
            encodings = kda_profile.analyzer_module().elf_instruction_encodings(
                elf, args.objdump, args.objdump_mattr)
            expected = [1443, 1444]
            for stage in capture['ranges']['stages']:
                expected.extend((stage['begin_imm'], stage['end_imm']))
            if not all(kda_capture.instruction(i) in encodings.values() for i in expected):
                raise RuntimeError("Requested invocation/stage markers absent from linked ELF; verify kernel build flags/backend before RTL collection")
    run.data["build_environment"] = {key: os.environ.get(key) for key in ("AM_HOME", "LLVM_HOME", "RISCV", "MARCH")}
    run.data["runtime_source"] = source_identity(Path(os.environ["AM_HOME"]).resolve())
    run.data["rvv_enable"] = args.rvv_enable
    run.data["test_harness"] = {
        str(path.relative_to(blas)): digest(path)
        for path in sorted((blas / "test").iterdir())
        if path.is_file() and (path.suffix in {".c", ".h"} or path.name == "Makefile")
    }
    compiler_variables = ("CFLAGS", "CPPFLAGS", "CC_OPT", "ASFLAGS", "LDFLAGS", "PERF_MAX_RUNS", "PERF_TARGET_FLOPS", "PERF_CPU_HZ", "CMAKE_TOOLCHAIN_FILE")
    run.data["build_overrides"] = {key: os.environ.get(key) for key in compiler_variables}
    compiler = (Path(os.environ.get("LLVM_HOME", "")) / "bin/clang") if args.toolchain == "LLVM" else Path(shutil.which("riscv64-linux-gnu-gcc") or "missing")
    run.data["compiler"] = {"path": str(compiler), "sha256": digest(compiler)}
    run.data["toolchain"] = args.toolchain
    run.data["arch"] = args.arch
    run.save()
    return binary, elf


def analyze(args, run, database, elf):
    run.artifact(database, "chiseldb.db")
    run.artifact(elf, "profile.elf")
    # Prefer the newer full profiler from the user's environment when available.
    profiler = Path(args.xsai_env).resolve() / "scripts/xsai-blas/analyze_perfcct.py"
    if profiler.is_file():
        command = [sys.executable, profiler, run.path / "chiseldb.db", "--elf", run.path / "profile.elf",
                   "--out-json", run.path / "pc_hotspots.json", "--out-md", run.path / "pc_hotspots.md",
                   "--roi-output", run.path / "roi"]
        if (run.path / "perf.log").exists():
            command += ["--run-log", run.path / "perf.log"]
        run.data["analyzer"] = {"kind": "xsai-env-perfcct", "path": str(profiler), "sha256": digest(profiler)}
    else:
        profiler = VENDOR / "roi_hotspots.py"
        command = [sys.executable, Path(__file__).with_name("kda_roi.py"), "--db", run.path / "chiseldb.db", "--elf", run.path / "profile.elf",
                   "--output", run.path / "roi", "--window", str(args.window), "--top", str(args.top)]
        for option in ("objdump", "addr2line", "readelf", "objdump_mattr"):
            value = getattr(args, option, None)
            if value:
                command += ["--" + option.replace("_", "-"), value]
        run.data["analyzer"] = {"kind": "vendored-roi", "sha256": digest(profiler)}
        run.data["analyzer"]["scope_adapter_sha256"] = digest(Path(__file__).with_name("kda_roi.py"))
    run.command(command, "analyze")
    expected = [run.path / "pc_hotspots.json", run.path / "pc_hotspots.md"] if run.data["analyzer"]["kind"] == "xsai-env-perfcct" else [run.path / "roi/hotspots.json", run.path / "roi/index.html"]
    if any(not p.is_file() for p in expected):
        raise RuntimeError("Analyzer exited without the required profiling reports")
    for p in expected:
        run.data["artifacts"][str(p.relative_to(run.path))] = {"sha256": digest(p)}
    for p in sorted((run.path / "roi").glob("*")):
        if p.is_file():
            run.data["artifacts"][str(p.relative_to(run.path))] = {"sha256": digest(p)}
    run.data["metric_semantics"] = "retirement gaps are attribution, not exclusive function execution time"


def rtl(args, run):
    noop = Path(args.noop_home).resolve()
    emu = noop / "build/emu"
    if not emu.is_file() or not os.access(emu, os.X_OK):
        raise RuntimeError(f"RTL emulator unavailable: {emu}; doctor records the missing prerequisites")
    config = Path(args.rtl_config).resolve()
    if not config.is_file():
        raise RuntimeError(f"RTL configuration file does not exist: {config}")
    receipt = validate_rtl_inputs(config, emu)
    isolated = getattr(args, "isolate_outputs", False)
    if isolated and args.mode == "trace":
        raise RuntimeError("Trace uses the original serialized emulator; isolated output mode is non-trace only")
    run.artifact(config, "rtl-config" + config.suffix)
    run.data.update({"target": "rtl", "mode": args.mode,
                     "rtl": {"emu_sha256": digest(emu), "config_sha256": digest(config), "revision": revision(noop)},
                     "instrumentation": args.mode if args.mode in {"hpm", "trace"} else "none"})
    from kda_capture import RECEIPT
    capture_path = Path(args.blas).resolve() / RECEIPT
    if capture_path.is_file():
        run.artifact(capture_path, "capture.json")
    run.data["output_isolation"] = isolated
    # The runtime filename helper honors NOOP_HOME before its compiled fallback.
    # Pin it to the selected emulator so relinked observers do not write traces
    # into another checkout's build directory.
    simulator_env = {**os.environ, "NOOP_HOME": str(noop)}
    scope = getattr(args, "trace_scope", "full")
    memory_trace = getattr(args, "memory_trace", False)
    if scope != "full" or memory_trace:
        from kda_observer import reviewed
        if args.mode != "trace" or not reviewed(receipt):
            raise RuntimeError("Filtered/memory trace requires trace mode and reviewed observer")
    simulator_env["XSAI_PROF_SCOPE"] = scope if args.mode == "trace" else "full"
    from kda_observer import cpu_reviewed
    if cpu_reviewed(receipt):
        simulator_env["XSAI_PROF_DB"] = str((run.path / "cpu-observer.db").resolve())
    run.data["trace_capture"] = {"scope": scope, "memory": memory_trace, "environment": {"XSAI_PROF_SCOPE": simulator_env["XSAI_PROF_SCOPE"]}}
    def invocation(binary, stage):
        command = [emu, "-i", binary, "--no-diff"]
        if isolated or receipt.get("clock_bridge"):
            directory = run.path / ("dramsim3-" + stage)
            directory.mkdir()
            command += ["--dramsim3-outdir", directory]
        return command
    for index, item in enumerate(receipt.get("runtime_inputs", [])):
        run.artifact(item["path"], f"rtl-runtime-{index}-" + Path(item["path"]).name)
    # Both image builds reuse upstream output paths; serialize them and trace collection.
    with blas_lock(args) as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with (emu.parent / ".xsai-kda.lock").open("a") as emu_lock:
            fcntl.flock(emu_lock, fcntl.LOCK_EX)
            binary, _ = image(args, run, "test")
            text = run.command(invocation(binary, "test"), "correctness", cwd=emu.parent, env=simulator_env)
            run.data["correctness"] = check_correctness(text)
            validate_rtl_inputs(config, emu)
            if args.mode == "test":
                return
            binary, elf = image(args, run, "perf", args.mode)
            command = invocation(binary, "perf")
            # ChiselDB's generated C++ may retain the source checkout's build
            # directory even when the emulator is run from an isolated copy.
            # Snapshot both locations so the newly written DB can be paired
            # with the ELF from this exact run.
            db_roots = [emu.parent, ROOT / "dependencies/xsai-env/XSAI/build"]
            if cpu_reviewed(receipt):
                db_roots.append(run.path)
            db_paths = {p for root in db_roots if root.is_dir() for p in root.glob("*.db")}
            before = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in db_paths}
            if args.mode == "trace":
                tables = "lifetime CUTE" if args.backend == "ame" else "lifetime"
                if memory_trace:
                    tables += " TLAEvent TLDEvent"
                run.data["trace_table_selection"] = tables.split()
                command += ["--dump-db", "--dump-select-db", tables]
                if args.fork:
                    command += ["--enable-fork"]
            text = run.command(command, "perf", cwd=emu.parent, env=simulator_env)
            validate_rtl_inputs(config, emu)
            run.data["measurements"] = performance_rows(text)
            if args.mode == "hpm":
                if "[xsai-blas-hpm] counter=" not in text:
                    raise RuntimeError("HPM mode produced no hardware counter rows")
                run.data["hpm_rows"] = [line for line in text.splitlines() if line.startswith("[xsai-blas-hpm]")]
                run.data["hpm_measurements"] = hpm_measurements(text, receipt.get("hpm_event_coding"))
                run.data["hpm_labels"] = {
                    "encoding_resolved": all(r["encoding_resolved"] for r in run.data["hpm_measurements"]),
                    "mismatched_counters": sorted({r["counter"] for r in run.data["hpm_measurements"]
                                                  if r["upstream_label_matches_rtl"] is False}),
                    "interpretation": "Use RTL event names and operators; upstream labels may be stale"}
            if len(run.data["measurements"]) != run.data["correctness"]["passed"]:
                raise RuntimeError("Performance case coverage differs from the passing correctness cases")
            if args.mode == "trace":
                after_paths = {p for root in db_roots if root.is_dir() for p in root.glob("*.db")}
                candidates = [p for p in after_paths
                              if before.get(p) != (p.stat().st_mtime_ns, p.stat().st_size)]
                if len(candidates) != 1:
                    raise RuntimeError(f"Expected one new ChiselDB, found {len(candidates)}; refusing to pair an ambiguous DB/ELF")
                analyze(args, run, candidates[0], elf)
            run.data["performance_eligible"] = args.mode == "perf"
            if args.mode == "perf":
                run.data["metric_semantics"] = "uninstrumented RTL cycles/run; Gop/s and peak% depend on upstream model assumptions"


def validate_nemu_configuration(home, backend):
    config = Path(home) / ".config"
    if backend == "ame":
        if not config.is_file() or "CONFIG_RVMATRIX=y" not in config.read_text().splitlines():
            raise RuntimeError("AME requires NEMU built with CONFIG_RVMATRIX=y; "
                               "use riscv64-matrix-xs_defconfig in a separate build")


def nemu(args, run):
    home = Path(args.nemu_home).resolve()
    runner = home / "build/riscv64-nemu-interpreter"
    if not runner.is_file() or not os.access(runner, os.X_OK):
        raise RuntimeError(f"Runnable NEMU unavailable: {runner}; a difftest -so library is not an executable")
    validate_nemu_configuration(home, args.backend)
    run.data.update(target="nemu", mode=args.mode,
                    runner={"path": str(runner), "sha256": digest(runner), "revision": revision(home)})
    runner = run.artifact(runner, "nemu-runner")
    if (home / ".config").is_file():
        run.artifact(home / ".config", "nemu.config")
    with blas_lock(args) as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        binary, _ = image(args, run, "test")
        text = run.command([runner, "-b", binary], "correctness", cwd=home)
        run.data["correctness"] = check_correctness(text)
        if args.mode == "perf":
            binary, _ = image(args, run, "perf")
            text = run.command([runner, "-b", binary], "perf", cwd=home)
            run.data["measurements"] = performance_rows(text)
    run.data["metric_semantics"] = "NEMU instruction/counter model for screening only; not XSAI RTL performance"


def load_run(path):
    path = Path(path).resolve()
    if path.is_dir():
        path /= "manifest.json"
    data = json.loads(path.read_text())
    if data.get("status") != "passed":
        raise RuntimeError(f"Run did not pass: {path}")
    for name, entry in data["artifacts"].items():
        artifact = path.parent / name
        if not artifact.is_file() or digest(artifact) != entry["sha256"]:
            raise RuntimeError(f"Artifact changed or missing: {artifact}")
    return data


def compare_runs(baseline, candidate):
    for data in (baseline, candidate):
        if not data.get("performance_eligible") or data.get("target") != "rtl" or data.get("instrumentation") != "none":
            raise RuntimeError("Ranking requires uninstrumented RTL performance runs")
        check = data.get("correctness", {})
        if check.get("failed") != 0 or not check.get("passed") or check["passed"] != len(data.get("measurements", [])):
            raise RuntimeError("Ranking requires a passing correctness gate")
    for key in ("selection", "rtl", "arch", "toolchain", "build_environment", "compiler", "runtime_source", "build_overrides", "rvv_enable", "test_harness"):
        if baseline.get(key) != candidate.get(key):
            raise RuntimeError(f"Incomparable runs: {key} differs")
    old = {(r["op"], r["unit"]): r for r in baseline["measurements"]}
    new = {(r["op"], r["unit"]): r for r in candidate["measurements"]}
    if len(old) != len(baseline["measurements"]) or len(new) != len(candidate["measurements"]):
        raise RuntimeError("Ambiguous comparison: duplicate operator descriptions")
    if any(not math.isfinite(r["cycles_per_run"]) or r["cycles_per_run"] <= 0 for r in [*old.values(), *new.values()]):
        raise RuntimeError("Ranking requires finite, positive cycles")
    if not old or old.keys() != new.keys():
        raise RuntimeError("Incomparable runs: operator shapes or units differ")
    return [{"op": op, "unit": unit, "baseline_cycles": old[(op, unit)]["cycles_per_run"],
             "candidate_cycles": new[(op, unit)]["cycles_per_run"],
             "speedup": old[(op, unit)]["cycles_per_run"] / new[(op, unit)]["cycles_per_run"]}
            for op, unit in old]


def doctor(args):
    paths = {"blas": Path(args.blas), "xsai_env": Path(args.xsai_env),
             "am": Path(os.environ.get("AM_HOME", str(Path(args.xsai_env) / "nexus-am"))),
             "rtl_emu": Path(args.noop_home) / "build/emu", "qemu": Path(qemu_path()),
             "nemu": Path(args.nemu_home) / "build/riscv64-nemu-interpreter"}
    report = {"paths": {k: {"path": str(p.resolve()), "exists": p.exists(), "executable_file": p.is_file() and os.access(p, os.X_OK)} for k, p in paths.items()},
              "commands": {name: shutil.which(name) for name in ("cmake", "cc", "riscv64-linux-gnu-gcc", "readelf", "riscv64-linux-gnu-objdump")},
              "source": source_identity(Path(args.blas).resolve()),
              "profiling": {"documented_analyzer": (Path(args.xsai_env) / "scripts/xsai-blas/analyze_perfcct.py").is_file(),
                            "vendored_roi_analyzer": (VENDOR / "roi_hotspots.py").is_file()},
              "rtl_ready": (paths["rtl_emu"].is_file() and os.access(paths["rtl_emu"], os.X_OK) and (paths["am"] / "Makefile.app").is_file())}
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if args.output:
        write_json(args.output, report)


def main():
    import kda_profile
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--blas", default=str(BLAS))
    p.add_argument("--xsai-env", default=os.environ.get("XSAI_ENV_HOME", str(ROOT / "dependencies/xsai-env")))
    p.add_argument("--noop-home", default=os.environ.get("NOOP_HOME", str(ROOT / "dependencies/xsai-env/XSAI")))
    p.add_argument("--nemu-home", default=os.environ.get("NEMU_HOME", str(ROOT / "dependencies/NEMU")))
    p.add_argument("--runs", default=str(ROOT / "runs"))
    sub = p.add_subparsers(dest="command", required=True)
    kda_profile.add_parser(sub)
    d = sub.add_parser("doctor", help="Report available tools and profiling prerequisites")
    d.add_argument("--output", type=Path)
    for name in ("test", "rtl", "nemu", "analyze"):
        s = sub.add_parser(name)
        s.add_argument("--kernel", default="matmul" if name != "analyze" else None)
        s.add_argument("--case", type=int)
        s.add_argument("--backend", choices=["generic", "scalar", "rvv", "ame", "triton"], default="generic")
        if name == "test":
            s.add_argument("--target", choices=["host", "qemu"], default="host")
            s.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 1))
        if name in {"rtl", "nemu"}:
            s.add_argument("--mode", choices=["test", "perf", "hpm", "trace"] if name == "rtl" else ["test", "perf"], default="perf")
            s.add_argument("--arch", default="riscv64-xs")
            s.add_argument("--toolchain", choices=["LLVM", "GNU"], default="LLVM")
            s.add_argument("--rvv-enable", choices=["yes", "no"], default="no")
            s.add_argument("--hpm-profile", choices=["memstall", "default"], default="memstall")
        if name == "rtl":
            s.add_argument("--rtl-config", required=True, help="RTL build configuration file, hashed for comparability")
            s.add_argument("--isolate-outputs", action="store_true", help="Use per-run DRAMsim3 output directories (non-trace workers)")
            s.add_argument("--trace-scope", default="full", help="Reviewed observer scope: full, invocation or stage:INDEX")
            s.add_argument("--memory-trace", action="store_true", help="Reviewed observer compact AME A/D capture")
            s.add_argument("--fork", action="store_true")
        if name in {"rtl", "analyze"}:
            s.add_argument("--window", type=int, default=1)
            s.add_argument("--top", type=int, default=30)
            s.add_argument("--objdump", default=shutil.which("riscv64-linux-gnu-objdump"))
            s.add_argument("--addr2line", default=shutil.which("riscv64-linux-gnu-addr2line"))
            s.add_argument("--readelf", default=shutil.which("readelf"))
            s.add_argument("--objdump-mattr", default=os.environ.get("OBJDUMP_MATTR", ""))
        if name == "analyze":
            s.add_argument("--db", type=Path, required=True)
            s.add_argument("--elf", type=Path, required=True)
    c = sub.add_parser("compare", help="Compare two verified, uninstrumented RTL runs")
    c.add_argument("baseline")
    c.add_argument("candidate")
    c.add_argument("--output", type=Path)
    args = p.parse_args()
    if getattr(args, "case", None) is not None and (args.case < 0 or not args.kernel):
        p.error("--case requires --kernel and must be non-negative")
    if args.command == "test" and args.backend != "generic":
        p.error("host/QEMU bring-up currently supports generic; use rtl for architecture backends")
    run = None
    try:
        if args.command == "profile":
            return kda_profile.dispatch(args, sys.modules[__name__]) or 0
        elif args.command == "doctor":
            doctor(args)
        elif args.command == "compare":
            result = compare_runs(load_run(args.baseline), load_run(args.candidate))
            print(json.dumps(result, indent=2))
            if args.output:
                write_json(args.output, result)
        else:
            run = Run(args, args.command)
            if args.command == "test":
                std_test(args, run)
            elif args.command == "rtl":
                rtl(args, run)
            elif args.command == "nemu":
                nemu(args, run)
            else:
                analyze(args, run, args.db, args.elf)
            run.finish()
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        if run:
            run.data.update(status="failed", error=str(exc))
            run.save()
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
