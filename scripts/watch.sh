#!/bin/bash
# logs socket counts and probe latency every 15s; dumps full lsof when a probe is slow or fails
LOG=/tmp/freeze-watch.log
while true; do
  ts=$(date +%H:%M:%S)
  c60084=$(lsof -nP -iTCP:60084 -sTCP:ESTABLISHED | grep -c ESTABLISHED)
  c5001=$(lsof -nP -iTCP:5001 -sTCP:ESTABLISHED | grep -c ESTABLISHED)
  health=$(curl -m 5 -s -o /dev/null -w "%{http_code}/%{time_total}" http://127.0.0.1:5001/health)
  prov=$(curl -m 5 -s -o /dev/null -w "%{http_code}/%{time_total}" \
    -H 'Authorization: Bearer local-session-token' \
    'http://127.0.0.1:5001/api/v1/providers?prefer=true')
  echo "$ts s60084=$c60084 s5001=$c5001 health=$health providers=$prov" >> $LOG
  if [[ "$prov" == 000* ]] || [[ "$health" == 000* ]]; then
    lsof -nP -iTCP:60084 -iTCP:5001 > /tmp/freeze-lsof-$(date +%H%M%S).txt
  fi
  sleep 15
done