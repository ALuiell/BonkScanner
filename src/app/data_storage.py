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

__all__ = [
    "MigrationActionResult",
    "StorageContext",
    "cancel_migration",
    "legacy_data_exists",
    "migration_status",
    "remove_legacy_data",
    "request_migration",
]
