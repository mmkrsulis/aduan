# Local development only

Run with `docker compose -f compose.yaml -f compose.dev.yaml up -d --build aduan-hub openwa-delivery-worker`.
Production on reka-1 is independent and was not modified.

## Delivery states

New WhatsApp replies are stored before dispatch. Only messages with `delivery_gateway=openwa` and status `queued` are dispatched; historical imported messages are never replayed.

`queued` → `sending` → `pending` → `sent` (ACK 1) → `delivered` (ACK 2) → `read` (ACK 3) / `played` (ACK 4).

The worker registers an authenticated `onAck` webhook and checks registration every 30 seconds. Early ACKs are buffered and out-of-order ACKs cannot downgrade a confirmed state. A small periodic read-only reconciliation checks recent pending messages using `getMessageById`.

Timeouts, unexpected gateway responses and interrupted dispatch become `unknown`, **never automatically resent**. Check the WhatsApp account before manually resending. A read receipt is shown only when the gateway reports one; recipients' privacy settings may prevent it.

Use exactly one dispatcher container. `WA_API_KEY` is loaded into the worker from `../openwa/.env`, never into browser scripts. Webhook requests require `X-OpenWA-Token` matching `WEBHOOK_SECRET`. Only the dev compose enables the new send path. Production reka-1 continues using its separate MPWA deployment.

## Incoming messages and autoreply

The worker registers `onAnyMessage` at `/hooks/openwa/incoming`; the receiver filters out own, group, broadcast and unsupported system messages. Accepted message IDs are persisted uniquely in `openwa_inbox`. The worker processes them through `/internal/openwa/process`, reusing the existing complaint flow. Flow state changes, incoming ticket messages and the autoreply outbox commit atomically, so retried callbacks cannot advance the same conversation twice. Supported media are decrypted through OpenWA, never fetched from an arbitrary incoming URL.

Bot replies and legacy text notifications use `openwa_system_outbox`; manual chat replies retain their existing queue. A linked bot message is excluded from the manual dispatcher to prevent double sending. Timeout/idle notifications only consider contacts with a new OpenWA inbox event, protecting imported production history from replay.

`openwa/store-compat.cjs` restores the v4 WhatsApp collection bindings after initialization and provides the legacy `models` getter. It does not change licensing restrictions. OpenWA v4 allows replies in existing chats; starting a conversation with a new non-contact may require its license.

Test the flow from another WhatsApp account by sending `MENU`, choose identity, choose the complaint option, enter a description, then `KIRIM`. A human-takeover conversation intentionally has no bot replies until `MENU` or `RESET` starts the flow again.

## Appearance and assignment

The public landing page uses a blue portal theme. In a ticket, **Tampilan** offers presets and custom colors for background/incoming/outgoing/internal-note messages, automatic text contrast, dotted background and reset. Preferences are local to the browser (`aduanhubChatAppearanceV1`), not shared across devices.

**Detail aduan** edits status/priority/category only. **Disposisi aduan** is the single web control for unit/optional officer. Officers must belong to the selected active unit; assigning without an officer clears the previous officer. Closed tickets must be reopened first.

## Tests

`python -m unittest test_delivery -v` uses a temporary database and mocks the gateway; no WhatsApp messages are sent. The optional `browser_smoke.cjs` uses an isolated browser and intercepts all send requests for the simulated send/read check. It is intended to run in the existing OpenWA container with a session cookie supplied over stdin, and should never log that cookie.
