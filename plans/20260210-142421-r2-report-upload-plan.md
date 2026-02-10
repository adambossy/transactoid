# R2 Report Artifact Uploads (Generic Utility + Report Integration)

## Summary
Implement a reusable Cloudflare R2 upload utility and wire it into the report job so successful runs upload artifacts to bucket `transactoid-runs`, using keys organized by type folder:

- `report-md/<ts>-report-md`
- `report-html/<ts>-report-html`

## Scope
- Add generic R2 storage function(s).
- Integrate report job to upload both markdown and HTML outputs.
- Preserve existing email behavior.
- No DB/schema changes.

## Design Decisions Locked
- Client: `boto3` (S3-compatible R2).
- Env vars:
  - `R2_ACCOUNT_ID`
  - `R2_ACCESS_KEY_ID`
  - `R2_SECRET_ACCESS_KEY`
  - `R2_BUCKET` (`transactoid-runs`)
- Key format:
  - `<type>/<ts>-<type>`
  - concrete types:
    - `report-md`
    - `report-html`
- Timestamp format: UTC sortable string, e.g. `20260210T033800Z`.

## Public API / Interface Additions
1. New module: `src/transactoid/adapters/storage/r2.py`
2. Types:
   - `R2Config`
   - `R2StoredObject`
3. Exceptions:
   - `R2StorageError`
   - `R2ConfigError`
   - `R2UploadError`
4. Functions:
   - `load_r2_config_from_env() -> R2Config`
   - `store_object_in_r2(*, key: str, body: bytes, content_type: str, metadata: dict[str, str] | None = None, config: R2Config | None = None) -> R2StoredObject`

## Implementation Details
1. Add dependency: `boto3` to `pyproject.toml`.
2. Build R2 client with:
   - endpoint: `https://{account_id}.r2.cloudflarestorage.com`
   - region: `auto`
   - sigv4
3. Report integration:
   - After report generation and HTML rendering:
     - upload markdown with key `report-md/<ts>-report-md`, content type `text/markdown; charset=utf-8`
     - upload HTML with key `report-html/<ts>-report-html`, content type `text/html; charset=utf-8`
   - Record uploaded keys in metadata/log output.
4. Error policy:
   - Upload failure fails the report job with clear wrapped error.

## Test Cases
1. Config loading:
   - success with all env vars
   - missing each required var (parameterized)
2. Upload utility (mock boto3):
   - correct endpoint/credentials
   - expected `put_object` args
   - error wrapping behavior
3. Report integration:
   - successful run attempts two uploads with exact key pattern
   - upload failure propagates as job failure
4. Key formatting:
   - exact format `<type>/<ts>-<type>` for both artifact types
   - no extension suffix in key (per requested pattern)

## Assumptions / Defaults
- Type tokens are fixed: `report-md`, `report-html`.
- Timestamp precision to seconds is sufficient.
- Bucket `transactoid-runs` exists and credentials have write access.
