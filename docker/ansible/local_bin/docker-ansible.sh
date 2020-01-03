#!/usr/bin/env bash

# Ansible docker run script.
# Pass ansible arguments to the script and it will run ansible docker
# container with all the dependencies included.

ANSIBLE_ROOT=$PWD
ANSIBLE_DOCKER_IMAGE=anryko/ansible:latest
DOCKER_OPTS=${DOCKER_OPTS:-'-it --rm --cap-add SYS_PTRACE --hostname=ansible'}

DOCKER_MOUNTS="-v $ANSIBLE_ROOT:/etc/ansible \
               -v $HOME/.ssh:/root/.ssh \
               -v $HOME/.aws:/root/.aws \
               -v $HOME/.gnupg:/root/.gnupg \
               -v /tmp:/tmp \
               -v /var/run/docker.sock:/var/run/docker.sock"

DOCKER_ENV=${DOCKER_ENV:-}

# Guess market based on passed arguments. Only last occurrence of market key
# is respected.
args=( "$@" )

for i in ${!args[@]}; do
  if [[ ${args[i]} =~ ^market/([a-zA-Z0-9_\.-]+)/(secret|config)/([a-zA-Z0-9_\.-]+)/([a-zA-Z0-9_\./-]+)\.[a-z]+:?([a-zA-Z0-9_\.-]+)?:?([a-zA-Z0-9_\.-]+)?$ ]]; then
    market=${BASH_REMATCH[1]}
    env=${BASH_REMATCH[3]}
    service=${BASH_REMATCH[4]}
    group=${BASH_REMATCH[5]}
    version=${BASH_REMATCH[6]}

    if [[ ${args[i-1]} != '-e' && ${args[i-1]} != '--env' && "$group" && "$version" ]]; then
      unset args[$i]
      args+=('-e' "market=$market" '-e' "env=$env" '-e' "service=$service" '-e' "group=$group" '-e' "version=$version")
    elif [[ ${args[i-2]} = '-e' || ${args[i-2]} = '--env' || ${args[i+1]} = '-e' || ${args[i+1]} = '--env' ]]; then
      unset args[$i]
      args+=('-e' "market=$market" '-e' "env=$env" '-e' "service=$service")
      [[ "$group" ]] && args+=('-e' "group=$group")
      [[ "$version" ]] && args+=('-e' "version=$version")
    fi
  fi

  if [[ ${args[i]} = *'market='* ]]; then
    market=$(echo "${args[i]}" | fmt -1 | grep 'market=' | tail -1 | cut -d= -f2)

    if [[ $i -eq 0 ]] || [[ ${args[i-1]} != '-e' && ${args[i-1]} != '--env' ]]; then
      # Throw away market variable if it's not part of ansible env parameters.
      # Useful when it is needed to get into the ansible container
      # bootstrapped for chosen market. e.g.
      # $ da market=br inventory/ec2.py --list
      # $ ansible-vault view market/us/secret/srv/infra.yml market=br
      # $ ansible-vault market=br edit market/br/secret/stg/infra.yml
      unset args[$i]
    fi
  fi

  if [[ ${args[i]} = *'env='* ]]; then
    env=$(echo "${args[i]}" | fmt -1 | grep 'env=' | tail -1 | cut -d= -f2)

    if [[ $i -eq 0 ]] || [[ ${args[i-1]} != '-e' && ${args[i-1]} != '--env' ]]; then
      unset args[$i]
    fi
  fi
done

if [[ -n $market ]] && [[ -n $env ]] && [[ -e .env.yml ]] \
    && [[ -e ./utilities/infra-vars ]]; then
  DOCKER_ENV_INI_VARS=$(\
    ./utilities/infra-vars get-env $market $env \
      | sed -e '/\[/d;s/#.*$//;/^$/d;s/^/ -e /' \
      | tr -d '\n' \
  )
  DOCKER_ENV="$DOCKER_ENV $DOCKER_ENV_INI_VARS"

elif [[ -e .env ]]; then
  DOCKER_ENV="$DOCKER_ENV --env-file=.env"
fi

if [[ -z $ANSIBLE_FORCE_COLOR ]]; then
  DOCKER_ENV="$DOCKER_ENV -e ANSIBLE_FORCE_COLOR=1"
else
  DOCKER_ENV="$DOCKER_ENV -e ANSIBLE_FORCE_COLOR=$ANSIBLE_FORCE_COLOR"
fi

docker run \
  $DOCKER_OPTS \
  $DOCKER_MOUNTS \
  $DOCKER_ENV \
  $ANSIBLE_DOCKER_IMAGE \
  "${args[@]}"
