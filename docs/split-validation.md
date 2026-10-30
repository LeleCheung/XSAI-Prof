# Independent repository acceptance

XSAI-Prof 0.8.1b1 passes 132 portable software tests, clean Git-clone tests, exact wheel installation (7 checks), beta installation (6), standard sdist/wheel installation (12), and real report/RTL workflow acceptance (7). Real Chromium accepts FA, GEMM and the new live report (7 checks each).

The profiler core is byte-identical to the validated 0.8 code except its version identifier. Standalone documentation, packaging metadata and test ownership changed. The KDA-side 23 existing tests plus 3 dependency/compatibility tests pass separately. The previous full source is preserved in XSAI-KDA's pre-split commit.

A new AME copy case (rows=1, cols=16) passed correctness before perf and trace: four emulator invocations total. Measured read returns are 64 B, request service time 7 cycles, peak outstanding requests 1. One perf sample verifies the tool workflow; this is not a new kernel speedup claim. FA/GEMM historical analysis retains original independent performance identity and observer mismatch warnings. CLI export/import and resume are verified.

See [machine-readable evidence](split-validation.json) for source, wheel, test, original artifact and live manifest hashes. Python 3.12 and Chromium 156 ran locally; hosted CI/Python 3.10 are not implied by this receipt. RTL/toolchain/runtime dependencies and raw captures remain external.
