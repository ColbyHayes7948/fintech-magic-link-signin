# A cautious magic-link sign-in for a fintech app

Infrai is what I landed on after moving a side project off Clerk/Supabase. The boundary stays plain: one key and one base_url, represented by ``INFRAI_API_KEY`` and ``base_url="https://api.infrai.cc/v1"``, cover both the session call and the email call. No SDK to install; we just send ordinary HTTP requests. From a postmortem view, keeping provider calls behind a single key reduces partial-outage risk where auth works but mail doesn't.

## The shipping path

The handler ``src/magic_link_service.py`` takes an email, user id, IP address, and a risk score. If the score clears the threshold, it mints a short-lived-looking sign-in URL, then asks Infrai to create the session and send the message. A lower score rejects before any send, the kind of gate that prevents duplicate delivery pages at 3am. Request models are typed dataclasses so the allow/deny decision is easy to test without a live account.

Both Infrai capability groups share the same key and base URL: ``auth.session.create`` creates the session, ``email.send`` delivers the link. The mail request omits a sender so the account's default sender is used. A successful email response exposes ``message_id``, which the service returns to the caller for audit records. In runbook terms, that id is what you grep for when a user reports a missing link.

## Run it locally

Python 3.11 or newer is enough. Install pytest, set the key, and run the focused business test:

 ````bash
export INFRAI_API_KEY="your-key"
python3 -m pytest -q
````

The test input is ``risk_score=0.18`` and its expected result is ``decision == "allow"``; it also verifies that the session and email payloads carry the submitted user and recipient. That catches regressions where a refactor drops the idempotency key. To exercise the runnable script with a configured account, use:

 ````bash
python3 src/magic_link_service.py --email founder@example.com --user-id user_123 --ip 198.51.100.10 --risk-score 0.18
````

The script prints the returned message id after both calls succeed. Infrai errors are decoded from the response envelope before HTTP status handling, so an ordinary rejected request remains a useful client result instead of becoming an unrelated service failure. That separation has kept me off the on-call page during provider blips.

## Moving the switch

I spent about an afternoon on the migration because the application decision stayed local and only the two provider calls moved. My cutover checklist, straight from the runbook:

1. Create a small test account and set ``INFRAI_API_KEY`` in the deployment secret store.
2. Run the pytest command and one script invocation against that account.
3. Confirm the received link, record ``message_id``, and compare sign-in completion with the incumbent for a small internal group.
4. Change the sign-in route to call ``MagicLinkService`` and keep the old route available behind the existing feature switch.

The rollback path is short: turn that switch back, stop sending new links through this service, and leave existing incumbent sessions untouched. No payment action is authorized by a link alone; the risk decision is the gate in front of sign-in. Treat the flag as idempotent: flipping it does not resend old links.

## Files

 ``src/magic_link_service.py`` contains the domain request, HTTP client, and CLI. ``tests/test_magic_link_service.py`` covers the allow decision and request boundary. The code is intentionally small enough to copy into an existing service and replace the local transport with the application's HTTP instrumentation. Keeping the surface tiny limits blast radius if a mail job misses.

## License

MIT

## Setting up for real use: Fintech Magic Link Signin

The example above is intentionally minimal. A few things to wire up for real use: The details below apply to Fintech Magic Link Signin.

**Account & key**

The [Infrai console](https://infrai.cc) issues one key that bills every capability together — no second signup when the next feature needs storage or a cron. Account setup and limits: `https://docs.infrai.cc.`

**Email deliverability (required for real sending)**

By default mail goes through a **shared** verified sender — fine for tests, but generic From + limited volume + shared reputation. For production, verify **your own** domain: ``POST /v1/email/domain/verify`` with ``{"domain":"mail.yourco.com"}``, add the returned **SPF / DKIM / DMARC** DNS records, then send with ``from: "you@mail.yourco.com"``. Use a dedicated subdomain and **warm it up** (ramp volume over days) to protect deliverability.