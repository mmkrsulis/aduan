# AduanHub

White-label, multi-tenant complaint management with MPWA intake and replies.

## Run

```bash
cp .env.example .env
sudo docker compose up -d --build
```

Open `http://127.0.0.1:18083`. The bootstrap account is `admin@demo.local`; its initial password is read from `BOOTSTRAP_PASSWORD` in your private `.env` file.

Configure the organization API key and sender token under **Settings**, then set the MPWA device webhook to `http://<aduan-host>:18083/webhooks/mpwa/demo`.

## Public deployment

Point the chosen domain's A/AAAA record at this server, set `APP_DOMAIN` in `.env`, ensure ports 80/443 are available, then run:

```bash
sudo docker compose -f compose.yaml -f compose.public.yaml up -d --build
```

The public overlay uses Caddy for automatic TLS, HTTP/3, compression, HSTS, and structured access logs. Keep `WEBHOOK_SECRET` private and include it in the MPWA device webhook query string.

## Complaint flow and reports

- Configure bilingual autoreplies under **Settings → Complaint Flow**.
- Citizens can use `MENU`, `BATAL/CANCEL`, `UBAH/EDIT`, `KIRIM/SEND`, `ID`, and `EN`.
- Filter complete complaint records under **Reports** and export CSV or print-ready PDF.

## Security before public exposure

Replace `SECRET_KEY`, terminate TLS at a reverse proxy, restrict container ingress, rotate the seeded accounts, and back up the `aduan_data` volume. MPWA credentials are deployment secrets and should be migrated to a secret manager for a regulated production environment.
