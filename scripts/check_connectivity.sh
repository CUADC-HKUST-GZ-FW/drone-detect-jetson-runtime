#!/usr/bin/env bash
set -euo pipefail

PEER=""
DURATION=10
ROLE=""
PORT=5201

while [[ $# -gt 0 ]]; do
  case "$1" in
    --peer) PEER="$2"; shift 2 ;;
    --duration) DURATION="$2"; shift 2 ;;
    --role) ROLE="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$ROLE" ]]; then
  echo "--role server|client is required" >&2
  exit 2
fi

if [[ "$ROLE" == "server" ]]; then
  echo "starting iperf3 server on port $PORT for ${DURATION}s"
  timeout --foreground "$DURATION" iperf3 -s -p "$PORT" -1
elif [[ "$ROLE" == "client" ]]; then
  if [[ -z "$PEER" ]]; then
    echo "--peer is required for client role" >&2
    exit 2
  fi
  echo "ping $PEER"
  ping -c 4 "$PEER"
  echo "iperf3 client -> $PEER:$PORT"
  iperf3 -c "$PEER" -p "$PORT" -t "$DURATION"
else
  echo "invalid --role: $ROLE" >&2
  exit 2
fi

