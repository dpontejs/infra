.PHONY: test lint dev init plan apply ansible-deps inventory bootstrap configure check stacks-test smoke test-integration

TF := terraform -chdir=terraform
SECRETS := $(HOME)/.config/infra/secrets.env
CADDY_IMAGE := caddy:2.11.7
DOMAIN := diegoponte.dev
# Ansible needs a valid UTF-8 locale; C.UTF-8 exists everywhere.
ANSIBLE := cd ansible && LC_ALL=C.UTF-8 ANSIBLE_CONFIG=ansible.cfg

init:
	$(TF) init -input=false

test: ansible-deps
	@$(TF) init -input=false -backend=false >/dev/null
	$(TF) test
	$(ANSIBLE) ansible-playbook -i localhost, --syntax-check playbook.yml
	@$(MAKE) -s stacks-test
	python3 -m unittest discover -s agent
	python3 -m unittest discover -s tests

lint: ansible-deps
	$(TF) fmt -check -recursive
	@$(TF) init -input=false -backend=false >/dev/null
	$(TF) validate
	$(ANSIBLE) ansible-lint --profile production
	@docker run --rm -v "$(CURDIR)/stacks/caddy/conf:/etc/caddy:ro" $(CADDY_IMAGE) caddy fmt --diff /etc/caddy/Caddyfile >/dev/null \
		|| (echo "Caddyfile is not formatted: run caddy fmt --overwrite"; exit 1)

plan:
	. $(SECRETS) && $(TF) plan -input=false -out=tfplan

apply:
	. $(SECRETS) && $(TF) apply -input=false tfplan

ansible-deps:
	@$(ANSIBLE) ansible-galaxy collection install -r requirements.yml -p collections >/dev/null

# Inventory is generated from Terraform outputs, so the server IP has one source of truth.
inventory:
	@printf 'vps:\n  hosts:\n    vps-01:\n      ansible_host: %s\n      ansible_user: deploy\n      ansible_ssh_private_key_file: ~/.ssh/hetzner_vps\n      admin_cidrs: %s\n' \
		"$$($(TF) output -raw ipv4)" "$$($(TF) output -json admin_cidrs)" > ansible/inventory.yml
	@echo "ansible/inventory.yml -> $$($(TF) output -raw ipv4)"

# First run only: connects as root (the deploy user doesn't exist yet). Disables root login at the end.
bootstrap: ansible-deps inventory
	$(ANSIBLE) ansible-playbook playbook.yml -e ansible_user=root

# Every later run: connects as the deploy user.
configure: ansible-deps inventory
	. $(SECRETS) && $(ANSIBLE) ansible-playbook playbook.yml

# Dry run: shows what would change, without changing anything.
check: ansible-deps inventory
	. $(SECRETS) && $(ANSIBLE) ansible-playbook playbook.yml --check --diff

# Validates every stack offline: compose files and the Caddyfile (with sample values).
stacks-test:
	@for f in stacks/*/compose.yml; do \
		DOMAIN=example.com ADMIN_CIDRS=203.0.113.10/32 docker compose -f $$f config -q || exit 1; \
	done
	@docker run --rm -e DOMAIN=example.com -e ADMIN_CIDRS="203.0.113.10/32 2001:db8::/64" \
		-v "$(CURDIR)/stacks/caddy/conf:/etc/caddy:ro" $(CADDY_IMAGE) \
		caddy validate --config /etc/caddy/Caddyfile 2>&1 | tail -1
	@echo "stacks ok"

# Deploy agent against a real Docker daemon and a local registry (~1 min).
test-integration:
	python3 -m unittest discover -s agent -p "integration_*.py"

# Checks the live sites over the internet after a deploy.
smoke:
	@scripts/smoke.sh $(DOMAIN)

dev:
	@echo "Not implemented yet: see the roadmap in README.md"
