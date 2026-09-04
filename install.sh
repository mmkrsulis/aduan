#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

for command in docker git openssl curl; do
  command -v "$command" >/dev/null || { echo "Perintah $command belum terpasang."; exit 1; }
done
docker compose version >/dev/null

if [ ! -d vendor/OpenWA/.git ]; then
  mkdir -p vendor
  git clone --depth 1 https://github.com/rmyndharis/OpenWA.git vendor/OpenWA
fi

if [ ! -f .env ]; then
  umask 077
  admin_password="$(openssl rand -base64 18 | tr -d '/+=')"
  {
    echo "SECRET_KEY=$(openssl rand -hex 32)"
    echo "WEBHOOK_SECRET=$(openssl rand -hex 32)"
    echo "BOOTSTRAP_PASSWORD=$admin_password"
    echo "ADUAN_BIND=0.0.0.0"
    echo "ADUAN_PORT=18083"
    echo "COOKIE_SECURE=false"
    echo "OPENWA_SESSION_ID="
    echo "PUBLIC_WHATSAPP="
  } > .env
  echo "Password admin awal: $admin_password"
  echo "Simpan password ini sekarang; password tidak akan ditampilkan lagi."
fi

set -a
. ./.env
set +a

if [ -z "${OPENWA_SESSION_ID:-}" ]; then
  echo "Menyiapkan OpenWA..."
  docker compose -f compose.opensource.yaml up -d --build openwa-core
  for _ in $(seq 1 60); do
    if docker compose -f compose.opensource.yaml exec -T openwa-core node -e "fetch('http://127.0.0.1:2785/api/infra/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"; then break; fi
    sleep 3
  done
  session_json="$(docker compose -f compose.opensource.yaml exec -T openwa-core node -e "fetch('http://127.0.0.1:2785/api/sessions',{method:'POST',headers:{'X-API-Key':process.env.API_MASTER_KEY,'Content-Type':'application/json'},body:JSON.stringify({name:'aduanhub'})}).then(async r=>{const t=await r.text();if(!r.ok)throw Error(t);process.stdout.write(t)}).catch(e=>{console.error(e.message);process.exit(1)})")"
  session_id="$(printf '%s' "$session_json" | sed -n 's/.*"id":"\([^"]*\)".*/\1/p')"
  test -n "$session_id" || { echo "OpenWA tidak mengembalikan ID sesi."; exit 1; }
  sed -i "s/^OPENWA_SESSION_ID=.*/OPENWA_SESSION_ID=$session_id/" .env
  export OPENWA_SESSION_ID="$session_id"
fi

docker compose -f compose.opensource.yaml up -d --build

for _ in $(seq 1 60); do
  if curl -fsS --max-time 3 "http://127.0.0.1:${ADUAN_PORT:-18083}/health" >/dev/null; then
    echo "AduanHub siap di http://localhost:${ADUAN_PORT:-18083}"
    echo "Login: admin@demo.local"
    exit 0
  fi
  sleep 3
done

echo "Instalasi selesai dibangun, tetapi pemeriksaan kesehatan belum berhasil."
docker compose -f compose.opensource.yaml ps
exit 1
