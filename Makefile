.DEFAULT_GOAL := help
.PHONY: help setup run simulate doctor check test lint wheel deb clean install-dev

PYTHON ?= python3

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup:  ## Install system dependencies (needs sudo) and the package in editable mode
	sudo apt update
	sudo apt install -y python3-gi gir1.2-gtk-3.0 python3-psutil \
		flatpak gsettings-desktop-schemas polkitd tar xz-utils
	$(PYTHON) -m pip install -e .

install-dev:  ## Install dev-only Python tooling
	$(PYTHON) -m pip install -e '.[dev]'

run:  ## Launch the GUI from this checkout
	$(PYTHON) -m preen_tool.app

simulate:  ## Launch the GUI with dry-run mode enabled
	$(PYTHON) -m preen_tool.app --simulate

doctor:  ## Check installation, dependencies and catalogue (no GTK needed)
	$(PYTHON) -m preen_tool.app --doctor

check:  ## Validate the app catalogue and presets
	$(PYTHON) -m preen_tool.app --check-catalog

test:  ## Run the full regression suite (no root/GTK/network needed)
	$(PYTHON) -m unittest discover -s tests -v

lint:  ## Syntax-check every Python file
	$(PYTHON) -m compileall -q preen_tool tests

wheel: check test  ## Build a wheel after validating the catalogue and tests
	$(PYTHON) -m pip wheel . --no-deps -w dist

deb: check test  ## Build the Debian package
	DEB_BUILD_OPTIONS=nocheck dpkg-buildpackage -us -uc --no-sign

clean:  ## Remove generated build artefacts
	rm -rf build dist .pybuild .pytest_cache *.egg-info preen.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
