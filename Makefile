.PHONY: test lint dev init plan apply

TF := terraform -chdir=terraform
SECRETS := $(HOME)/.config/infra/secrets.env

init:
	$(TF) init -input=false

test:
	@$(TF) init -input=false -backend=false >/dev/null
	$(TF) test

lint:
	$(TF) fmt -check -recursive
	@$(TF) init -input=false -backend=false >/dev/null
	$(TF) validate

plan:
	. $(SECRETS) && $(TF) plan -input=false -out=tfplan

apply:
	. $(SECRETS) && $(TF) apply -input=false tfplan

dev:
	@echo "Not implemented yet: see the roadmap in README.md"
