AGE_KEY ?= $(HOME)/.config/sops/age/keys.txt
export SOPS_AGE_KEY_FILE = $(AGE_KEY)
PY = .venv/bin/python

.PHONY: secrets check edit-vault rotate-key clean-env test help

help:           ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-14s %s\n", $$1, $$2}'

secrets:        ## Render <stack>/.env + .env.deploy from vault + manifests
	@$(PY) scripts/render_env.py $(ARGS)

check:          ## Validate manifests + vault consistency without writing
	@$(PY) scripts/render_env.py --check

edit-vault:     ## Open vault in $$EDITOR (sops decrypts on read, re-encrypts on save)
	@sops secrets/vault.sops.yaml

rotate-key:     ## Re-encrypt vault for current .sops.yaml recipients
	@sops updatekeys secrets/vault.sops.yaml

clean-env:      ## Remove all generated .env files (does not touch vault)
	@find . -name '.env' -not -path './.git/*' -not -path './.venv/*' -not -path './backup-pre-vault/*' -delete
	@rm -f .env.deploy

test:           ## Run repo-level pytest suite
	@$(PY) -m pytest tests/ -v
