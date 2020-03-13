FROM python:3.7

ARG DEBIAN_FRONTEND=noninteractive
ARG PIP_ARGS='--quiet --upgrade --no-cache-dir --disable-pip-version-check'

RUN apt-get update && \
    apt-get install -y zip

WORKDIR /lambda

# Add the requiremts
ADD requirements.txt /tmp
RUN pip install $PIP_ARGS -t /lambda -r /tmp/requirements.txt

# Add the source code
ADD src/ /lambda/
RUN find /lambda -type d | xargs chmod ugo+rx && \
    find /lambda -type f | xargs chmod ugo+r

# compile the lot
RUN python -m compileall -q /lambda

RUN zip --quiet -9r /lambda.zip . \
    -x '.mypy_cache/*' \
    -x '*.swp' \
    -x '*.dist-info/*'


FROM scratch
COPY --from=0 /lambda.zip /
