# AI fallback for PDF trainer import

The regular PDF parser runs first. If it cannot recognize a trainer, the LMS
keeps the private upload and offers **Send to Z.AI and create quiz**. Clicking
that button sends rendered page images to Z.AI and immediately creates the quiz
from the returned questions and answers. There is no draft step. PDFs over 30
pages are not sent.

The import dialog also has a **Force AI** checkbox for PDFs that use a supported
quiz structure but an unfamiliar layout. When checked, each uploaded PDF skips
format detection and is sent directly to Z.AI; the quiz is created immediately.

The request uses Z.AI's Anthropic Messages-compatible endpoint and
`glm-5.3-flash`. The authenticated key must be a GLM Coding Plan key because
Z.AI manages Coding Plan keys separately from standard model API keys.

Configure these values in the LMS backend runtime environment or its private
Frappe site configuration:

- `ANTHROPIC_AUTH_TOKEN` or `ZAI_API_KEY` (or private site config key
  `anthropic_auth_token` or `zai_api_key`) — required secret.
- `ZAI_MODEL` (or `zai_model`) — defaults to `glm-5.3-flash`.
- `ANTHROPIC_BASE_URL` (or `anthropic_base_url`) — optional; defaults to
  `https://api.z.ai/api/anthropic`.

The `tutor-infra` repository's `preprod` and `production` GitHub Environments
own encrypted `ZAI_API_KEY` secrets. Their deployment workflows write the value
to the relevant private site's `site_config.json` over SSH stdin. Never commit
the key, put it in the frontend, print it in logs, or expose it as a workflow
artifact. The production secret is used only by the production deployment
workflow.
