#!/usr/bin/env bash
# Real Docker verification of ARO 3D Studio (Phase 4). Builds the image, inspects it, runs it hardened and checks behaviour.
#
#   scripts/verify_docker.sh                         # normal host with Docker
#   DOCKER_BUILD_ARGS="--network host --build-arg PYTHON_IMAGE=... --build-arg HTTPS_PROXY=..." scripts/verify_docker.sh   # restricted sandbox
#
# Env: IMAGE, PORT, MAX_UPLOAD_MB (default 1), MEMORY_LIMIT (default 768m), SKIP_BUILD=1, OUT (evidence dir),
#      DOCKER_RUN_ARGS (extra flags for `docker run`, e.g. "--network host" if bridge networking is unavailable)
# Exit 0 only if every check passed. Evidence: $OUT/docker-verification.json
set -uo pipefail
cd "$(dirname "$0")/.."
IMAGE=${IMAGE:-aro-3d-studio:verify}
PORT=${PORT:-17860}
MAXMB=${MAX_UPLOAD_MB:-1}
MEM=${MEMORY_LIMIT:-768m}
OUT=${OUT:-docs/acceptance/evidence/docker}
NAME=aro-verify
VOL=aro-verify-data
TOKEN=${TOKEN:-$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')}
mkdir -p "$OUT"; STEPS="$OUT/steps.jsonl"; : > "$STEPS"
FAILS=0
step() { # name status detail
  python3 - "$1" "$2" "$3" >> "$STEPS" <<'PY'
import json,sys; print(json.dumps({"step":sys.argv[1],"result":sys.argv[2],"detail":sys.argv[3][:400]}))
PY
  echo "[$2] $1  ${3:0:150}"; [ "$2" = PASS ] || FAILS=$((FAILS+1))
}
ok() { [ "$1" = 0 ] && echo PASS || echo FAIL; }
wait_health() { for _ in $(seq 1 60); do curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null && return 0; sleep 1; done; return 1; }
run_container() { # extra args...
  docker rm -f $NAME >/dev/null 2>&1
  # the root filesystem is read-only: without a named volume the data dir needs an (ephemeral) tmpfs
  local datamount="--tmpfs /home/user/data:uid=1000,gid=1000"
  case " $* " in *" -v "*) datamount="";; esac
  docker run -d --name $NAME -p "$PORT:7860" --memory "$MEM" --memory-swap "$MEM" --cpus 2 --pids-limit 256 \
    --read-only --tmpfs /tmp $datamount --cap-drop ALL --security-opt no-new-privileges \
    -e ARO_ACCESS_TOKEN="$TOKEN" -e ARO_MAX_UPLOAD_MB="$MAXMB" -e HF_HOME=/home/user/data/hf ${DOCKER_RUN_ARGS:-} "$@" "$IMAGE" >/dev/null
}
trap 'docker rm -f $NAME >/dev/null 2>&1; docker volume rm -f $VOL >/dev/null 2>&1; docker rm -f $NAME-b >/dev/null 2>&1' EXIT

docker version --format '{{.Server.Version}}' >/dev/null 2>&1 || { step "docker daemon reachable" FAIL "no daemon"; exit 2; }
step "docker daemon reachable" PASS "server $(docker version --format '{{.Server.Version}}')"

# 1. build ------------------------------------------------------------------------------------------------------------------
if [ "${SKIP_BUILD:-0}" != 1 ]; then
  t0=$(date +%s)
  # shellcheck disable=SC2086
  docker build ${DOCKER_BUILD_ARGS:-} -t "$IMAGE" . > "$OUT/build.log" 2>&1; rc=$?
  step "docker build (clean dependency install from requirements.txt)" "$(ok $rc)" "exit $rc in $(( $(date +%s) - t0 ))s; log: $OUT/build.log"
  [ $rc = 0 ] || { echo "build failed"; tail -20 "$OUT/build.log"; exit 1; }
fi
SIZE=$(docker image inspect "$IMAGE" -f '{{.Size}}'); ID=$(docker image inspect "$IMAGE" -f '{{.Id}}')
step "image inspected" PASS "id $ID size $((SIZE/1000000)) MB user=$(docker image inspect "$IMAGE" -f '{{.Config.User}}')"
[ "$(docker image inspect "$IMAGE" -f '{{.Config.User}}')" = user ] && step "image runs as a non-root user" PASS "USER user" || step "image runs as a non-root user" FAIL "USER not set"

# 2. image contents ---------------------------------------------------------------------------------------------------------
out=$(docker run --rm --entrypoint python "$IMAGE" -m pip check 2>&1); step "pip check inside the image" "$([ "$out" = "No broken requirements found." ] && echo PASS || echo FAIL)" "$out"
out=$(docker run --rm --entrypoint python "$IMAGE" -c "
import importlib,pkgutil,aro_studio,sys
bad=[m.name for m in pkgutil.walk_packages(aro_studio.__path__,'aro_studio.') if not (lambda n: (importlib.import_module(n),True))(m.name)]
print('python',sys.version.split()[0],'imports ok')" 2>&1); step "every aro_studio module imports on the image's Python" "$([[ $out == *'imports ok'* ]] && echo PASS || echo FAIL)" "$out"
out=$(docker run --rm --entrypoint sh "$IMAGE" -c 'id -u; ls -A /home/user/app | tr "\n" " "'); 
bad=""; for n in tests docs .git .env; do case " $(echo $out) " in *" $n "*) bad="$bad $n";; esac; done
step "image contains no tests/.git/.env/docs" "$([ -z "$bad" ] && echo PASS || echo FAIL)" "uid+files: $(echo $out)"
SCAN='
import os,re,sys
pats={"hf token":r"hf_[A-Za-z0-9]{20,}","private key":r"-----BEGIN [A-Z ]*PRIVATE KEY-----","aws key":r"AKIA[0-9A-Z]{16}","github token":r"gh[pousr]_[A-Za-z0-9]{30,}","token assignment":r"ARO_ACCESS_TOKEN=[A-Za-z0-9_\-]{12,}","password assignment":r"(?i)password\s*=\s*[\x27\"][^\x27\"$<{]{6,}"}
hits=[]
for root in ("/home/user/app","/home/user/data"):
    for d,_,fs in os.walk(root):
        for f in fs:
            p=os.path.join(d,f)
            if os.path.getsize(p)>2_000_000: continue
            try: t="\n".join(l for l in open(p,errors="ignore").read().splitlines() if not l.lstrip().startswith("#"))
            except OSError: continue
            for k,r in pats.items():
                if re.search(r,t): hits.append((k,p))
print("HITS",hits)'
out=$(docker run --rm --entrypoint python "$IMAGE" -c "$SCAN"); step "no secrets embedded in the application layer" "$([ "$out" = "HITS []" ] && echo PASS || echo FAIL)" "$out"
envs=$(docker image inspect "$IMAGE" -f '{{json .Config.Env}}'); step "image ENV holds no token/secret/password" "$([[ ! $envs =~ [Tt][Oo][Kk][Ee][Nn]|[Ss][Ee][Cc][Rr][Ee][Tt]|[Pp][Aa][Ss][Ss][Ww] ]] && echo PASS || echo FAIL)" "$envs"
hist=$(docker history --no-trunc --format '{{.CreatedBy}}' "$IMAGE")
step "docker history contains no secrets or proxy settings" "$([[ ! $hist =~ [Tt][Oo][Kk][Ee][Nn]=|127\.0\.0\.1:[0-9]+ ]] && echo PASS || echo FAIL)" "checked $(echo "$hist" | wc -l) layers"

# 3. run hardened -----------------------------------------------------------------------------------------------------------
docker volume create $VOL >/dev/null
run_container -v $VOL:/home/user/data
if wait_health; then step "container starts and /api/health answers (read-only rootfs, caps dropped, mem $MEM, 2 cpus)" PASS "port $PORT"; else step "container starts and /api/health answers" FAIL "$(docker logs $NAME 2>&1 | tail -5)"; exit 1; fi
for _ in $(seq 1 40); do hs=$(docker inspect $NAME -f '{{.State.Health.Status}}'); [ "$hs" = healthy ] && break; sleep 2; done
step "Docker HEALTHCHECK reports healthy" "$([ "$hs" = healthy ] && echo PASS || echo FAIL)" "$hs"
step "process uid inside the running container is 1000" "$([ "$(docker exec $NAME id -u)" = 1000 ] && echo PASS || echo FAIL)" "uid $(docker exec $NAME id -u)"
docker exec $NAME sh -c 'touch /home/user/app/x 2>&1' >/dev/null 2>&1; step "application directory is read-only at runtime" "$([ $? != 0 ] && echo PASS || echo FAIL)" "touch failed as expected"

# 4. HTTP-level checks ------------------------------------------------------------------------------------------------------
python3 scripts/verify_deployment.py --base-url "http://127.0.0.1:$PORT" --token "$TOKEN" --max-upload-mb "$MAXMB" --expect-no-ai --out "$OUT/deployment-checks.json" > "$OUT/deployment-checks.log" 2>&1; rc=$?
step "HTTP verification suite (auth, uploads, archives, traversal, inference failure, full pipeline, export)" "$(ok $rc)" "$(tail -1 "$OUT/deployment-checks.log")"
oom=$(docker inspect $NAME -f '{{.State.OOMKilled}}'); mem=$(docker stats --no-stream --format '{{.MemUsage}}' $NAME)
step "no OOM kill under the $MEM limit; memory in use after the pipeline" "$([ "$oom" = false ] && echo PASS || echo FAIL)" "OOMKilled=$oom mem=$mem"
sysj=$(curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:$PORT/api/system")
step "service sees the container memory limit (cgroup-aware resource checks)" "$(python3 -c "
import json,sys; j=json.loads(sys.argv[1]); r=j['resources']; lim=j.get('cgroup_memory_limit_mb')
print('PASS' if lim and r['ram_total_mb']<=lim else 'FAIL')" "$sysj")" "$(python3 -c "
import json,sys; j=json.loads(sys.argv[1]); r=j['resources']; print('cgroup limit',j.get('cgroup_memory_limit_mb'),'MB; ram_total',r['ram_total_mb'],'MB; ram_available',r['ram_available_mb'],'MB')" "$sysj")"

# 5. persistence ------------------------------------------------------------------------------------------------------------
count() { curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:$PORT/api/projects" | python3 -c "import json,sys; print(len(json.load(sys.stdin)['items']))"; }
before=$(count)
docker restart $NAME >/dev/null; wait_health; after=$(count)
step "data survives a container restart (named volume)" "$([ "$before" -ge 1 ] && [ "$before" = "$after" ] && echo PASS || echo FAIL)" "projects before=$before after=$after"
docker rm -f $NAME >/dev/null; run_container -v $VOL:/home/user/data; wait_health; replaced=$(count)
step "data survives container replacement with the same volume" "$([ "$replaced" = "$before" ] && echo PASS || echo FAIL)" "projects=$replaced"
jobs=$(curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:$PORT/api/jobs?limit=200" | python3 -c "import json,sys; print(len(json.load(sys.stdin)['items']))")
step "job history (incl. the failed inference job) persisted" "$([ "$jobs" -ge 5 ] && echo PASS || echo FAIL)" "$jobs jobs"
docker rm -f $NAME >/dev/null; run_container; wait_health; fresh=$(count)
step "without a volume the data is ephemeral (documented behaviour of free Spaces)" "$([ "$fresh" = 0 ] && echo PASS || echo FAIL)" "projects=$fresh in a fresh container"

# 6. resource limits / failure containment ----------------------------------------------------------------------------------
docker rm -f $NAME >/dev/null; MEM_SAVE=$MEM; MEM=160m; run_container; MEM=$MEM_SAVE
if wait_health; then
  r=$(python3 - "$PORT" "$TOKEN" <<'PY'
import json,sys,urllib.request
b=f"http://127.0.0.1:{sys.argv[1]}"; h={"Authorization":"Bearer "+sys.argv[2]}
j=json.load(urllib.request.urlopen(urllib.request.Request(b+"/api/system",headers=h)))
print(j["resources"]["ram_total_mb"], j["resources"]["ram_available_mb"], j.get("cgroup_memory_limit_mb"))
PY
)
  step "160 MB container: the service starts and reports the real (cgroup) limit" "$([[ $r == *' 160' ]] && echo PASS || echo FAIL)" "ram_total/ram_available/limit = $r"
else step "160 MB container: the service starts" FAIL "$(docker logs $NAME 2>&1 | tail -3)"; fi
docker rm -f $NAME >/dev/null

python3 - "$OUT" "$IMAGE" "$ID" "$SIZE" "$MEM" "$MAXMB" "${DOCKER_BUILD_ARGS:-}" "${DOCKER_RUN_ARGS:-}" "${SKIP_BUILD:-0}" <<'PY'
import json,sys,time,platform,subprocess,re
out,image,iid,size,mem,maxmb,bargs,rargs,skipb=sys.argv[1:10]
bargs=re.sub(r"(PROXY=)\S+",r"\1<redacted>",bargs)
caveats=[]
if "PYTHON_IMAGE=" in bargs: caveats.append("base image overridden at build time ("+re.search(r"PYTHON_IMAGE=\S+",bargs).group(0)+"): the Dockerfile default is a digest-pinned python:3.11-slim")
if "--network host" in bargs: caveats.append("build used --network host (sandbox without bridge networking)")
if "HTTPS_PROXY" in bargs: caveats.append("build went through an egress proxy")
if rargs: caveats.append("extra docker run args: "+rargs)
if skipb=="1": caveats.append("build step skipped (SKIP_BUILD=1): an existing image was verified")
steps=[json.loads(l) for l in open(f"{out}/steps.jsonl")]
dep=json.load(open(f"{out}/deployment-checks.json")) if __import__("os").path.exists(f"{out}/deployment-checks.json") else None
doc={"when":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),"image":image,"image_id":iid,"image_size_bytes":int(size),
     "docker_server":subprocess.run(["docker","version","--format","{{.Server.Version}}"],capture_output=True,text=True).stdout.strip(),
     "host":platform.platform(),"memory_limit":mem,"max_upload_mb":maxmb,
     "passed":sum(s["result"]=="PASS" for s in steps),"failed":sum(s["result"]!="PASS" for s in steps),"caveats":caveats,"build_args":bargs,"steps":steps,"http_checks":dep}
json.dump(doc,open(f"{out}/docker-verification.json","w"),indent=2)
print(f"\n{doc['passed']}/{len(steps)} docker steps passed; HTTP checks: {dep['passed']}/{dep['passed']+dep['failed']}" if dep else "")
PY
echo "evidence: $OUT/docker-verification.json"; [ "$FAILS" = 0 ]
