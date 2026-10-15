.PHONY: test lint dev init plan apply ansible-deps inventory bootstrap configure check

TF := terraform -chdir=terraform
SECRETS := $(HOME)/.config/infra/secrets.env
# Ansible needs a valid UTF-8 locale; C.UTF-8 exists everywhere.
ANSIBLE := cd ansible && LC_ALL=C.UTF-8 ANSIBLE_CONFIG=ansible.cfg

init:
	$(TF) init -input=false

test: ansible-deps
	@$(TF) init -input=false -backend=false >/dev/null
	$(TF) test
	$(ANSIBLE) ansible-playbook -i localhost, --syntax-check playbook.yml

lint: ansible-deps
	$(TF) fmt -check -recursive
	@$(TF) init -input=false -backend=false >/dev/null
	$(TF) validate
	$(ANSIBLE) ansible-lint --profile production

plan:
	. $(SECRETS) && $(TF) plan -input=false -out=tfplan

apply:
	. $(SECRETS) && $(TF) apply -input=false tfplan

ansible-deps:
	@$(ANSIBLE) ansible-galaxy collection install -r requirements.yml -p collections >/dev/null

# Inventory is generated from Terraform outputs, so the server IP has one source of truth.
inventory:
	@printf 'vps:\n  hosts:\n    vps-01:\n      ansible_host: %s\n      ansible_user: deploy\n      ansible_ssh_private_key_file: ~/.ssh/hetzner_vps\n' \
		"$$($(TF) output -raw ipv4)" > ansible/inventory.yml
	@echo "ansible/inventory.yml -> $$($(TF) output -raw ipv4)"

# First run only: connects as root (the deploy user doesn't exist yet). Disables root login at the end.
bootstrap: ansible-deps inventory
	$(ANSIBLE) ansible-playbook playbook.yml -e ansible_user=root

# Every later run: connects as the deploy user.
configure: ansible-deps inventory
	$(ANSIBLE) ansible-playbook playbook.yml

# Dry run: shows what would change, without changing anything.
check: ansible-deps inventory
	$(ANSIBLE) ansible-playbook playbook.yml --check --diff

dev:
	@echo "Not implemented yet: see the roadmap in README.md"
