# AduanHub

[![License: AGPL v3 or later](https://img.shields.io/badge/License-AGPL_v3_or_later-blue.svg)](LICENSE)

Open-source, white-label complaint management for WhatsApp and email. The web edition is free; the optional Android officer application is distributed separately as a premium add-on.

## One-command installation

Linux hosts with Git, Docker, and the Docker Compose plugin can install the complete web stack—including OpenWA—with:

```bash
git clone https://github.com/mmkrsulis/aduan.git aduan-hub
cd aduan-hub
./install.sh
```

Open `http://localhost:18083`, sign in as `admin@demo.local`, and use **Settings → WhatsApp connection** to scan the QR code. The installer generates private secrets and prints the initial administrator password once.

The Android application is not part of this public repository. It uses AduanHub's REST API and is available separately for premium deployments.

## License

AduanHub Web Edition is licensed under the GNU Affero General Public License v3.0 or later (`AGPL-3.0-or-later`). If you run a modified version as a network service, you must offer its corresponding source code to its users under the same license. The premium Android application is a separate product and is not included under this repository's license.

## Run

```bash
cp .env.example .env
sudo docker compose up -d --build
```

Open `http://127.0.0.1:18083`. The bootstrap account is `admin@demo.local`; its initial password is read from `BOOTSTRAP_PASSWORD` in your private `.env` file.

## Easy deployment on the AduanHub server

Deploy the application and its OpenWA integration with one command:

```bash
cd /home/sulis/aduan-hub
make deploy
```

The deployment command validates both Compose files, creates a consistent SQLite backup under `/data/backups`, preserves the previous image for rollback, rebuilds only AduanHub services, and verifies AduanHub plus OpenWA health. If the health check fails, it automatically restores the previous application image. Use `make status` for service status and `make logs` for live application logs.

Configure the organization API key and sender token under **Settings**, then set the MPWA device webhook to `http://<aduan-host>:18083/webhooks/mpwa/demo`.

## Public deployment

Point the chosen domain's A/AAAA record at this server, set `APP_DOMAIN` in `.env`, ensure ports 80/443 are available, then run:

```bash
sudo docker compose -f compose.yaml -f compose.public.yaml up -d --build
```

The public overlay uses Caddy for automatic TLS, HTTP/3, compression, HSTS, and structured access logs. Keep `WEBHOOK_SECRET` private and include it in the MPWA device webhook query string.

For the current host-Nginx deployment, use `deploy/nginx-aduanhub.rekadev.site.conf`. The live demo hostname is `https://aduanhub.rekadev.site`.

## Complaint flow and reports

- Configure bilingual autoreplies under **Settings → Complaint Flow**.
- Citizens can use `MENU`, `BATAL/CANCEL`, `UBAH/EDIT`, `KIRIM/SEND`, `ID`, and `EN`.
- Filter complete complaint records under **Reports** and export CSV or print-ready PDF.

## Security before public exposure

Replace `SECRET_KEY`, terminate TLS at a reverse proxy, restrict container ingress, rotate the seeded accounts, and back up the `aduan_data` volume. MPWA credentials are deployment secrets and should be migrated to a secret manager for a regulated production environment.
