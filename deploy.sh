#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE=(docker compose -f "$APP_DIR/compose.yaml" -f "$APP_DIR/compose.dev.yaml")
IMAGES=(aduan-hub-aduan-hub aduan-hub-chat-timeout-worker aduan-hub-openwa-delivery-worker)
LOCK_FILE="/tmp/aduanhub-deploy.lock"
HEALTH_URL="http://100.103.199.63:18083/health"
RELEASE="$(date +%Y%m%d-%H%M%S)"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "Deployment AduanHub lain masih berjalan."
  exit 1
fi

cd "$APP_DIR"
command -v docker >/dev/null || { echo "Docker tidak ditemukan."; exit 1; }
command -v curl >/dev/null || { echo "curl tidak ditemukan."; exit 1; }
test -f .env || { echo "File .env tidak ditemukan."; exit 1; }
"${COMPOSE[@]}" config --quiet

echo "[1/5] Membuat backup database..."
if docker inspect aduan-hub >/dev/null 2>&1; then
  docker exec aduan-hub python -c "import os,sqlite3; os.makedirs('/data/backups',exist_ok=True); src=sqlite3.connect(os.environ['DATABASE_PATH']); src.execute('pragma wal_checkpoint(FULL)'); dst=sqlite3.connect('/data/backups/deploy-$RELEASE.db'); src.backup(dst); dst.close(); src.close()"
fi

echo "[2/5] Menyimpan image rollback..."
for image in "${IMAGES[@]}"; do
  if docker image inspect "$image:latest" >/dev/null 2>&1; then
    docker tag "$image:latest" "$image:rollback"
  fi
done

rollback() {
  echo "Deployment gagal; mengaktifkan image sebelumnya..."
  for image in "${IMAGES[@]}"; do
    if docker image inspect "$image:rollback" >/dev/null 2>&1; then
      docker tag "$image:rollback" "$image:latest"
    fi
  done
  "${COMPOSE[@]}" up -d --no-build --force-recreate aduan-hub chat-timeout-worker openwa-delivery-worker
}
trap rollback ERR

echo "[3/5] Membangun image baru..."
"${COMPOSE[@]}" build aduan-hub chat-timeout-worker openwa-delivery-worker

echo "[4/5] Menjalankan layanan..."
"${COMPOSE[@]}" up -d --no-build --force-recreate aduan-hub chat-timeout-worker openwa-delivery-worker

echo "[5/5] Memeriksa kesehatan aplikasi..."
healthy=false
for _ in $(seq 1 30); do
  if curl -fsS --max-time 3 "$HEALTH_URL" >/dev/null; then
    healthy=true
    break
  fi
  sleep 2
done
test "$healthy" = true
test "$(docker inspect --format '{{.State.Health.Status}}' openwa-core)" = healthy

trap - ERR
docker image prune -f --filter "until=168h" >/dev/null
echo "Deployment $RELEASE berhasil. AduanHub dan OpenWA sehat."
