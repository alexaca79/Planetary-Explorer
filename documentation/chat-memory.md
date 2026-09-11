---
title: Chat history and memory
description: Configure private saved-chat recall and bounded long-conversation context in Planetary Explorer
ms.date: 2026-09-11
ms.topic: how-to
---

## Recall earlier context

On the [deployed application](https://app-earthcopilot-e1bb5a9c.azurewebsites.net),
select **Sign in** to save and restore your own chats. Public map use remains
available without sign-in; anonymous visitors do not share a history archive.

Chat memory combines the most recent six messages with relevant older excerpts.
It keeps the original wording instead of generating a summary that might change
dates or measurements. The current question, current map and pin, and newer
corrections take precedence. Remembered assistant answers are not new tool results
or authorization to repeat a billed action.

With saved history configured, the chat can also recall relevant excerpts from
your other saved sessions. **Recalled context** beneath an answer lists the
source chats supplied to the model. Open a source to inspect its transcript.
This indicates context supplied, not proof that the model used every excerpt.

Use the **Memory** switch to control extended recall and whether the current
saved chat can become a future memory source. When it is off, normal recent-turn
context remains available. In **History**, search session titles and change
**Include in memory** for individual sessions. Excluding a session keeps its
transcript and files; deleting it removes the saved session and its Search keys.

## Try the workflows

For a same-chat check:

1. Send `For this comparison, our Thunder Bay baseline is June 1, 2026.`
2. Continue with several other questions.
3. Ask `Which Thunder Bay baseline did we choose earlier?`
4. Check that the answer recalls June 1, 2026, without claiming a new measurement.
5. Correct the baseline with `Use July 1, 2026 instead of June 1, 2026.`
6. Ask again and check that the newer correction wins.

For a cross-chat check, keep Memory on, wait for **Saved**, start another chat,
and ask `What baseline did we choose for Thunder Bay in the previous chat?`
Inspect **Recalled context**, then exclude the original session in History and
repeat from a fresh chat. The excluded transcript must no longer be recalled.
Text copied into another transcript remains part of that other transcript.

## Configure saved history

The existing archive uses Cosmos DB for transcripts and private Blob Storage
for attachments. Use one of these deployment paths:

* For an authenticated API with network access to its stores, the canonical
	Bicep deployment supplies Cosmos, Blob and dedicated memory Search settings.
* For an existing public API without VNet integration, use the
	[private history upgrade](deployment.md#add-private-history-to-an-existing-public-app).
	The API forwards validated user tokens to a separate CPU history service,
	which validates them again and accesses the private data endpoints.

The service that owns the stores uses these settings:

| Setting                       | Value or purpose                                    |
|-------------------------------|-----------------------------------------------------|
| `CHAT_HISTORY_STORE`          | `cosmos` for durable history                         |
| `COSMOS_CHAT_ENDPOINT`        | Existing Cosmos DB account endpoint                  |
| `COSMOS_CHAT_DATABASE`        | Defaults to `planetary-explorer`                     |
| `COSMOS_CHAT_CONTAINER`       | Defaults to `chat-history`, partitioned by `/ownerId` |
| `CHAT_ARTIFACT_STORE`         | `blob`                                               |
| `CHAT_ARTIFACT_BLOB_ENDPOINT` | Existing storage account Blob endpoint               |
| `CHAT_ARTIFACT_CONTAINER`     | Defaults to `chat-artifacts`                         |
| `PE_FEATURE_CHAT_HISTORY`    | `true`; defaults on when a history store is selected |
| `PE_FEATURE_CHAT_MEMORY`     | `true` by default; `false` disables extended recall  |

In remote mode, the public API instead uses `CHAT_HISTORY_STORE=remote`,
`CHAT_ARTIFACT_STORE=remote`, `CHAT_HISTORY_REMOTE_URL=https://<history-host>`,
and `PE_FEATURE_CHAT_HISTORY=true`. The URL must be an operator-configured
HTTPS origin, not a user-supplied proxy target. Both services require the same
validated tenant and application audience. The frontend receives
`historyRequiresSignIn=true` and only enables archive operations after sign-in.

Requests use the owner derived from validated sign-in claims. Do not enable
`CHAT_HISTORY_ALLOW_ANONYMOUS` in a shared deployment. Its `local-development`
owner is for an isolated local process only. `CHAT_HISTORY_STORE=memory` and
`CHAT_ARTIFACT_STORE=memory` are development stores and lose data on restart.

## Enable Azure AI Search

The authenticated direct-history Bicep path creates a dedicated Basic Search
service when `DEPLOY_CHAT_HISTORY=true` and `DEPLOY_CHAT_MEMORY=true` (defaults).
The additive private-history template also creates a dedicated service. Neither
path changes catalog or document indexes. The memory index is initialized by the
history service using managed identity and `CHAT_MEMORY_AUTO_SETUP=true`.

`CHAT_MEMORY_SEARCH_LOCATION` optionally selects an available region for the
canonical template. The additive template uses `searchLocation`. The September
11 deployment used East US after East US 2 rejected a Basic allocation for
regional capacity. Compilation and advertised quotas do not reserve capacity.

No embedding deployment is required. Full-text ranking is the deployed default;
semantic ranking is optional and requires a service with semantic ranker enabled.
For an operator-managed compatible service, manual schema setup is also available.

Run these commands from the repository root. The first command only prints the
index schema and makes no Azure requests:

```powershell
python planetary-explorer/container-app/setup_chat_memory.py --index-name chat-memory-v1
```

Set `CHAT_MEMORY_SEARCH_ENDPOINT` to the dedicated Search endpoint.
`AZURE_SEARCH_ENDPOINT` is a legacy fallback, not required for the dedicated
service. The identity needs Search Index Data Contributor and, for automatic
schema initialization, Search Service Contributor at that dedicated service's
scope. The Bicep templates disable local keys and use managed identity. Keep
existing catalog credentials separate and never place credentials in a chat.

Creating the index is an explicit Azure write:

```powershell
python planetary-explorer/container-app/setup_chat_memory.py --index-name chat-memory-v1 --apply
```

The command creates a missing index or validates an existing compatible one.
It does not replace an existing index. Set the backend configuration and restart
or redeploy it through your normal deployment process:

```powershell
$env:CHAT_MEMORY_SEARCH_INDEX = "chat-memory-v1"
$env:CHAT_MEMORY_SEMANTIC_CONFIGURATION = "chat-memory"
```

Omit `CHAT_MEMORY_SEMANTIC_CONFIGURATION` to use full-text ranking without the
optional semantic ranker. The variables above affect the current PowerShell
process only; hosted deployments need the same settings on the backend service.

## Storage and failure behavior

Each saved message produces an owner-scoped Search document containing sanitized
text, title, position, timestamp, and a fingerprint. Attachments, map screenshots,
and raw tool payloads are not indexed. Search queries always filter by owner.
Each hit is checked against the caller's current canonical transcript before
its content reaches the model. Deleted, excluded, or changed source turns are
discarded even if the index is stale.

Without Search, on a Search failure, or before older chats have been indexed,
recall searches at most the twelve most recent saved sessions. Existing sessions
are indexed on their next save; this fallback is not an exhaustive archive scan.
At most four saved-message excerpts are recalled per request. Conversation
context has an 18,000-character JSON budget; saved excerpts have an additional
8,000-character budget. Indexed message text is capped at 6,000 characters.

Saved recall has a five-second service budget, including a three-second Search
budget; the remote API proxy allows six seconds for transport and service work.
Current-chat context remains available when saved recall is unavailable.
An indexing failure does not undo a committed transcript save; the next save
retries indexing. Deletion first marks the session unavailable to recall, then
removes Search entries and files. Failed cleanup returns an error and remains
retryable rather than reporting success prematurely.

## Run local checks

```powershell
Push-Location planetary-explorer/container-app
python -m pytest tests/test_chat_memory.py tests/test_chat_memory_search.py tests/test_chat_memory_integration.py tests/test_chat_history_api.py tests/test_chat_history_store.py tests/test_setup_chat_memory.py -q
Pop-Location
python scripts/verify_documentation.py
```

These checks use local fixtures. They verify context assembly, tenant isolation,
streamed and buffered query plumbing, exclusion, stale-hit rejection, and schema
compatibility. They do not certify a live Search index, production model answers,
private data access, or a deployed release.

For local browser checks, start an isolated backend and frontend on loopback
ports, with temporary `memory` history/artifact stores and local-development
anonymous history enabled. Do not enable that anonymous mode on a shared server.
The verifier creates its own test sessions and deletes those sessions afterward:

```powershell
node scripts/verify_chat_memory.mjs --base-url http://127.0.0.1:5187 --api-url http://127.0.0.1:8026
node scripts/verify_get_started_gallery.mjs --base-url http://127.0.0.1:5187
```

For deployed checks, use an application-scoped signed-in user token in
`PLANETARY_EXPLORER_ACCESS_TOKEN`, never a Graph or management token. Do not
print it. The browser verifier uses real App Service token login and real API
requests; it does not mock sign-in or saved responses. Refresh the token before
a long matrix and keep failure reports if it expires during a run.

`verify_chat_memory.mjs` requires `--allow-production` and `--release-args` for
remote origins. The latter is a private JSON array of the canonical verifier's
exact revision, digest, frontend bundle, tenant and resource arguments. See the
[canonical verifier](../scripts/verify_get_started_scenarios.py) (`--help`)
for those binding arguments.
`verify_get_started_image_analysis.mjs --with-history` adds authenticated
save/restore checks to the real imagery/pixel assertions. These checks delete
only their own fixtures and may incur ordinary model/API usage charges.

## September 11 deployed verification

The API, frontend and private CPU history service were deployed. Cosmos, Blob
and memory Search public networking remain disabled; local/shared-key access is
disabled, and all three new private endpoints are approved. The history identity
has container-scoped Cosmos/Blob access, two roles on its dedicated Search
service, and AcrPull on the existing registry. No peer-service release changed.

| Check | Result |
| --- | --- |
| Live history and memory | Anonymous rejection; durable save/read; older same-chat and Search-backed cross-chat model recall; attachment export; exclusion; deletion passed |
| History browser controls | Restore, title filtering, exclusion, memory persistence, source metadata and deletion passed at 1440, 390 and 320 pixels |
| Canonical Setup matrix | 30 passed; 2 MPC Pro prerequisites blocked; 30 history round trips |
| Canonical analysis matrix | 27 passed; 2 MPC Pro and 3 Fabric prerequisites blocked; 39 history round trips |
| Real Image Analysis | 12 passed with tile, pixel-change, pin, provenance and history checks; 2 private Building Damage examples blocked |
| Web Search and Code Interpreter | Real search and completed managed Python execution; restored the saved search transcript before calculation; printed numbers independently verified |
| CPU NBR worked example | Actual May 31/September 6 scenes at the BC pin; before-minus-after `+0.004226744`; saved transcript restored |
| GeoFM | Connected model, real preflight, exact approval arguments, explicit denial and restored denial transcript passed; no GPU approval sent |

The first browser image matrix stopped when its verifier token expired. Its ten
completed passes were retained, the leftover fixture was deleted after token
refresh, and the two remaining radar cases passed against the unchanged release.
The initial CPU attempt hit model quota before tool execution; a bounded retry
with the correct pin field and the other existing model deployment passed.
All verification fixtures were cleaned up.

MPC Pro imagery and populated Fabric Site Intel data remain prerequisites, not
successful analyses. No new billed GeoFM result or private artifact download is
claimed. The September 9 completed GPU run remains historical evidence. A second
live user was not available; cross-user isolation is covered by automated tests,
not a two-account production exercise. Successful tool execution does not certify
the scientific interpretation of imagery.

The current API is `ca-earthcopilot-api--history-executor-0911`, image digest
`sha256:1f5f313e3f40c24a792abbb8e36f68a146205fac88be548c4158120494b43aa6`.
Frontend deployment `9adce019-bc4e-48be-942f-0decb38ead6a` serves
`index-BHgg9cCg.js`, SHA-256
`af5a63f539c932be3eadd1d773395ee40f5f4d9b870fcc8dee62eee7e6e09444`.
Operator evidence is retained privately under `.azure/history-release/`; do not
publish raw settings snapshots or authentication responses.

## September 10 verification

The following checks ran against the local memory implementation, not a new
Azure deployment:

| Check                                      | Result                                               |
|--------------------------------------------|------------------------------------------------------|
| Complete backend suite                     | 1,462 passed; 1 existing skip                         |
| Complete frontend suite                    | 218 passed                                           |
| Documentation and example helper suite     | 149 passed; 9 skipped for unavailable shell tooling   |
| Image-analysis verifier contracts          | 16 passed                                            |
| Production host and Vite deployment tests  | 2 passed                                             |
| Markdown links, images, and local anchors   | 38 files; 0 reference errors                          |
| Get Started source contracts               | 32 scenarios across 11 families                       |
| Memory and history browser workflows       | Passed at 1440, 390, and 320 pixels                    |
| Gallery layout and keyboard workflows      | Passed at the same three viewport widths              |
| Public catalog summer scene-footprint scan | 136 covered; 17 snow-collection no-data results        |
| Snow collection using February 2025 dates  | All 17 Canadian points covered                        |

The browser memory check exercised real local save, restore, exclusion, setting
persistence, source metadata, and deletion APIs with fixture transcripts. It
does not simulate a successful model answer. Public coverage confirms scene
footprints and dates, not usable pixels or scientific validity.

That local-only phase did not verify live model, Search, Cosmos, forecast or
private-data integrations, and did not change cloud resources. The later
September 11 results above supersede that deployment limitation, not the dated
measurements and screenshots in the [usage guide](get-started-playbook.md).