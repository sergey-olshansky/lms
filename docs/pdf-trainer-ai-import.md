# AI review and standard parser fallback for PDF trainer import

Every import attempts AI review, including legacy API requests with `use_ai=0`.
The template parser runs first. For recognised PDFs, one compact AI audit receives
the processed questions, shared context and a boolean indicating answer presence.
It checks completeness and independent understandability, never answer correctness;
the answer contents are not transmitted in this audit. Passed questions are reused.
Embedded source images are reported as preserved crop content, so a diagram absent
from selectable text is not treated as missing when it exists in the original crop.

If parsing fails or any question fails review, a planning request receives all
selectable PDF text once, labelled with original page numbers. It returns the task
count and question/context/answer pages for each task. Each remaining task is then
extracted in a separate request containing only those planned pages. Passed parser
questions are not extracted again. Printed answers are copied, never solved or
verified for subject-matter correctness. Existing parser answers are retained unchanged
when repairing question layout. Missing answers stop import.
Page numbers, task identities, plan counts and source anchors are validated locally.
There is no draft step or Force AI switch. Optional guidance is limited to 1000
characters. PDFs over 30 pages and image-only PDFs are not supported.

Imports run as background jobs with owner-scoped status and retry idempotency.
The default queue is `long`; `LMS_PDF_IMPORT_QUEUE` or `pdf_import_queue` can select
another configured worker queue. A worker must consume that queue.

Each question includes all of its shared instructions and referenced lists or
tables, followed by the task itself. AI can select template regions or add
missing fragments by exact page/text anchors. Local code verifies the regions
and renders the original PDF formatting; it refuses an unlocatable fragment
instead of guessing a whole-page crop. Extracted text is used as image alt text,
so it does not visibly duplicate the source image. PDF page images are rendered
locally, not sent to the model. This review checks textual structure and source
regions; it is not visual inspection of rendered pixels by a vision model.

Unordered selection tasks become LMS Choices questions. A task requiring order
keeps its exact sequence as a text answer. Numeric digit sequences are graded
exactly (whitespace is ignored, digit order is preserved); other text retains
the normal typo tolerance. Source instructions provide a local
guard against a model dropping the order requirement. Errors create no partial
quiz and keep the private upload for the dialog's Retry import action.

The request uses Z.AI's OpenAI-compatible chat completions endpoint with
`glm-5.3` and `reasoning_effort: max`. Responses are streamed to avoid idle
connections during model reasoning; only the completed JSON result is accepted. The default endpoint is the GLM Coding
Plan endpoint; set `ZAI_BASE_URL` to override it where appropriate.

Configure these values in the LMS backend runtime environment or its private
Frappe site configuration:

- `ANTHROPIC_AUTH_TOKEN` or `ZAI_API_KEY` (or private site config key
  `anthropic_auth_token` or `zai_api_key`) — required secret.
- `ZAI_MODEL` (or `zai_model`) — defaults to `glm-5.3`.
- `ZAI_BASE_URL` (or `zai_base_url`) — defaults to
  `https://api.z.ai/api/coding/paas/v4`.

The `tutor-infra` repository's `preprod` and `production` GitHub Environments
own encrypted `ZAI_API_KEY` secrets. Their deployment workflows write the value
to the relevant private site's `site_config.json` over SSH stdin. Never commit
the key, put it in the frontend, print it in logs, or expose it as a workflow
artifact. The production secret is used only by the production deployment
workflow.

## Local sessions

Use a dedicated hostname (for example `localhost:8001`) for the isolated local
feature server when other checks use `127.0.0.1`. Browser cookies are shared
across ports on the same hostname. A login performed by another local check can
therefore replace the session and invalidate the already rendered CSRF token.

The import dialog obtains a fresh session token through the authenticated,
non-cacheable GET endpoint `get_import_session` before private uploads and job
creation. Status polling uses GET. CSRF validation and instructor permissions
remain enforced. A dedicated hostname still requires its own normal login.

## AI service outages

Missing service configuration, network/HTTP failures, interrupted streams and
unreadable JSON are classified as service failures. If the original template
parser recognised the PDF and all its questions have valid source regions and
answers, import continues with that original parser output. The result explicitly
sets `used_ai: false` and includes a warning displayed in the import summary and
a toast. Shared context crops and ordered text answers are retained.

Unknown formats and incomplete parser output cannot use this fallback. Semantic
validation failures are not silently treated as service outages. No draft or
extra confirmation is introduced.

## Restarted numbering and partial AI reviews

Recognised documents can contain several sections whose printed task numbers
restart. The import assigns stable sequential IDs only when printed numbers
repeat, while keeping the original source numbers, unique parser keys and answer
associations. Task ranges apply to stable IDs. Crop checks compare the original
printed number, not its global import position. This is shared handling for all
parser formats, with no PDF filename checks or new layout template.

A partial or malformed audit retains unambiguous individual verdicts and moves
the other tasks to the page-planning route. The model receives the stable task
index, printed number and source page along with all page text once. A partial
audit alone does not bypass AI or require a new template.
