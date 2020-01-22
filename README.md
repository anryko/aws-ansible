# aws-ansible

To start using local ansible while hacking on this project source the local environment.

```bash
$ source .env.local
$ which ansible
/Users/Name/git-repos/aws-ansible/docker/ansible/local_bin/ansible
```

## Deploy example VPC

```bash
ansible-playbook plays/aws-infra.yml market/example/config/dev/infra.yml:vpc:1
```

Example of used `.env.yml`

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
