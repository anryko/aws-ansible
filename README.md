# aws-ansible <!-- omit in toc -->

## Table of Contents <!-- omit in toc -->

- [Hacking](#hacking)
- [Directory Structure](#directory-structure)
- [Config variable templating](#config-variable-templating)
  - [Templating example](#templating-example)
- [AWS access configuration](#aws-access-configuration)
- [Deployment](#deployment)
  - [Adding vault secrets](#adding-vault-secrets)
  - [Deploying VPC infra](#deploying-vpc-infra)

## Hacking

To start using local ansible while hacking on this project `source` the local environment.

```bash
$ source .env.local
$ which ansible
/Users/Name/git-repos/aws-ansible/docker/ansible/local_bin/ansible
```

## Directory Structure

| Path         | Description                                                       |
| :----------- | :---------------------------------------------------------------- |
| `docker/`    | Custom Docker image build files.                                  |
| `inventory/` | Ansible dynamic AWS service discovery and static hosts variables. |
| `lambdas/`   | Lambdas code and builds                                           |
| `market/`    | Market configuration and secret files.                            |
| `plays/`     | Ansible playbooks.                                                |
| `plugins/`   | Custom Ansible plugins.                                           |
| `roles/`     | Ansible roles.                                                    |
| `tmp/`       | Ansible temp files and logs.                                      |
| `utilities/` | Utility scripts.                                                  |

## Config variable templating

Templating can be used in `market/<market>/config/<env>/<service>.yml` configuration files.
There are two types of variable pattern matching:

- Public variables: `"{? variable_name ?}"`
- Secret variables: `"{! variable_name !}"`

Both substitutions are performed by custom Ansible lookup plugin `plugins/lookup/tmpl_files.py`.

### Templating example

Public config in `market/<market>/config/<env>/<service>.yml`:

```yaml
service:
  group1:
    app:
      secret_cookie: "{! app_secret_cookie !}"
    service:
      secret_list: "{! service_secret_list !}"
      secret_whatever: "{! service_secret_whatever !}"
      secret_partial: "secret number - {! service_secret_number !}"
```

Secret vault encrypted config in `market/<market>/secret/<env>/<service>.yml`:

```yaml
service:
  group1:
    secrets:
      app_secret_cookie: ThisIsVerySecretString
      service_secret_whatever:
      - name: SecretName
        value: SecretValue
      - WhateverSecretString
      service_secret_number: 42
```

Secrets are stored in encrypted file but can be referenced in a config via `{! secret_variable_name !}` template expression.

Resulting configuration object during playbook execution will be:

```yaml
service:
  group:
    app:
      secret_cookie: "ThisIsVerySecretString"
    service:
      secret_whatever:
      - name: SecretName
        value: SecretValue
      - WhateverSecretString
      secret_partial: "secret number - 42"
```

Public variable templating works in the same way. Different variable templating pattern `"{? var ?}"` is used for configuration clarity. Public variables are defined in the playbook or passed to `ansible-playbook` via `-e/--env` option.

## AWS access configuration

Add `.env.yml` file to the root of this git repository. Set correct values for your environment variables and passwords.

```yaml
---
markets:
  example:
    env:
      AWS_PROFILE: default
      AWS_REGION: us-east-2
      ANSIBLE_VAULT_PASSWORD: B4KTS5XKPbxq13RAGHHDmjaQpDmvTv+N19r517xapsKZdKRCMJxn1n0rQkBM
    environments:
      dev:
        env:
          BASTION_HOST: bastion.dev.example.mov.lt
          BASTION_SSH_KEY: ~/.ssh/example/example-dev-bastion-key.pem
          SSH_KEY: ~/.ssh/example/example-dev-default-key.pem
      # prd:
      #   env:
      #     BASTION_HOST: bastion.prd.example.mov.lt
      #     BASTION_SSH_KEY: ~/.ssh/example/example-prd-bastion-key.pem
      #     SSH_KEY: ~/.ssh/example/example-prd-default-key.pem
```

During playbook execution `markets.<market>.environments.<env>.env` and `markets.<market>.env` are merged. In this way all the environment variables defined in `markets.example.env` apply to all subordinate environments.

## Deployment

Ansible playbook input path is parsed as:

```bash
market/<market>/config/<env>/<service>.yml:<group>:<version>
```

In some cases `<version>` is not actually used and set value of `1` serves as a placeholder.

Same parsing is applied to `ansible-vault` path (excluding `:<group>:<version>`) to determine `ANSIBLE_VAULT_PASSWORD` to apply.

### Adding vault secrets

```bash
$ ansible-vault create market/example/secret/dev/infra.yml
$ ansible-vault view market/example/secret/dev/infra.yml
---
infra:
  secrets:
    dummy_api_key: dummy
```

### Deploying VPC infra

```bash
ansible-playbook plays/aws-infra.yml market/example/config/dev/infra.yml:vpc:1
```
