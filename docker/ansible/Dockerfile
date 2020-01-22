FROM python:3-slim
LABEL maintainer="a.shvenke@gmail.com"

ARG DEBIAN_FRONTEND=noninteractive
ARG APT_INSTALL_OPTS='-y --no-install-recommends'
ARG APT_BUILD_DEPENDENCIES='\
  build-essential \
  python3-dev \
  libffi-dev \
  libssl-dev'
ARG PIP_ARGS='--upgrade --no-cache-dir --disable-pip-version-check'
ARG ANSIBLE_GIT_REPO='git+https://github.com/ansible/ansible.git'
ARG ANSIBLE_GIT_BRANCH='stable-2.9'
ARG ANSIBLE_LINT_GIT_REPO='git+https://github.com/ansible/ansible-lint.git'
ARG ANSIBLE_LINT_BRANCH='master'
ARG PACKER_VERSION='1.4.5'
ARG PACKER_DOWNLOAD_URL="https://releases.hashicorp.com/packer/\
${PACKER_VERSION}/packer_${PACKER_VERSION}_linux_amd64.zip"

RUN apt-get update && \
    apt-get -y upgrade && \
    # Install required apt packages.
    apt-get install $APT_INSTALL_OPTS \
      $APT_BUILD_DEPENDENCIES \
      libcurl4 \
      curl \
      git \
      vim \
      rsync \
      unzip \
      make \
      groff \
      gnupg2 \
      gnupg-agent \
      openssh-client \
      apt-transport-https \
      software-properties-common \
      && \
    ln -s /usr/local/bin/python /usr/bin/python && \
    pip install $PIP_ARGS \
      boto \
      boto3 \
      botocore \
      requests \
      cryptography \
      pycrypto \
      wheel \
      configobj \
      pyOpenSSL \
      awscli \
      netaddr \
      $ANSIBLE_GIT_REPO@$ANSIBLE_GIT_BRANCH#egg=ansible \
      $ANSIBLE_LINT_GIT_REPO@$ANSIBLE_LINT_BRANCH#egg=ansible-lint \
      && \
    # Add docker tools.
    curl -fsSL https://download.docker.com/linux/debian/gpg \
      | apt-key add - && \
    add-apt-repository \
      "deb [arch=amd64] https://download.docker.com/linux/debian \
      $(lsb_release -cs) \
      stable" && \
    apt-get update && \
    apt-get install $APT_INSTALL_OPTS docker-ce-cli && \
    # Add packer.
    curl -fsSL "$PACKER_DOWNLOAD_URL" -o packer.zip && \
    unzip packer.zip && \
    rm packer.zip && \
    mv packer /bin/ && \
    chmod 755 /bin/packer && \
    # Configure ansible.
    mkdir /etc/ansible && \
    echo "[local]\nlocalhost\n" > /etc/ansible/hosts && \
    # Cleanup.
    apt-get purge --auto-remove -y $APT_BUILD_DEPENDENCIES && \
    apt-get clean all && \
    apt-get -y autoremove && \
    rm -rf \
      /root/.cache/* \
      /var/lib/apt/lists/* \
      /tmp/*

WORKDIR /etc/ansible

CMD ["ansible-playbook", "--version"]
