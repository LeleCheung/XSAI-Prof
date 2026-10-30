import copy
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("xsai_kda", ROOT / "scripts/xsai_kda.py")
kda = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kda)


class EvidenceTests(unittest.TestCase):
    def test_ame_requires_matrix_nemu_config(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            for content in (None, "# CONFIG_RVMATRIX is not set\n",
                            "CONFIG_RVMATRIX=y_disabled\n"):
                if content is not None:
                    (home / ".config").write_text(content)
                with self.subTest(content=content), self.assertRaisesRegex(RuntimeError, "CONFIG_RVMATRIX=y"):
                    kda.validate_nemu_configuration(home, "ame")
                kda.validate_nemu_configuration(home, "rvv")
            (home / ".config").write_text("CONFIG_RVMATRIX=y\nCONFIG_RVMATRIX_TRLEN=512\n")
            kda.validate_nemu_configuration(home, "ame")

    def baseline(self):
        return {"performance_eligible": True, "target": "rtl", "instrumentation": "none",
                "correctness": {"passed": 1, "failed": 0, "reported_skipped": 115},
                "selection": {"kernel": "softmax", "case": 0},
                "rtl": {"emu_sha256": "same", "config_sha256": "same"},
                "arch": "riscv64-xs", "toolchain": "LLVM", "build_environment": {},
                "measurements": [{"op": "softmax(n=128)", "unit": "RVV-FP32", "cycles_per_run": 100}]}

    def test_rank_cycles_and_reject_wrong_evidence(self):
        base = self.baseline()
        candidate = copy.deepcopy(base)
        candidate["measurements"][0]["cycles_per_run"] = 80
        self.assertEqual(kda.compare_runs(base, candidate)[0]["speedup"], 1.25)
        for key, value in [("target", "qemu"), ("instrumentation", "trace"),
                           ("rtl", {"config_sha256": "different"}),
                           ("correctness", {"passed": 0, "failed": 0}),
                           ("selection", {"kernel": "softmax", "case": 1})]:
            bad = copy.deepcopy(candidate)
            bad[key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                kda.compare_runs(base, bad)

    def test_correctness_selection_skips_and_empty_results(self):
        self.assertEqual(kda.check_correctness("--- 6 passed, 0 failed, 110 skipped ---")["passed"], 6)
        for text in ["--- 0 passed, 0 failed, 116 skipped ---", "--- 1 passed, 1 failed, 0 skipped ---", "GOOD TRAP"]:
            with self.subTest(text=text), self.assertRaises(RuntimeError):
                kda.check_correctness(text)

    def test_rank_rejects_changed_harness(self):
        baseline = self.baseline()
        baseline['test_harness'] = {'test/cases_gemm_tile.c': 'one-call'}
        candidate = copy.deepcopy(baseline)
        candidate['test_harness']['test/cases_gemm_tile.c'] = 'two-calls'
        with self.assertRaisesRegex(RuntimeError, 'test_harness differs'):
            kda.compare_runs(baseline, candidate)
        del candidate['test_harness']
        with self.assertRaisesRegex(RuntimeError, 'test_harness differs'):
            kda.compare_runs(baseline, candidate)

    def test_perf_parser_shape_spaces_and_hpm(self):
        text = "  softmax (n=128) RVV-FP32 100 200 2.00 1.2 2.3 0.25 1.28 50.0%\n[xsai-blas-hpm] counter=3 total=10"
        rows = kda.performance_rows(text)
        self.assertEqual(rows[0]["op"], "softmax (n=128)")
        self.assertEqual(rows[0]["cycles_per_run"], 100)
        with self.assertRaises(RuntimeError):
            kda.performance_rows("softmax RVV-FP32 0 200 0 0 0 0 0 0%")
        with self.assertRaises(RuntimeError):
            kda.performance_rows("softmax RVV-FP32 nan 200 0 0 0 0 0 0%")

    def test_artifact_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            elf = root / "image.elf"
            elf.write_bytes(b"original")
            kda.write_json(root / "manifest.json", {"status": "passed", "artifacts": {elf.name: {"sha256": kda.digest(elf)}}})
            self.assertEqual(kda.load_run(root)["status"], "passed")
            elf.write_bytes(b"changed")
            with self.assertRaises(RuntimeError):
                kda.load_run(root)

    def test_hpm_stale_labels_and_combined_selectors(self):
        coding = [{"group": "backend", "id": 0, "name": "noEvent"},
                  {"group": "backend", "id": 67, "name": "EXEC_STALL_CYCLE    "},
                  {"group": "backend", "id": 76, "name": "IssueQueueAluCsrFenceDivMcfg_full"}]
        raw = ("[xsai-blas-hpm] counter=11 event=EXEC_STALL_CYCLE config=0x43 total=80 per_run=10.00\n"
               "[xsai-blas-hpm] counter=16 event=ISSUE_GE_4_UOPS config=0x4c total=16 per_run=2.00")
        rows = kda.hpm_measurements(raw, coding)
        self.assertTrue(rows[0]["upstream_label_matches_rtl"])
        self.assertEqual(rows[0]["rtl_event_names"][0], "EXEC_STALL_CYCLE")
        self.assertFalse(rows[1]["upstream_label_matches_rtl"])
        self.assertEqual(rows[1]["rtl_event_names"][0], "IssueQueueAluCsrFenceDivMcfg_full")
        self.assertFalse(kda.hpm_measurements(raw)[0]["encoding_resolved"])
        selector = 14 | (31 << 10) | (48 << 20) | (65 << 30) | (4 << 40) | (4 << 45) | (4 << 50)
        coding = [{"group": "L2 Cache", "id": i, "name": f"bank{n}_access"}
                  for n, i in enumerate([14, 31, 48, 65])]
        combined = kda.hpm_measurements(
            f"[xsai-blas-hpm] counter=27 event=l2_access config=0x{selector:x} total=32 per_run=4.00", coding)[0]
        self.assertTrue(combined["encoding_resolved"])
        self.assertEqual(combined["operators"], ["add"] * 3)
        self.assertEqual(combined["rtl_event_names"], [f"bank{n}_access" for n in range(4)])
        self.assertIsNone(combined["upstream_label_matches_rtl"])

    def test_rtl_receipt_rejects_changed_emulator_or_memory_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            emu, memory, config = root / "emu", root / "dram.ini", root / "config.json"
            emu.write_bytes(b"built emulator")
            memory.write_text("tCK=0.63\n")
            kda.write_json(config, {"emulator": {"sha256": kda.digest(emu)},
                                   "runtime_inputs": [{"path": str(memory), "sha256": kda.digest(memory)}]})
            self.assertEqual(len(kda.validate_rtl_inputs(config, emu)["runtime_inputs"]), 1)
            memory.write_text("tCK=1.00\n")
            with self.assertRaisesRegex(RuntimeError, "runtime input changed"):
                kda.validate_rtl_inputs(config, emu)
            memory.write_text("tCK=0.63\n")
            emu.write_bytes(b"other emulator")
            with self.assertRaisesRegex(RuntimeError, "does not match"):
                kda.validate_rtl_inputs(config, emu)


@unittest.skipUnless(shutil.which("riscv64-linux-gnu-gcc"), "Requires RISC-V cross compiler")
class ProfilerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.elf = self.root / "fixture.elf"
        subprocess.run(["riscv64-linux-gnu-gcc", "-nostdlib", "-static", "-march=rv64gc", "-g",
                        "-Wl,-Ttext=0x80000000", "-Wl,--build-id=none", ROOT / "tests/roi_fixture.S",
                        "-o", self.elf], check=True, capture_output=True)
        self.db = self.root / "fixture.db"
        with sqlite3.connect(self.db) as connection:
            connection.execute("CREATE TABLE LifeTimeCommitTrace (SN INTEGER, PC INTEGER, DisAsm INTEGER, AtFetch INTEGER, AtIssueQue INTEGER, AtFU INTEGER, AtCommit INTEGER)")
            for sn, encoding, cycle in [(1, 0x5a100013, 101), (2, 0x00150513, 104), (3, 0x00250513, 108), (4, 0x5a200013, 113)]:
                connection.execute("INSERT INTO LifeTimeCommitTrace VALUES (?, ?, ?, ?, ?, ?, ?)",
                                   (sn, 0x80000000 + 4 * (sn - 1), encoding, cycle - 4, cycle - 3, cycle - 1, cycle))

    def tearDown(self):
        self.directory.cleanup()

    def invoke(self, runs):
        return subprocess.run([sys.executable, ROOT / "scripts/xsai_kda.py", "--runs", self.root / runs,
                               "analyze", "--db", self.db, "--elf", self.elf], text=True, capture_output=True)

    def test_roi_accounting_and_outputs(self):
        result = self.invoke("success")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        run = next((self.root / "success").iterdir())
        data = json.loads((run / "roi/hotspots.json").read_text())
        self.assertEqual(data["window"]["roi_cycles"], 12)
        self.assertEqual(data["window"]["committed_instructions"], 2)
        self.assertEqual(data["window"]["attributed_cycles"] + data["window"]["trailing_marker_cycles"], 12)
        self.assertTrue((run / "roi/index.html").is_file())
        self.assertEqual(kda.load_run(run)["status"], "passed")

    def test_mismatched_elf_rejected(self):
        with sqlite3.connect(self.db) as connection:
            connection.execute("UPDATE LifeTimeCommitTrace SET DisAsm=0x00350513 WHERE SN=2")
        result = self.invoke("mismatch")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("trace and ELF do not match", result.stderr)
        run = next((self.root / "mismatch").iterdir())
        self.assertEqual(json.loads((run / "manifest.json").read_text())["status"], "failed")

    def test_missing_markers_rejected(self):
        with sqlite3.connect(self.db) as connection:
            connection.execute("DELETE FROM LifeTimeCommitTrace WHERE SN=4")
        result = self.invoke("no-markers")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("complete BEGIN/END pair", result.stderr)


if __name__ == "__main__":
    unittest.main()
