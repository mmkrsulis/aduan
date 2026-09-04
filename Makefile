.PHONY: deploy status logs

deploy:
	./deploy.sh

status:
	docker compose -f compose.yaml -f compose.dev.yaml ps

logs:
	docker compose -f compose.yaml -f compose.dev.yaml logs --tail=150 -f aduan-hub openwa-delivery-worker
