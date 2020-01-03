# Custom Ansible docker image

## Local docker-ansible setup

- Install [Docker](https://www.docker.com) on your operating system.
- Run `./install.sh` to install docker-ansible.
  If you are having issues with automated `install.sh`, fallback to manual setup:
  - Ensure user's `bin` directory is present: `mkdir ~/bin`.
  - Copy scripts: `cp -Pav local_bin/* ~/bin/`.
  - Check ansible path: `which ansible`. It should point to your users's local bin. If this is not the case you need to append `PATH=~/bin:$PATH` to your `~/.profile` and apply profile change for current session `source ~/.profile`.

## Versions

- 2.9_0 (latest)

## Build Instructions

Build docker-ansible image and push to docker hub.

```bash
IMAGE=anryko/ansible TAG=2.9_0 && \
  docker build --squash -t $IMAGE:$TAG . && \
  docker push $IMAGE:$TAG && \
  docker tag $IMAGE:$TAG $IMAGE:latest && \
  docker push $IMAGE:latest
```
