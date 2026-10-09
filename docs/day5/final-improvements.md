# Day 5 final improvements

The interface and Django Admin use US English independently of the conversation
language. The welcome screen requires explicit English/Spanish confirmation for
new browser chats; existing conversations resume without repeating the choice.
Clear language changes update the conversation, ambiguous acknowledgments retain
its language, and manual selection provides an explicit override. DemoAI and the
OpenAI adapter share a conservative language policy. Broader bilingual phrasing
evaluation and a live OpenAI account check remain future work.

The existing protected catalog now provides four ordered offline-CPE steps,
original generic SVG illustrations, bilingual text, accessible alternatives,
safety warnings, model/vendor compatibility and source/license metadata. Cards
work without assets; missing files return 404. Click/tap opens an accessible
enlargement dialog; the close button and Escape return focus to the image control.
No illustration assigns ports, voltages or LED meanings for unknown equipment.

Configuration uses LANGUAGE_CODE=en-us, USE_TZ=True and DJANGO_TIME_ZONE (UTC
default). Browser timestamps explicitly use the configured timezone rather than
the workstation timezone. New technical assessment/ticket text is English;
existing messages and free-form notes are preserved; known generated historical
technical phrases are translated by a bounded data migration. Model-choice label
migrations retain all stored enum values.

## Changed files

- `config/settings.py`, `config/urls.py`, `.env.example`
- `conversations/ai.py`, `services.py`, `api.py`, `web.py`, `replies.py`
- `conversations/instructions.py`, `media_api.py`, `instruction_assets/*.svg`
- `conversations/templates/conversations/demo.html`
- `conversations/static/conversations/demo.css`, `demo.js`, `demo-core.js`
- `customers/models.py`, `conversations/models.py`, `diagnostics/models.py`,
  `tickets/models.py`, `tickets/admin.py`, `diagnostics/engine.py`
- `conversations/test_language_ux.py`, `test_web.py`, `test_multimodal.py`,
  `tests/frontend.test.cjs`, `README.md`

New migrations:

- customers/0002_alter_internetservice_connectivity_status_and_more
- conversations/0004_alter_demochatsession_options_and_more
- conversations/0005_alter_conversation_language
- diagnostics/0003_alter_diagnosticrun_options_and_more
- diagnostics/0004_translate_technical_summaries
- tickets/0002_alter_ticket_priority_alter_ticket_status_and_more

## Validation

- 122 Django tests pass, retaining all earlier tests. The existing image test
  now asserts four ordered steps instead of three unordered thumbnails.
- 7 dependency-free JavaScript tests pass; syntax check passes.
- Django system check and migration consistency check pass.
- Browser checks cover English login, disabled Continue before selection,
  confirmation, service selection, English support, English-to-Spanish change,
  ticket escalation, refresh continuity, four-step guide order, loaded assets,
  enlargement and closing via button/Escape.
- Mobile viewport 390 × 844: no horizontal overflow (375 px content and available
  width with scrollbar). No JavaScript errors were observed in these flows.
- Photo permissions, upload validation, private storage, CSRF, conversation
  isolation, diagnostic rules and ticket authorization remain covered by the
  complete regression suite. No real API/ISP/SMS calls were made.

Evidence: welcome-desktop.jpg, welcome-mobile.jpg, guides-desktop.jpg,
guides-mobile.jpg, guide-zoom-mobile.jpg, adaptive-ticket-desktop.jpg.
Screenshots use isolated SQLite and a temporary fictional operator. The preview
server and its temporary database/credentials are removed after verification.

Production authentication is documented in the English README: customer portal
or verified registered-phone SMS OTP, server-side service authorization, service
selection, then personalized chat. A phone number alone never grants access.
No OTP implementation or Day 6 development is included.
