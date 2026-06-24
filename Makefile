AGE_KEY ?= $(HOME)/.config/sops/age/keys.txt
export SOPS_AGE_KEY_FILE = $(AGE_KEY)
PY = .venv/bin/python

.PHONY: secrets check edit-vault rotate-key clean-env test sync-shared lint format help

# Vendored copies of shared/notify.py — each stack builds its own image with
# build context = its own dir, so the file must physically live inside each.
# Single source: shared/notify.py. Guarded by tests/test_shared_sync.py.
NOTIFY_COPIES = news-feed/app/notify.py game-codes/notify.py \
                watchtower/notifier/notify.py torrentwatch/notify.py
HTTP_COPIES = news-feed/app/http_client.py game-codes/http_client.py \
              maid-tracker/http_client.py
BACKUP_COPIES = maid-tracker/sqlite_backup.py news-feed/app/sqlite_backup.py \
                torrentwatch/sqlite_backup.py

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

sync-shared:    ## Copy shared/{notify,http_client,sqlite_backup}.py into each stack (vendored, committed)
	@for dst in $(NOTIFY_COPIES); do cp shared/notify.py $$dst && echo "synced $$dst"; done
	@for dst in $(HTTP_COPIES); do cp shared/http_client.py $$dst && echo "synced $$dst"; done
	@for dst in $(BACKUP_COPIES); do cp shared/sqlite_backup.py $$dst && echo "synced $$dst"; done

test:           ## Run repo-level pytest suite
	@$(PY) -m pytest tests/ -v

lint:           ## Run ruff linter (no auto-fix)
	@$(PY) -m ruff check

format:         ## Auto-format + safe-fix with ruff
	@$(PY) -m ruff format
	@$(PY) -m ruff check --fix
