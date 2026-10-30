# Provenance

XSAI-Prof was extracted from [XSAI-KDA](https://github.com/LeleCheung/XSAI-KDA). The exact source commit, pre-split hashes and original package identity are recorded in [repository-split.json](https://github.com/LeleCheung/XSAI-KDA/blob/main/docs/repository-split.json). The extraction includes the required build/simulation adapter; legacy internal `kda_` module names remain for compatibility.

The pinned ROI analyzer is from OurCompArchGroup/xsai-blas commit `d5a2f9135aab63e38f0ba4d434fe47cdeab8801a`. Its algorithm and license are preserved in `vendor/xsai-blas-profiling/`. RTL source excerpts carry the Mulan PSL v2 license and source-specific notices in `vendor/xsai-rtl-reference/` and the recorded hardware contracts. The split does not change upstream licenses.

No CUDA optimizer, model transport, API credentials, skill, private BLAS source tree, emulator binary or raw historical capture is part of this tool repository. Simulator/runtime/toolchain paths are supplied explicitly for collection. Historical reports referenced by the documentation remain in XSAI-KDA; links do not imply their raw artifacts are shipped in Git.
