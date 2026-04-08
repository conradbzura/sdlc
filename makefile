.PHONY: help install uninstall validate-target

skills_source = $(realpath $(CURDIR)/agents/skills)
guides_source = $(realpath $(CURDIR)/agents)

# Whitelist of valid skill directories
SKILLS = commit implement issue pr review test understand-chat

--validate-target:
	@if [ -z "$(target)" ]; then \
		echo "✗ Error: target parameter is required"; \
		echo "Usage: make install target=<path> or make uninstall target=<path>"; \
		exit 1; \
	fi

help:
	@echo "SDLC Pipeline Makefile"
	@echo ""
	@echo "Targets:"
	@echo "  make install target=<path>          Install to custom path"
	@echo "  make uninstall target=<path>        Remove from custom path"

install: --validate-target
	@bash scripts/install.sh "$(target)" "$(skills_source)" "$(guides_source)" $(SKILLS)

uninstall: --validate-target
	@bash scripts/uninstall.sh "$(target)" "$(skills_source)" "$(guides_source)" $(SKILLS)
