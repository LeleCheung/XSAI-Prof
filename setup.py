"""Bundle the pinned upstream analyzer without maintaining a second code copy."""
from pathlib import Path
from setuptools import setup
from setuptools.command.build_py import build_py

class BuildProfiler(build_py):
    def find_package_modules(self, package, package_dir):
        excluded = {'bootstrap', 'kda_model', 'verify_profile_examples'}
        return [v for v in super().find_package_modules(package, package_dir) if v[1] not in excluded]

    def run(self):
        super().run()
        target = Path(self.build_lib) / 'xsai_prof/vendor'
        target.mkdir(parents=True, exist_ok=True)
        for name in ('roi_hotspots.py', 'LICENSE'):
            self.copy_file(str(Path('vendor/xsai-blas-profiling') / name), str(target / name))
        for source, name in [('LICENSE', 'RTL-SOURCE-LICENSE'), ('NOTICE', 'RTL-SOURCE-NOTICE')]:
            self.copy_file(str(Path('vendor/xsai-rtl-reference') / source), str(target / name))
        docs = Path(self.build_lib) / 'xsai_prof/resources/docs'
        docs.mkdir(parents=True, exist_ok=True)
        for name in ('profiler-quickstart.md', 'profiler-supported-targets.md', 'profiler-ame-read.md', 'profiler-case-studies.md', 'profiler-cli-workflow.md'):
            self.copy_file(str(Path('docs') / name), str(docs / name))

setup(cmdclass={'build_py': BuildProfiler})
