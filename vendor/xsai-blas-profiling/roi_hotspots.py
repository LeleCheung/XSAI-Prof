#!/usr/bin/env python3
"""Build guest-code hotspot reports for an xsai-blas marker-delimited ROI.

The input is XSAI's LifeTimeCommitTrace ChiselDB table.  The report attributes
the interval between consecutive retirement events to the instruction that
retires next.  This produces a useful, additive retirement-stall profile, but
it is not the exclusive execution time of an instruction on an out-of-order
core.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import html
import json
import math
import os
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable


BEGIN_INSN = 0x5A100013
END_INSN = 0x5A200013


def default_objdump() -> str | None:
    candidates = (
        os.environ.get("LLVM_OBJDUMP"),
        "/nfs/home/maoyirao/work/xsai-env/local/llvm/bin/llvm-objdump",
        shutil.which("llvm-objdump"),
        shutil.which("objdump"),
    )
    return next((candidate for candidate in candidates if candidate and pathlib.Path(candidate).exists()), None)


@dataclass(frozen=True)
class Symbol:
    start: int
    end: int
    name: str


@dataclass
class Instruction:
    sn: int
    pc: int
    fetch: int
    issue: int
    fu: int
    commit: int
    uops: int


class SymbolTable:
    def __init__(self, elf: pathlib.Path, readelf: str):
        result = subprocess.run(
            [readelf, "-sW", str(elf)], text=True, capture_output=True, check=True
        )
        raw: list[tuple[int, int, str]] = []
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) < 8 or fields[3] != "FUNC" or fields[6] == "UND":
                continue
            try:
                start = int(fields[1], 16)
                size = int(fields[2], 10)
            except ValueError:
                continue
            if start:
                raw.append((start, size, fields[7]))
        if not raw:
            raise SystemExit(f"no function symbols found in {elf}")
        raw.sort(key=lambda item: (item[0], -item[1], item[2]))
        deduplicated: list[tuple[int, int, str]] = []
        seen_starts = set()
        for item in raw:
            if item[0] not in seen_starts:
                deduplicated.append(item)
                seen_starts.add(item[0])
        symbols = []
        for index, (start, size, name) in enumerate(deduplicated):
            next_start = (
                deduplicated[index + 1][0]
                if index + 1 < len(deduplicated)
                else start + max(size, 1)
            )
            end = start + size if size else next_start
            symbols.append(Symbol(start, max(end, start + 1), name))
        self.symbols = symbols
        self.starts = [symbol.start for symbol in symbols]

    def lookup(self, pc: int) -> tuple[str, int]:
        index = bisect.bisect_right(self.starts, pc) - 1
        if index >= 0:
            symbol = self.symbols[index]
            if symbol.start <= pc < symbol.end:
                return symbol.name, pc - symbol.start
        return "[unknown]", 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze function and PC hotspots between xsai-blas ROI markers."
    )
    parser.add_argument("--db", type=pathlib.Path, required=True)
    parser.add_argument("--elf", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument(
        "--window",
        type=int,
        default=1,
        help="1-based dynamic BEGIN/END marker pair (default: 1)",
    )
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--readelf", default=shutil.which("readelf") or "readelf")
    parser.add_argument("--addr2line", default=shutil.which("addr2line"))
    parser.add_argument(
        "--objdump",
        default=default_objdump(),
        help="objdump used for instruction text and local disassembly context",
    )
    parser.add_argument(
        "--objdump-mattr",
        default=os.environ.get("OBJDUMP_MATTR", ""),
        help="comma-separated RISC-V features passed to llvm-objdump, e.g. +matrix-xuantie-0.6",
    )
    parser.add_argument(
        "--allow-elf-mismatch",
        action="store_true",
        help="continue even if sampled trace instruction encodings do not match the ELF (unsafe)",
    )
    args = parser.parse_args()
    if args.window <= 0 or args.top <= 0:
        parser.error("--window and --top must be positive")
    for name in ("db", "elf"):
        path = getattr(args, name)
        if not path.is_file():
            parser.error(f"--{name} does not exist: {path}")
    return args


def require_trace_schema(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='LifeTimeCommitTrace'"
    ).fetchone()
    if not row:
        raise SystemExit("database has no LifeTimeCommitTrace table")
    count = connection.execute("SELECT count(*) FROM LifeTimeCommitTrace").fetchone()[0]
    if not count:
        raise SystemExit(
            "LifeTimeCommitTrace is empty; collect with DB_SELECT=lifetime (or include lifetime in the selection)"
        )


def marker_rows(
    connection: sqlite3.Connection,
) -> tuple[list[tuple[int, int, int]], list[tuple[int, int, int]]]:
    rows = connection.execute(
        """
        SELECT SN, PC, DisAsm, MAX(AtCommit) AS commit_cycle
        FROM LifeTimeCommitTrace
        WHERE DisAsm IN (?, ?) AND AtCommit > 0
        GROUP BY SN, PC, DisAsm
        ORDER BY SN
        """,
        (BEGIN_INSN, END_INSN),
    ).fetchall()
    begins = [(int(row[0]), int(row[1]), int(row[3])) for row in rows if row[2] == BEGIN_INSN]
    ends = [(int(row[0]), int(row[1]), int(row[3])) for row in rows if row[2] == END_INSN]
    return begins, ends


def select_window(connection: sqlite3.Connection, number: int) -> dict[str, int]:
    begins, ends = marker_rows(connection)
    pairs = []
    end_index = 0
    for begin in begins:
        while end_index < len(ends) and ends[end_index][0] <= begin[0]:
            end_index += 1
        if end_index == len(ends):
            break
        end = ends[end_index]
        pairs.append((begin, end))
        end_index += 1
    if number > len(pairs):
        raise SystemExit(
            f"requested marker window {number}, but found {len(pairs)} complete BEGIN/END pair(s); "
            f"BEGIN={len(begins)} END={len(ends)}"
        )
    begin, end = pairs[number - 1]
    return {
        "window": number,
        "begin_sn": int(begin[0]),
        "begin_pc": int(begin[1]),
        "begin_commit_cycle": int(begin[2]),
        "end_sn": int(end[0]),
        "end_pc": int(end[1]),
        "end_commit_cycle": int(end[2]),
    }


def load_instructions(
    connection: sqlite3.Connection, begin_sn: int, end_sn: int
) -> list[Instruction]:
    rows = connection.execute(
        """
        SELECT SN, PC,
               MIN(CASE WHEN AtFetch > 0 THEN AtFetch END) AS fetch_cycle,
               MIN(CASE WHEN AtIssueQue > 0 THEN AtIssueQue END) AS issue_cycle,
               MIN(CASE WHEN AtFU > 0 THEN AtFU END) AS fu_cycle,
               MAX(AtCommit) AS commit_cycle,
               COUNT(*) AS uops
        FROM LifeTimeCommitTrace
        WHERE AtCommit > 0 AND SN > ? AND SN < ?
        GROUP BY SN, PC
        ORDER BY SN, PC
        """,
        (begin_sn, end_sn),
    ).fetchall()
    return [
        Instruction(
            sn=int(row[0]),
            pc=int(row[1]),
            fetch=int(row[2] or 0),
            issue=int(row[3] or 0),
            fu=int(row[4] or 0),
            commit=int(row[5]),
            uops=int(row[6]),
        )
        for row in rows
    ]


def update_stack(stack: list[str], function: str) -> list[str]:
    if not stack:
        return [function]
    if stack[-1] == function:
        return stack
    if function in stack:
        return stack[: stack.index(function) + 1]
    return [*stack, function]


def percentile(values: list[int], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower)


def source_locations(
    elf: pathlib.Path, addr2line: str | None, pcs: Iterable[int]
) -> dict[int, str]:
    unique = list(dict.fromkeys(pcs))
    if not addr2line or not unique:
        return {pc: "N/A" for pc in unique}
    result = subprocess.run(
        [addr2line, "-e", str(elf), "-f", "-C", *[hex(pc) for pc in unique]],
        text=True,
        capture_output=True,
        check=False,
    )
    lines = result.stdout.splitlines()
    locations = {}
    for index, pc in enumerate(unique):
        function = lines[index * 2] if index * 2 < len(lines) else "??"
        location = lines[index * 2 + 1] if index * 2 + 1 < len(lines) else "??:0"
        if location.endswith(":0") or location in ("??:?", "??:0"):
            locations[pc] = (
                f"{location} (DWARF line unavailable; rebuild the profile with "
                "PROFILE_DEBUG_INFO=yes and use the instruction context below)"
            )
        else:
            locations[pc] = f"{function} at {location}"
    return locations


def objdump_command(objdump: str, elf: pathlib.Path, mattr: str = "") -> list[str]:
    command = [objdump, "-d", "--demangle"]
    if mattr:
        command.append(f"--mattr={mattr}")
    return [*command, str(elf)]


_ABI_REGS = (
    "zero", "ra", "sp", "gp", "tp", "t0", "t1", "t2", "s0", "s1", "a0", "a1", "a2", "a3",
    "a4", "a5", "a6", "a7", "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9", "s10", "s11",
    "t3", "t4", "t5", "t6",
)


def decode_xsai_ame(encoding: int) -> str | None:
    """Decode XSAI's unified AME raw `.insn r 0x2b` format for reports."""
    if (encoding & 0x7F) != 0x2B:
        return None
    rd, funct3 = (encoding >> 7) & 31, (encoding >> 12) & 7
    rs1, rs2, funct7 = (encoding >> 15) & 31, (encoding >> 20) & 31, (encoding >> 25) & 0x7F
    gpr = lambda index: _ABI_REGS[index]
    matrix = lambda index: (f"tr{index}" if index < 4 else f"acc{index - 4}")
    if funct3 == 0:
        names = {33: "msetcfg", 17: "msettilem", 9: "msettilek", 25: "msettilen"}
        if funct7 == 33:
            return f"msetcfg mcfg{rd}, {gpr(rs1)}"
        if funct7 in names:
            return f"{names[funct7]} {gpr(rs1)}"
    elif funct3 == 1:
        names = {0: "mlae8", 8: "mlbe8", 16: "mlce32", 17: "msce32"}
        if funct7 in names:
            return f"{names[funct7]} {matrix(rd)}, ({gpr(rs1)}), stride={gpr(rs2)}"
    elif funct3 == 2 and funct7 == 0:
        return f"mqma {matrix(rd)}, {matrix(rs1)}, {matrix(rs2)}"
    elif funct3 == 3 and funct7 == 0:
        return f"mzero.acc {matrix(rd)}"
    elif funct3 == 4:
        names = {64: "msyncreset", 72: "mrelease"}
        if funct7 in names:
            return names[funct7]
        if funct7 == 80:
            return f"macquire {gpr(rs1)}"
    return f"ame.custom f3={funct3}, f7={funct7}, rd={gpr(rd)}, rs1={gpr(rs1)}, rs2={gpr(rs2)}"


def parse_objdump_encoding(field: str) -> int | None:
    byte_fields = field.split()
    if byte_fields and all(re.fullmatch(r"[0-9a-fA-F]{2}", item) for item in byte_fields):
        return int.from_bytes(bytes.fromhex("".join(byte_fields)), "little")
    if len(byte_fields) == 1 and re.fullmatch(r"[0-9a-fA-F]+", byte_fields[0]):
        return int(byte_fields[0], 16)
    return None


def elf_instruction_encodings(
    elf: pathlib.Path, objdump: str | None, objdump_mattr: str = ""
) -> dict[int, int]:
    """Return PC -> encoded instruction word for GNU or LLVM objdump output."""
    if not objdump:
        return {}
    result = subprocess.run(
        objdump_command(objdump, elf, objdump_mattr),
        text=True,
        capture_output=True,
        check=False,
    )
    encodings: dict[int, int] = {}
    for line in result.stdout.splitlines():
        match = re.match(r"^\s*([0-9a-fA-F]+):\s+(.*)$", line)
        if not match:
            continue
        fields = [field.strip() for field in match.group(2).split("\t") if field.strip()]
        if len(fields) < 2:
            continue
        encoding = parse_objdump_encoding(fields[0])
        if encoding is None:
            continue
        encodings[int(match.group(1), 16)] = encoding
    return encodings


def validate_elf_matches_trace(
    connection: sqlite3.Connection,
    begin_sn: int,
    end_sn: int,
    elf: pathlib.Path,
    objdump: str | None,
    objdump_mattr: str,
    allow_mismatch: bool,
) -> None:
    """Reject a report when its PC symbols would be resolved against another build."""
    encodings = elf_instruction_encodings(elf, objdump, objdump_mattr)
    if not encodings:
        print("warning: cannot validate trace/ELF instruction encodings; objdump unavailable", file=sys.stderr)
        return
    rows = connection.execute(
        """
        SELECT PC, MIN(DisAsm) AS encoding
        FROM LifeTimeCommitTrace
        WHERE AtCommit > 0 AND SN > ? AND SN < ?
        GROUP BY PC
        ORDER BY PC
        """,
        (begin_sn, end_sn),
    ).fetchall()
    by_pc = {int(pc): int(encoding) for pc, encoding in rows}
    pcs = list(by_pc)
    sample_count = min(256, len(pcs))
    sampled = [pcs[index * len(pcs) // sample_count] for index in range(sample_count)] if sample_count else []
    # LifeTimeCommitTrace records a decompressed 32-bit form for RVC
    # instructions, while objdump shows their 16-bit ELF encoding.  Compare
    # only native 32-bit instructions; wider encodings are also skipped.
    def is_native_32bit(encoding: int) -> bool:
        return (encoding & 0b11) == 0b11 and (encoding & 0b11100) != 0b11100

    mismatches = [
        (pc, by_pc[pc], encodings[pc])
        for pc in sampled
        if pc in encodings
        and is_native_32bit(encodings[pc])
        and by_pc[pc] != encodings[pc]
    ]
    if not mismatches:
        return
    pc, trace_encoding, elf_encoding = mismatches[0]
    message = (
        "trace and ELF do not match: at "
        f"PC 0x{pc:016x}, trace has 0x{trace_encoding:08x} but ELF has 0x{elf_encoding:08x}. "
        "Function/source names would be invalid. Use the ELF saved with this trace or rerun profile-emu."
    )
    if allow_mismatch:
        print(f"warning: {message}", file=sys.stderr)
    else:
        raise SystemExit(message)


def disassembly_context(
    elf: pathlib.Path, objdump: str | None, pcs: Iterable[int], radius: int = 2,
    objdump_mattr: str = ""
) -> dict[int, dict[str, str]]:
    requested = list(dict.fromkeys(pcs))
    unavailable = {pc: {"instruction": "N/A", "disassembly_context": "N/A"} for pc in requested}
    if not objdump or not requested:
        return unavailable
    result = subprocess.run(
        objdump_command(objdump, elf, objdump_mattr),
        text=True,
        capture_output=True,
        check=False,
    )
    decoded: dict[int, str] = {}
    for line in result.stdout.splitlines():
        match = re.match(r"^\s*([0-9a-fA-F]+):\s+(.*)$", line)
        if not match:
            continue
        address = int(match.group(1), 16)
        fields = [field.strip() for field in match.group(2).split("\t") if field.strip()]
        if len(fields) >= 2:
            instruction = " ".join(fields[1:])
            encoding = parse_objdump_encoding(fields[0])
            if instruction == "<unknown>" and encoding is not None:
                instruction = decode_xsai_ame(encoding) or f"<unknown 0x{encoding:08x}>"
            decoded[address] = instruction
    if not decoded:
        return unavailable
    addresses = sorted(decoded)
    result_by_pc = {}
    for pc in requested:
        if pc not in decoded:
            result_by_pc[pc] = unavailable[pc]
            continue
        index = bisect.bisect_left(addresses, pc)
        nearby = addresses[max(0, index - radius) : index + radius + 1]
        context = "\n".join(
            f"{'>>' if address == pc else '  '} 0x{address:016x}: {decoded[address]}"
            for address in nearby
        )
        result_by_pc[pc] = {
            "instruction": decoded[pc],
            "disassembly_context": context,
        }
    return result_by_pc


def analyze(
    instructions: list[Instruction],
    symbols: SymbolTable,
    window: dict[str, int],
    elf: pathlib.Path,
    addr2line: str | None,
    objdump: str | None,
    objdump_mattr: str,
) -> dict[str, Any]:
    if not instructions:
        raise SystemExit("the selected marker window contains no committed instructions")
    function_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "calls": 0,
            "instructions": 0,
            "uops": 0,
            "retirement_cycles": 0,
            "latencies": [],
        }
    )
    pc_stats: dict[int, dict[str, Any]] = defaultdict(
        lambda: {"instructions": 0, "uops": 0, "retirement_cycles": 0, "latencies": []}
    )
    collapsed: dict[tuple[str, ...], int] = defaultdict(int)
    stack: list[str] = []
    last_commit = window["begin_commit_cycle"]

    for instruction in instructions:
        function, _ = symbols.lookup(instruction.pc)
        is_entry = not stack or (stack[-1] != function and function not in stack)
        stack = update_stack(stack, function)
        if is_entry:
            function_stats[function]["calls"] += 1
        retirement_cycles = max(0, instruction.commit - last_commit)
        last_commit = max(last_commit, instruction.commit)
        latency = instruction.commit - instruction.fetch if instruction.fetch else None
        for stats in (function_stats[function], pc_stats[instruction.pc]):
            stats["instructions"] += 1
            stats["uops"] += instruction.uops
            stats["retirement_cycles"] += retirement_cycles
            if latency is not None:
                stats["latencies"].append(latency)
        if retirement_cycles:
            collapsed[tuple(stack)] += retirement_cycles

    roi_cycles = window["end_commit_cycle"] - window["begin_commit_cycle"]
    attributed_cycles = sum(item["retirement_cycles"] for item in function_stats.values())
    trailing_cycles = max(0, roi_cycles - attributed_cycles)
    if trailing_cycles:
        collapsed[("[ROI marker/loop overhead]",)] += trailing_cycles

    inclusive_cycles: dict[str, int] = defaultdict(int)
    for stack_key, cycles in collapsed.items():
        for function in dict.fromkeys(stack_key):
            inclusive_cycles[function] += cycles

    total_instructions = len(instructions)
    functions = []
    for function, stats in function_stats.items():
        latencies = stats.pop("latencies")
        functions.append(
            {
                "function": function,
                **stats,
                "instruction_percent": stats["instructions"] / total_instructions * 100.0,
                "retirement_cycle_percent": (
                    stats["retirement_cycles"] / roi_cycles * 100.0 if roi_cycles else 0.0
                ),
                "inclusive_retirement_cycles": inclusive_cycles[function],
                "inclusive_retirement_cycle_percent": (
                    inclusive_cycles[function] / roi_cycles * 100.0 if roi_cycles else 0.0
                ),
                "avg_fetch_to_commit_cycles": (
                    sum(latencies) / len(latencies) if latencies else None
                ),
                "p95_fetch_to_commit_cycles": percentile(latencies, 0.95),
            }
        )
    functions.sort(key=lambda item: item["retirement_cycles"], reverse=True)

    hottest_pcs = sorted(
        pc_stats.items(), key=lambda item: item[1]["retirement_cycles"], reverse=True
    )
    locations = source_locations(elf, addr2line, (pc for pc, _ in hottest_pcs))
    disassembly = disassembly_context(
        elf, objdump, (pc for pc, _ in hottest_pcs), objdump_mattr=objdump_mattr
    )
    pcs = []
    for pc, stats in hottest_pcs:
        function, offset = symbols.lookup(pc)
        latencies = stats.pop("latencies")
        pcs.append(
            {
                "pc": f"0x{pc:016x}",
                "function": function,
                "function_offset": offset,
                "source": locations.get(pc, "N/A"),
                **disassembly.get(pc, {}),
                **stats,
                "retirement_cycle_percent": (
                    stats["retirement_cycles"] / roi_cycles * 100.0 if roi_cycles else 0.0
                ),
                "avg_fetch_to_commit_cycles": (
                    sum(latencies) / len(latencies) if latencies else None
                ),
                "p95_fetch_to_commit_cycles": percentile(latencies, 0.95),
            }
        )
    return {
        "schema_version": 1,
        "metric_semantics": {
            "retirement_cycles": (
                "cycles since the preceding committed instruction, attributed to the instruction "
                "that retires next; additive but not exclusive execution time"
            ),
            "fetch_to_commit_cycles": (
                "per-instruction pipeline residence; overlapping instructions must not be summed as time"
            ),
            "call_stack": (
                "reconstructed from dynamic transitions between ELF function symbols; indirect calls, "
                "tail calls, recursion, inlining, and missing symbols can reduce stack fidelity"
            ),
        },
        "window": {
            **window,
            "roi_cycles": roi_cycles,
            "committed_instructions": total_instructions,
            "attributed_cycles": attributed_cycles,
            "trailing_marker_cycles": trailing_cycles,
        },
        "functions": functions,
        "pcs": pcs,
        "collapsed_stacks": [
            {"stack": list(stack_key), "retirement_cycles": cycles}
            for stack_key, cycles in sorted(collapsed.items(), key=lambda item: item[1], reverse=True)
        ],
    }


def write_csv(path: pathlib.Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def flame_color(name: str) -> str:
    value = sum((index + 1) * ord(char) for index, char in enumerate(name))
    return f"hsl({value % 45 + 8} 78% {55 + value % 12}%)"


def write_flamegraph(path: pathlib.Path, collapsed: list[dict[str, Any]]) -> None:
    tree: dict[str, Any] = {"value": 0, "children": {}}
    for row in collapsed:
        value = int(row["retirement_cycles"])
        tree["value"] += value
        node = tree
        for frame in row["stack"]:
            child = node["children"].setdefault(frame, {"value": 0, "children": {}})
            child["value"] += value
            node = child
    width = 1200
    frame_height = 24
    max_depth = max((len(row["stack"]) for row in collapsed), default=1)
    height = 70 + frame_height * max_depth
    total = max(1, tree["value"])
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<style>text{font-family:monospace;font-size:12px;fill:#1f2937}.title{font-family:sans-serif;font-size:18px;fill:#111827}</style>',
        '<rect width="100%" height="100%" fill="#fff"/>',
        '<text class="title" x="12" y="24">ROI retirement-attributed flame graph</text>',
        '<text x="12" y="43">Width is retirement-attributed cycles, not exclusive execution time.</text>',
    ]

    def draw(node: dict[str, Any], x: float, depth: int, span: float) -> None:
        cursor = x
        children = sorted(node["children"].items(), key=lambda item: item[1]["value"], reverse=True)
        for name, child in children:
            child_span = span * child["value"] / max(1, node["value"])
            y = 55 + (max_depth - depth - 1) * frame_height
            safe_name = html.escape(name)
            percent = child["value"] / total * 100.0
            svg.append(
                f'<g><title>{safe_name}: {child["value"]} cycles ({percent:.2f}%)</title>'
                f'<rect x="{cursor:.2f}" y="{y}" width="{max(0.2, child_span - 0.5):.2f}" height="22" fill="{flame_color(name)}" stroke="#fff"/>'
                f'<text x="{cursor + 3:.2f}" y="{y + 15}">{safe_name if child_span > 45 else ""}</text></g>'
            )
            draw(child, cursor, depth + 1, child_span)
            cursor += child_span

    draw(tree, 0.0, 0, float(width))
    svg.append("</svg>")
    path.write_text("\n".join(svg) + "\n", encoding="utf-8")


def display_number(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def write_html(path: pathlib.Path, report: dict[str, Any], top: int) -> None:
    window = report["window"]
    function_rows = []
    for row in report["functions"][:top]:
        function_rows.append(
            "<tr>"
            f'<td>{html.escape(row["function"])}</td>'
            f'<td>{row["calls"]}</td><td>{row["instructions"]}</td><td>{row["instruction_percent"]:.2f}%</td>'
            f'<td>{row["retirement_cycles"]}</td><td>{row["retirement_cycle_percent"]:.2f}%</td>'
            f'<td>{row["inclusive_retirement_cycles"]}</td><td>{row["inclusive_retirement_cycle_percent"]:.2f}%</td>'
            f'<td>{display_number(row["avg_fetch_to_commit_cycles"])}</td>'
            f'<td>{display_number(row["p95_fetch_to_commit_cycles"])}</td></tr>'
        )
    pc_rows = []
    for row in report["pcs"][:top]:
        pc_rows.append(
            "<tr>"
            f'<td><code>{row["pc"]}</code></td><td>{html.escape(row["function"])}+0x{row["function_offset"]:x}</td>'
            f'<td>{html.escape(row["source"])}</td><td><code>{html.escape(row["instruction"])}</code>'
            f'<details><summary>context</summary><pre>{html.escape(row["disassembly_context"])}</pre></details></td><td>{row["instructions"]}</td>'
            f'<td>{row["retirement_cycles"]}</td><td>{row["retirement_cycle_percent"]:.2f}%</td>'
            f'<td>{display_number(row["p95_fetch_to_commit_cycles"])}</td></tr>'
        )
    document = f"""<!doctype html><html><head><meta charset="utf-8"><title>xsai-blas ROI hotspots</title>
<style>body{{font:14px system-ui,sans-serif;max-width:1280px;margin:28px auto;padding:0 20px;color:#172033}}table{{border-collapse:collapse;width:100%;margin:12px 0 28px}}th,td{{border-bottom:1px solid #dfe5ed;padding:8px;text-align:left}}th{{background:#eef3f8}}.note{{background:#fff7ed;border-left:4px solid #f59e0b;padding:12px}}img{{width:100%;border:1px solid #d7dee8}}code{{font-size:12px}}</style></head><body>
<h1>xsai-blas ROI code hotspots</h1><p>Dynamic SN range: {window['begin_sn']} &lt; SN &lt; {window['end_sn']}; {window['committed_instructions']} committed instructions; {window['roi_cycles']} marker-to-marker retirement cycles.</p>
<div class="note"><b>Interpretation:</b> flame width and “retirement cycles” attribute each gap between commits to the instruction/function that retires next. This exposes retirement blockers and adds to 100%, but it is not exclusive function execution time on an out-of-order core. Per-instruction fetch-to-commit latency overlaps and is shown separately. Call stacks are reconstructed from dynamic ELF-symbol transitions, so tail/indirect calls, recursion, inlining, and missing symbols can reduce stack fidelity.</div>
<h2>Top PCs / source lines</h2><table><tr><th>PC</th><th>Function</th><th>Source</th><th>Instruction / nearby block</th><th>Instructions</th><th>Retirement cycles</th><th>Cycle share</th><th>P95 latency</th></tr>{''.join(pc_rows)}</table>
<h2>Top functions</h2><table><tr><th>Function</th><th>Calls</th><th>Instructions</th><th>Instruction share</th><th>Self retirement cycles</th><th>Self share</th><th>Inclusive cycles</th><th>Inclusive share</th><th>Avg fetch→commit</th><th>P95 fetch→commit</th></tr>{''.join(function_rows)}</table>
<details><summary>Experimental call-path flame graph</summary><p>Useful only when symbol-transition stack reconstruction is sufficiently accurate.</p><img src="flamegraph.svg" alt="retirement-attributed flame graph"></details>
<p>Raw outputs: <a href="hotspots.json">JSON</a>, <a href="functions.csv">functions CSV</a>, <a href="pcs.csv">PC CSV</a>, <a href="collapsed.txt">collapsed stacks</a>.</p></body></html>"""
    path.write_text(document, encoding="utf-8")


def write_outputs(output: pathlib.Path, report: dict[str, Any], top: int) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "hotspots.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    write_csv(
        output / "functions.csv",
        report["functions"],
        [
            "function",
            "calls",
            "instructions",
            "instruction_percent",
            "uops",
            "retirement_cycles",
            "retirement_cycle_percent",
            "inclusive_retirement_cycles",
            "inclusive_retirement_cycle_percent",
            "avg_fetch_to_commit_cycles",
            "p95_fetch_to_commit_cycles",
        ],
    )
    write_csv(
        output / "pcs.csv",
        report["pcs"],
        [
            "pc",
            "function",
            "function_offset",
            "source",
            "instruction",
            "disassembly_context",
            "instructions",
            "uops",
            "retirement_cycles",
            "retirement_cycle_percent",
            "avg_fetch_to_commit_cycles",
            "p95_fetch_to_commit_cycles",
        ],
    )
    with (output / "collapsed.txt").open("w", encoding="utf-8") as stream:
        for row in report["collapsed_stacks"]:
            stream.write(";".join(row["stack"]) + f' {row["retirement_cycles"]}\n')
    with (output / "hotspots.txt").open("w", encoding="utf-8") as stream:
        window = report["window"]
        stream.write(
            f"ROI window {window['window']}: SN {window['begin_sn']}..{window['end_sn']}, "
            f"{window['roi_cycles']} cycles, {window['committed_instructions']} committed instructions\n\n"
        )
        stream.write(
            f"{'FUNCTION':40} {'CALLS':>8} {'INSTR':>12} {'SELF CYC':>12} {'SELF%':>8} {'INCL%':>8} {'P95 LAT':>10}\n"
        )
        for row in report["functions"][:top]:
            stream.write(
                f"{row['function'][:40]:40} {row['calls']:8d} {row['instructions']:12d} "
                f"{row['retirement_cycles']:12d} {row['retirement_cycle_percent']:7.2f}% "
                f"{row['inclusive_retirement_cycle_percent']:7.2f}% "
                f"{display_number(row['p95_fetch_to_commit_cycles']):>10}\n"
            )
        stream.write("\nTop PCs\n")
        for row in report["pcs"][:top]:
            stream.write(
                f"{row['pc']} {row['retirement_cycles']:10d} cycles "
                f"({row['retirement_cycle_percent']:6.2f}%) "
                f"{row['function']}+0x{row['function_offset']:x} {row['instruction']} {row['source']}\n"
            )
    write_flamegraph(output / "flamegraph.svg", report["collapsed_stacks"])
    write_html(output / "index.html", report, top)


def main() -> None:
    args = parse_args()
    with sqlite3.connect(f"file:{args.db.resolve()}?mode=ro", uri=True) as connection:
        require_trace_schema(connection)
        window = select_window(connection, args.window)
        validate_elf_matches_trace(
            connection,
            window["begin_sn"],
            window["end_sn"],
            args.elf.resolve(),
            args.objdump,
            args.objdump_mattr,
            args.allow_elf_mismatch,
        )
        instructions = load_instructions(connection, window["begin_sn"], window["end_sn"])
    symbols = SymbolTable(args.elf.resolve(), args.readelf)
    report = analyze(
        instructions,
        symbols,
        window,
        args.elf.resolve(),
        args.addr2line,
        args.objdump,
        args.objdump_mattr,
    )
    write_outputs(args.output.resolve(), report, args.top)
    print(f"ROI hotspot report: {(args.output.resolve() / 'index.html')}")


if __name__ == "__main__":
    try:
        main()
    except sqlite3.Error as exc:
        raise SystemExit(f"SQLite error: {exc}") from exc
