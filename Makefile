AGE_KEY ?= $(HOME)/.config/sops/age/keys.txt
export SOPS_AGE_KEY_FILE = $(AGE_KEY)
PY = .venv/bin/python

.PHONY: secrets check edit-vault sync-test-vault rotate-key clean-env test sync-shared lint format help

help:           ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-14s %s\n", $$1, $$2}'

secrets:        ## Render <stack>/.env + .env.deploy from vault + manifests
	@$(PY) scripts/render_env.py $(ARGS)

check:          ## Validate manifests + vault + test-vault consistency without writing
	@$(PY) scripts/render_env.py --check
	@$(PY) scripts/render_env.py --check --vault secrets/test-vault.sops.yaml --exclude scripts

edit-vault:     ## Open vault in $$EDITOR (sops decrypts on read, re-encrypts on save)
	@sops secrets/vault.sops.yaml

sync-test-vault: ## Regenerate test-vault from real vault structure (dummy values). Run after adding/removing a vault key.
	@$(PY) scripts/sync_test_vault.py

rotate-key:     ## Re-encrypt vault for current .sops.yaml recipients
	@sops updatekeys secrets/vault.sops.yaml

clean-env:      ## Remove all generated .env files (does not touch vault)
	@find . -name '.env' -not -path './.git/*' -not -path './.venv/*' -not -path './backup-pre-vault/*' -delete
	@rm -f .env.deploy

sync-shared:    ## Copy each shared/*.py over its existing vendored copies (discovered by filename among tracked files, see tests/test_shared_sync.py)
	@for src in shared/*.py; do \
		name=$$(basename $$src); \
		[ "$${name#test_}" = "$$name" ] || continue; \
		for dst in $$(git ls-files -- '*/'"$$name" | grep -v '^shared/'); do \
			cp $$src $$dst && echo "synced $$dst"; \
		done; \
	done

test:           ## Run repo-level pytest suite
	@$(PY) -m pytest tests/ -v

lint:           ## Run ruff linter (no auto-fix)
	@$(PY) -m ruff check

format:         ## Auto-format + safe-fix with ruff
	@$(PY) -m ruff format
	@$(PY) -m ruff check --fix
