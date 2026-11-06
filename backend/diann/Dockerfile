# A newer Ubuntu for DIA-NN to run in. DIA-NN's Linux builds need GLIBC 2.34
# or later; the server runs Ubuntu 20.04, which has 2.31. DIA-NN itself is not
# in the image: diann-docker.sh mounts the server's own copy, so updating
# DIA-NN means pointing DIANN_BINARY at the new one, not rebuilding this.
#
# Build once, on the server:
#   docker build -t specvault-diann ~/specvault/backend/diann
FROM ubuntu:24.04

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV LC_ALL=C.UTF-8
