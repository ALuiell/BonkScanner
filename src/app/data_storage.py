"""Application-facing access to the installed-build data-storage service."""

from infra.data_storage import (
    MigrationActionResult,
    StorageContext,
    cancel_migration,
    legacy_data_exists,
    migration_status,
    remove_legacy_data,
    request_migration,
)

from infra.shared_storage import request_shared_folder
from infra.edition import CONFIG_FILE_NAME

__all__ = [
    "CONFIG_FILE_NAME",
    "request_shared_folder",
    "MigrationActionResult",
    "StorageContext",
    "cancel_migration",
    "legacy_data_exists",
    "migration_status",
    "remove_legacy_data",
    "request_migration",
]
