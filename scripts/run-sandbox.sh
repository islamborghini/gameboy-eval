#!/usr/bin/env bash
# Bring up the faithful generation topology: an *internal* Docker network where the offline
# build sandbox can reach ONLY the SameBoy oracle container (reachable as host `gb-oracle`,
# i.e. $ORACLE_URL) and has no route to the internet.
#
#   docker build -t gameboy-eval-oracle -f oracle/Dockerfile .
#   docker build -t gameboy-eval-gen    -f env/Dockerfile .
#   scripts/run-sandbox.sh
set -euo pipefail

NET=gb-eval-net
ORACLE_IMG=gameboy-eval-oracle
GEN_IMG=gameboy-eval-gen

docker network inspect "$NET" >/dev/null 2>&1 || docker network create --internal "$NET"
docker rm -f gb-oracle >/dev/null 2>&1 || true
docker run -d --name gb-oracle --network "$NET" "$ORACLE_IMG" >/dev/null
echo "started oracle on internal network '$NET' as host 'gb-oracle'"

probe='import urllib.request;urllib.request.urlopen("http://gb-oracle:8765/health",timeout=3)'
printf "waiting for oracle"
for _ in $(seq 1 60); do
  if docker run --rm --network "$NET" "$GEN_IMG" python3 -c "$probe" >/dev/null 2>&1; then
    echo " up."; break
  fi
  printf "."; sleep 1
done

echo "--- [sandbox] oracle reachable? ---"
docker run --rm --network "$NET" "$GEN_IMG" python3 -c \
  'import urllib.request,os;print(urllib.request.urlopen(os.environ["ORACLE_URL"]+"/health",timeout=5).read().decode())'

echo "--- [sandbox] internet blocked? (expect failure) ---"
docker run --rm --network "$NET" "$GEN_IMG" sh -c \
  'timeout 8 python3 -c "import urllib.request;urllib.request.urlopen(\"https://github.com\",timeout=6)" \
     && echo "INTERNET REACHABLE (bad)" || echo "internet blocked (good)"'

echo
echo "oracle is up; the sandbox sees only it. tear down with:"
echo "  docker rm -f gb-oracle && docker network rm $NET"
