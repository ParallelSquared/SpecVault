#!/bin/sh
# DIA-NN, run inside the specvault-diann container (see Dockerfile here).
#
# Point DIANN_PATH at this script and DIANN_BINARY at DIA-NN itself, both in
# backend/.env. SpecVault runs this exactly as it would run DIA-NN, with the
# same arguments.
#
# Every folder DIA-NN is given a path in is mounted at that same path inside
# the container, so the arguments need no translating: DIA-NN's own folder,
# the lab share (read-only; SpecVault writes the copy, not DIA-NN), and the
# scratch folder DIA-NN writes into. It runs as the calling user, so what it
# writes belongs to them.
set -e

: "${DIANN_BINARY:?set DIANN_BINARY to DIA-NN itself, e.g. /home/ip2/Documents/diann-2.0.1/diann-linux}"
SHARE="${SHARE_MOUNT:-/home/ip2/syno_mount/lab}"
SCRATCH="${TMPDIR:-/tmp}"
DIANN_DIR="$(dirname "$DIANN_BINARY")"

exec docker run --rm \
    --user "$(id -u):$(id -g)" \
    -v "$DIANN_DIR:$DIANN_DIR:ro" \
    -v "$SHARE:$SHARE:ro" \
    -v "$SCRATCH:$SCRATCH" \
    -e TMPDIR="$SCRATCH" \
    -w "$PWD" \
    specvault-diann "$DIANN_BINARY" "$@"
