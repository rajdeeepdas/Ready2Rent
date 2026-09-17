"""
Storage selection.

- Local development and tests: uploads on the local filesystem (MEDIA_ROOT).
- Production: a PRIVATE Supabase Storage bucket through its S3-compatible API.

Access control does not depend on the storage: files are never served by URL. Every download
goes through the authenticated, ownership-checked Django views, which read the object with the
server-only S3 keys and stream it back.
"""


def build_storages(*, debug: bool, s3: dict | None) -> dict:
    """
    Return Django's STORAGES setting.

    `s3` is None for local storage, or a dict with endpoint_url, region_name, access_key,
    secret_key, bucket_name for Supabase Storage.
    """
    staticfiles = {
        # Hashed, compressed static files in production (collectstatic runs at build time).
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        if debug
        else "whitenoise.storage.CompressedManifestStaticFilesStorage"
    }

    if not s3:
        return {
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": staticfiles,
        }

    missing = [k for k in ("endpoint_url", "region_name", "access_key", "secret_key", "bucket_name") if not s3.get(k)]
    if missing:
        from django.core.exceptions import ImproperlyConfigured

        raise ImproperlyConfigured(f"Supabase Storage is partly configured; missing: {', '.join(missing)}")

    from botocore.config import Config

    return {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "bucket_name": s3["bucket_name"],
                "endpoint_url": s3["endpoint_url"],
                "region_name": s3["region_name"],
                "access_key": s3["access_key"],
                "secret_key": s3["secret_key"],
                # Supabase requires path-style addressing and SigV4. Recent boto3 releases add
                # optional checksums by default, which S3-compatible services may reject, so
                # checksums are only sent when an operation requires them.
                "client_config": Config(
                    signature_version="s3v4",
                    s3={"addressing_style": "path"},
                    request_checksum_calculation="when_required",
                    response_checksum_validation="when_required",
                ),
                # Two uploads with the same name (e.g. two "other" documents called scan.pdf)
                # must not overwrite each other; Django appends a suffix instead.
                "file_overwrite": False,
                # The bucket stays private: no ACL is sent, and any URL the library might
                # build is signed and short-lived. The app itself never hands out file URLs.
                "default_acl": None,
                "querystring_auth": True,
                "querystring_expire": 60,
            },
        },
        "staticfiles": staticfiles,
    }
