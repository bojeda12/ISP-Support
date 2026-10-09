# ISP Support

Local Django support demo for a US Internet service provider. Python 3.14.5,
Django REST Framework, temporary SQLite, simulated diagnostics, bilingual
conversations, automatic tickets, private photo analysis and a Bootstrap widget.
No real ISP systems, network commands or SMS are connected.

## Run locally on Windows

Keep the existing `.venv`. From the project directory in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py seed_demo
.\.venv\Scripts\python.exe manage.py createsuperuser
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Skip superuser creation if one already exists. Configure `.env` using
`.env.example`; the minimum local demo configuration is:

```dotenv
DJANGO_ENV=development
DJANGO_DEBUG=true
ENABLE_DEMO_CHAT=true
AI_PROVIDER=demo
DJANGO_TIME_ZONE=UTC
```

Open **http://127.0.0.1:8000/demo/** and sign in through Django Admin. A superuser
can use the demo; other operators must be active staff with
`conversations.use_demo_chat`. The welcome screen requires an explicit English
or Spanish choice and Continue. Then select a fictional service and connect.
No shared demo password, browser API key or fixed JavaScript token is provided.

The UI, login and Admin use US English. Conversation language is independent:
clear English/Spanish messages adapt subsequent responses, ambiguous messages
such as OK retain the previous language, and the conversation selector provides
an explicit override for the next message. Previous customer messages remain
unchanged. Refresh restores the conversation and bypasses initial selection for
an existing conversation. Changing services starts a new chat and requires a
fresh confirmation if a conversation was already active.

`DJANGO_TIME_ZONE` accepts an IANA zone name. UTC is only the default, not an
assumption about the ISP location. Admin and widget display that configured
zone; timestamps remain timezone-aware. Installations include `tzdata` for
Windows. Restart the server after changing environment configuration.

## Demo scenarios

`seed_demo` is idempotent and only manages its deterministic fictional records.

| Service | Scenario |
| --- | --- |
| DEMO-SERVICE-001 | Active service, unreachable CPE / disconnected PoE simulation |
| DEMO-SERVICE-002 | Active service, weak wireless signal |
| DEMO-SERVICE-003 | Administratively suspended account |
| DEMO-SERVICE-004 | Healthy simulated link |
| DEMO-SERVICE-005 | Degraded simulated performance |

For the offline flow, send “My internet is not working.” Four protected guides
explain locating a generic PoE injector, observing an indicator if present,
inspecting accessible Ethernet connections and asking for a new diagnostic.
Then send “Ya revisé los cables, pero todavía no funciona.” The assistant should
respond in Spanish, acknowledge the checks and show an OPEN ticket without
immediately repeating the physical instructions. Ticket number and current
status also appear in the context panel. No visit or repair is promised.

The diagnostic engine and ticket services control measurements, escalation,
state transitions and duplicate prevention independently of language or AI.
Technical assessments and ticket summaries use English. A bounded data migration
translates known generated historical technical phrases, preserving original
customer messages and unrecognized free-form notes.

## API and session contracts

- `GET /api/health/`: public health check, `{ "status": "ok" }`.
- `POST /api/chat/`: send `message` and **either** `service_id` for a new chat
  **or** `conversation_id` to continue. Optional `language` is an explicit
  override. Omit it during ordinary adaptive continuation.
- `GET /api/conversations/<id>/messages/`: authorized history, up to 50 messages.
  Use returned `next_before` as `?before=<id>` for older pages. Responses include
  protected photo references, diagnostics, guide references and current tickets.
- `GET /api/instructions/?language=en` (or `es`): replaceable guide catalog.
- `GET /api/instructions/<id>/`: authorized SVG image, private/no-store.
- `POST /api/conversations/<id>/photos/`: multipart `photo`, JPEG or PNG only.
- `GET /api/conversations/<id>/photos/`: authorized photo metadata list.
- `GET /api/photos/<uuid>/` and `/content/`: authorized metadata and image.
- `GET /demo/state/`: selected service, conversation, confirmation and timezone.
- `POST /demo/language/`: confirm initial `language=en` or `es` using CSRF.
- `POST /demo/session/`: select a verified fictional `service_id` using CSRF.

Web access uses Django login cookies plus a server-side, operator/service-scoped
DemoChatSession that expires after one hour. Starting a browser chat without
language confirmation is rejected server-side. Selecting another service revokes
the previous demo session. Demo routes/authentication are disabled outside
DEBUG development/test. CSRF remains enabled for all cookie-based writes.

The existing CLI header flow remains compatible. Issue a short-lived scoped
token locally (treat its output as a credential; never commit or embed it):

```powershell
.\.venv\Scripts\python.exe manage.py create_demo_session DEMO-SERVICE-001 --operator YOUR_STAFF_USERNAME
```

Use the returned token in `Authorization: Demo <token>` for CLI API requests.
Browser confirmation requirements do not alter this existing CLI contract.
Internal diagnostic routes retain their staff permissions and do not accept
demo customer tokens. There are no public customer/ticket modification routes.

## Photos and OpenAI

Upload only fictional or authorized equipment photos, without passwords or
personal information. Start a conversation before attaching a photo. The server
checks real file format, a 5 MiB limit, dimensions (4096 per side / 12 megapixels),
corruption and animation. Pillow normalizes images to JPEG and removes EXIF.
Private files stay under `private_media/`, excluded from Git and never served by
a public media route. Cross-service access is rejected for history and photos.
Arbitrary remote image URLs are not accepted.

DemoAI requires no API key and explicitly labels simulated photo results. A
photo never confirms connectivity or electrical safety and cannot execute
commands, change accounts or authorize ticket transitions.

For optional backend-only OpenAI mode, set `AI_PROVIDER=openai`,
`OPENAI_API_KEY`, `OPENAI_MODEL` and `OPENAI_VISION_MODEL` in `.env`. Use models
available to your account with the required structured output and image-input
capabilities. No real API calls are made during automated tests. The adapter
uses the official Responses API with validated structured output, store=False,
a timeout and no automatic retries or tools. See the official
[structured outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).

Real text and image calls incur model/token-dependent charges; image detail and
resolution affect cost. Check current [OpenAI pricing](https://openai.com/api/pricing/)
and configure account budget limits before enabling paid mode. Missing keys,
unsupported models, quota/rate limits, timeouts, refusals, incomplete output and
upstream failures produce safe errors rather than network actions. Review the
conversation before manually retrying an uncertain operation: the server may
already have saved the message or photo. The widget never automatically repeats
writes, but exactly-once delivery across tabs/network failures is not guaranteed.

Development `.env` loading uses python-dotenv with override=False; existing
process variables win. `.env`, database files, `.venv`, private images and logs
are ignored by Git. Configure a persistent secret key for a stable local session;
production requires an explicit key and DEBUG=False. PostgreSQL is supported
through the database environment configuration; install its driver only when
actually switching. Do not enable demo access on a production deployment.

## Replace the instructional catalog

Catalog definitions are in `conversations/instructions.py`; original SVG assets
are in `conversations/instruction_assets/` and released as CC0-1.0 demo artwork.
Each reference includes guide ID, step number, equipment type, vendor/model
compatibility, safe asset path, English/Spanish descriptions, alternative text,
safety instructions, source and license. These generic assets do not assert
port assignments, voltages or LED meanings for unknown equipment.

Replace catalog entries/assets with authorized, model-accurate ISP material
without changing the orchestrator or diagnostic rules. Keep IDs stable when
replacing an existing asset. New formats need an explicit safe content-type
allowlist in the protected endpoint. Cards remain readable when images fail;
click/tap an image to enlarge it in an accessible dialog, close with the button
or Escape. All text uses textContent, not HTML injection; images use authorized
fetch and revocable Blob URLs. Bootstrap 5.3.8 CSS is vendored locally with MIT
license and does not require a CDN, npm, React or a frontend build step.

## Technical administration

Open **http://127.0.0.1:8000/admin/**. The widget's Technical panel filters OPEN
tickets. Ticket forms include customer, service, priority, status, assigned
technician, event history and links to the conversation and diagnostics. Assign
appropriate Django view permissions for Ticket, TicketEvent, Customer,
InternetService, Conversation, Message and DiagnosticRun. Changes require the
corresponding change permissions; closing tickets retains its specific business
authorization. Operator permission alone does not grant technical Admin access.

## Verification

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test
node --check conversations/static/conversations/demo.js
node --test tests/frontend.test.cjs
```

Node is optional and used only for dependency-free JavaScript tests. Python
requirements remain unchanged. Tests cover bilingual preference/adaptation,
ambiguous text, guide ordering, ticket flow, scoped history, CSRF, permissions,
private photographs, invalid formats/size limits and provider failures. Browser
verification covers welcome, guides, image zoom, refresh and desktop/mobile
layouts; evidence is stored in `docs/day5/`.

## Future production identity flow — documentation only

1. A customer opens the chatbot on the ISP website.
2. The ISP customer portal authenticates them, or a registered phone number is
   verified with a short-lived SMS OTP through an approved identity workflow.
3. Django resolves only the customer's authorized services.
4. The customer selects a service if multiple services are available.
5. Personalized support starts with scoped conversation access.

A phone number alone must never expose private customer information. No real OTP
or SMS is implemented: the ISP database and provider contracts are not known.

Remaining work includes broader bilingual phrasing evaluation, live-account
OpenAI validation, actual device/browser testing, equipment-specific authorized
photos, production identity, retention policy and cost/rate controls. Original
customer text is preserved. This remains a local demo, not production software.
Day 6 development has not started.

Conversational context fixes, effective provider inspection, test results and
manual reproduction: [verification report](docs/day5/conversational-context.md).
