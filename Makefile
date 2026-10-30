.PHONY: help test build
help:
	python3 scripts/cli.py --help
test:
	python3 -m unittest discover -s tests -v
build:
	python3 tools/build_release.py --output release
