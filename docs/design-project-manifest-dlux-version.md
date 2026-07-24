# Design: baked DjangoLux version in the project release manifest

Status: **implemented** in composer v1.2.3, DjangoLux v1.5.4, and this project. The badge only renders once the project pins `django-lux>=1.5.4`; on 1.5.3 the field is emitted and simply ignored.

## Naming (confirmed against the code)

`baked_dlux_version`, not `dlux_version`. DjangoLux already separates the two concepts on `DluxUpdateState`:

- `baked_version` — from `get_baked_version()`, documented as *"the immutable image version captured before runtime activation"*. A property of the image.
- `active_version` — from `dlux.__version__`, what the volume-based updater has activated. Changes at runtime.

The manifest describes an image, so the baked value is the correct one, and the name matches the existing `dlux_update_baked_label` ("baked dlux") UI string.

## What already exists

The value largely reaches the dialog already, but never arrives as a displayable fact:

1. composer `check_availability` writes `entry["version"]` from the plain version label and `entry["manifest"]` from the base64 manifest label.
2. dlux `image_update_target()` computes `runtime_target = version_target or digest_target` and `target = manifest.version or runtime_target`.
3. `dlux/views/updater.py:78` exposes **only** `image_metadata["target"]` as `image_update_target`. `runtime_target` is used solely to stamp `target_version` on the history row (`image_update.py:314`).

So the candidate image's baked DjangoLux version is computed and then dropped before the UI. Three gaps:

- It never reaches the template.
- It is conflated with a digest fallback (`version_target or digest_target`), so a consumer cannot tell a version from a truncated digest.
- It depends on per-project `COMPOSER_VERSION_LABEL` wiring pointing at the slug-specific label.

A badge in the wanted style already exists at `dlux/templates/dlux/includes/options.html:280`, but it renders `dlux_update_state.baked_version` — the **currently running** image, not the candidate. The new badge is the same pattern applied to the update target.

## Change

Carry the value in the manifest so it is self-describing, and render it beside the project version.

### 1. Manifest field, CI-injected

```json
{
  "schema_version": 1,
  "version": "0.1.1",
  "baked_dlux_version": "1.5.3",
  "summary": "…",
  "highlights": ["…"],
  "release_url": "https://…"
}
```

The committed `release-manifest.json` does **not** contain it. `tools/validate_project_release_manifest.py` resolves the `django-lux` pin from `requirements.txt`, injects it into an in-memory copy, and base64-encodes that as the `label` output. The manifest is hand-authored while the baked version is a build-time fact; injecting removes any chance of the two disagreeing.

This also retires the `grep -oiE 'django-lux…' requirements.txt` step duplicated in every project's release workflow — the validator resolves the pin once, in tested Python, and emits it for both the label and the `DLUX_BAKED_VERSION` build arg. Fail the release if the pin cannot be resolved.

`dlux.utils.get_project_version()` is unaffected; it reads only `version` from the on-disk file.

### 2. Two whitelists must pass it through

Both normalizers drop unknown keys, so the field is inert until each is updated:

- `app-composer` — `composer/watcher.py:83-103` (`_release_manifest_from_label`)
- `pkg-django-lux` — `dlux/updater/image_update.py:111-131` (`_normalize_project_manifest`)

Validate as a string, `strip()`, cap at 32 chars to match `DluxUpdateState.baked_version`.

`schema_version` stays `1`. Both normalizers reject anything other than `1`/`"1"` outright, so bumping it would make deployed readers discard the manifest and lose the review dialog entirely. The field is additive under schema 1.

### 3. Expose and render

- `image_update_target()` returns `manifest.get("baked_dlux_version")` as its own key, distinct from `runtime_target` so it is never confused with the digest fallback.
- `dlux/views/updater.py` passes it into template state alongside `image_update_target`.
- The update dialog renders it as a badge next to the project version, reusing the markup and `dlux_update_baked_label` string from `options.html:280`.
- Absent field → omit the badge. Old images and old manifests must degrade silently.

## Non-goals

- **The preflight version gate is untouched.** `VersionGateMixin` keeps reading its plain string label. It is intentionally generic (defaults to OCI `org.opencontainers.image.version`, guards non-DjangoLux projects), and the manifest normalizer has many paths that return empty — sourcing the gate from it could silently disable the guard against recreating onto an older image.
- Image-update **completion** verification keeps comparing `runtime_target` against baked DjangoLux. Switching that to the manifest is a separate change with its own risk.
- Renaming the slug-specific baked label to a generic one, and adding the release pipeline to `dlux/scaffold_templates/` (it currently templates neither the manifest, the validator, nor the workflow). Both are real boilerplate, but independent of this.

## Rollout order

1. `app-composer`: add `baked_dlux_version` to the label whitelist. Ship first so emitters have a reader.
2. `pkg-django-lux`: whitelist passthrough, expose from `image_update_target()`, badge in the dialog.
3. Projects: validator injects the field and emits the build arg; drop the workflow `grep`. `project-dlux-control` first, then `project-decrees`.

## Open question

Should composer warn when `manifest.baked_dlux_version` disagrees with the plain version label? They come from the same CI value, so a mismatch means a broken build pipeline — worth surfacing, but it is a new failure mode to design.
