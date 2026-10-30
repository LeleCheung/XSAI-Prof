#!/usr/bin/env bash
# Collect a marker-delimited LifeTimeCommitTrace and build an ROI hotspot report.
# This target is intentionally separate from normal perf runs: ChiselDB and the
# lifetime trace are far too expensive to include in a benchmark measurement.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
XSAI_BLAS_HOME="${XSAI_BLAS_HOME:-$(cd "$SCRIPT_DIR/.." && pwd)}"
XSAI_ENV_HOME="${XSAI_ENV_HOME:-$(cd "$XSAI_BLAS_HOME/.." && pwd)}"
NOOP_HOME="${NOOP_HOME:-$XSAI_ENV_HOME/XSAI}"
ARCH="${ARCH:-riscv64-xs}"
BACKEND="${BACKEND:-generic}"
KERNEL="${KERNEL:-}"
CASE="${CASE:-}"
# Keep every deep-profile run separate by default.  A ChiselDB trace must be
# paired with the exact ELF that produced it, so overwriting a prior directory
# makes later hotspot comparisons error-prone.  Set PROFILE_DIR explicitly
# when a stable path is required by automation.
PROFILE_TIMESTAMP="${PROFILE_TIMESTAMP:-$(date +%Y%m%d-%H%M%S)}"
PROFILE_DIR="${PROFILE_DIR:-$XSAI_BLAS_HOME/profile/${BACKEND}-${KERNEL}-case${CASE}-${PROFILE_TIMESTAMP}}"
PROFILE_DIR="$(mkdir -p "$PROFILE_DIR" && cd "$PROFILE_DIR" && pwd)"
PROFILE_DB="${PROFILE_DB:-$PROFILE_DIR/chiseldb.db}"
PROFILE_RUN_LOG="${PROFILE_RUN_LOG:-$PROFILE_DIR/emulator.log}"
PROFILE_JSON="${PROFILE_JSON:-$PROFILE_DIR/hotspots.json}"
PROFILE_REPORT="${PROFILE_REPORT:-$PROFILE_DIR/perfcct.txt}"
PROFILE_TOP="${PROFILE_TOP:-${PERFCCT_TOP:-30}}"
FORK="${FORK:-1}"
DIFF="${DIFF:-0}"
DB_SELECT="${DB_SELECT:-lifetime}"
PERFCCT_ANALYZER="${PERFCCT_ANALYZER:-python3}"
OBJDUMP_MATTR="${OBJDUMP_MATTR:-}"

[[ -n "$KERNEL" ]] || { echo "KERNEL is required" >&2; exit 2; }
[[ "$CASE" =~ ^[0-9]+$ ]] || { echo "CASE must be a non-negative integer" >&2; exit 2; }

# Describe both the Xuantie tile format and the XSAI INT8->INT32 AME use case.
# The remaining XSAI unified raw encodings are decoded by roi_hotspots.py,
# because upstream LLVM does not yet attach mnemonics to all of them.
if [[ "$BACKEND" == "ame" && -z "$OBJDUMP_MATTR" ]]; then
  OBJDUMP_MATTR="+matrix-xuantie-0.6,+ame-i8,+ame-i32,+xxiangshaname,+zame"
fi

echo "[xsai-blas-profile] building marker-enabled payload"
build_cmd=(make -C "$XSAI_BLAS_HOME/test" image MODE=perf
  BACKEND="$BACKEND" KERNEL="$KERNEL" CASE="$CASE"
  PERFCCT_MARKERS=yes PROFILE_DEBUG_INFO=yes RVV_ENABLE="${RVV_ENABLE:-no}"
  TOOLCHAIN="${TOOLCHAIN:-LLVM}")
[[ -n "${MARCH:-}" ]] && build_cmd+=(MARCH="$MARCH")
"${build_cmd[@]}"

PAYLOAD="${PAYLOAD:-$XSAI_BLAS_HOME/test/build/test-ops-$ARCH.bin}"
ELF="${ELF:-${PAYLOAD%.bin}.elf}"
[[ -f "$PAYLOAD" ]] || { echo "payload not found: $PAYLOAD" >&2; exit 1; }
[[ -f "$ELF" ]] || { echo "ELF not found: $ELF" >&2; exit 1; }

# Keep immutable copies with the trace.  test/build is reused by later
# benchmarks, and resolving a saved trace against a subsequently rebuilt ELF
# can silently assign PCs to unrelated functions.
PROFILE_PAYLOAD="${PROFILE_PAYLOAD:-$PROFILE_DIR/$(basename "$PAYLOAD")}"
PROFILE_ELF="${PROFILE_ELF:-$PROFILE_DIR/$(basename "$ELF")}"
cp "$PAYLOAD" "$PROFILE_PAYLOAD"
cp "$ELF" "$PROFILE_ELF"

if [[ -e "$PROFILE_DB" ]]; then
  previous_db="$PROFILE_DB.previous.$(date +%Y%m%d-%H%M%S)"
  mv "$PROFILE_DB" "$previous_db"
  echo "[xsai-blas-profile] preserved previous database: $previous_db"
fi
mkdir -p "$(dirname "$PROFILE_DB")"
echo "[xsai-blas-profile] collecting LifeTimeCommitTrace: DB_SELECT=$DB_SELECT"
run_cmd=(make -C "$XSAI_ENV_HOME" run-emu-debug
  PAYLOAD="$PROFILE_PAYLOAD" FORK="$FORK" DIFF="$DIFF" LOG=1
  DB_SELECT="$DB_SELECT" DB_PATH="$PROFILE_DB")
[[ -n "${WARMUP:-}" ]] && run_cmd+=(WARMUP="$WARMUP")
[[ -n "${MAX_INSTR:-}" ]] && run_cmd+=(MAX_INSTR="$MAX_INSTR")
set +e
"${run_cmd[@]}" 2>&1 | tee "$PROFILE_RUN_LOG"
run_status=${PIPESTATUS[0]}
set -e
((run_status == 0)) || exit "$run_status"
[[ -f "$PROFILE_DB" ]] || {
  echo "no ChiselDB database was produced: $PROFILE_DB" >&2
  exit 1
}

echo "[xsai-blas-profile] decoding ROI hotspots"
"$PERFCCT_ANALYZER" "$XSAI_BLAS_HOME/scripts/roi_hotspots.py" \
  --db "$PROFILE_DB" --elf "$PROFILE_ELF" --output "$PROFILE_DIR/roi" \
  --top "$PROFILE_TOP" --objdump-mattr "$OBJDUMP_MATTR"
cp "$PROFILE_DIR/roi/hotspots.json" "$PROFILE_JSON"
cp "$PROFILE_DIR/roi/hotspots.txt" "$PROFILE_REPORT"

{
  printf 'BACKEND=%s\nKERNEL=%s\nCASE=%s\n' "$BACKEND" "$KERNEL" "$CASE"
  printf 'PROFILE_DB=%s\nPROFILE_PAYLOAD=%s\nPROFILE_ELF=%s\nDB_SELECT=%s\n' \
    "$PROFILE_DB" "$PROFILE_PAYLOAD" "$PROFILE_ELF" "$DB_SELECT"
  printf 'OBJDUMP_MATTR=%s\nROI_REPORT=%s\nPERFCCT_REPORT=%s\n' \
    "$OBJDUMP_MATTR" "$PROFILE_DIR/roi/index.html" "$PROFILE_REPORT"
} > "${PROFILE_META:-$PROFILE_DIR/profile.env}"
echo "ROI hotspot report: $PROFILE_DIR/roi/index.html"
