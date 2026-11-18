"""The column type that stores a `JobPayload`: the record of the job's type, as binary JSON."""

from __future__ import annotations

from typing import Any

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from songmaker_cli.job_payloads import JOB_PAYLOAD_ADAPTER, JobPayload


class JobPayloadColumn(TypeDecorator[JobPayload]):
    """JSONB column holding a `JobPayload`; no payload is SQL NULL, never JSON `null`.

    A read validates the stored JSON against the record its `job_type` names, so a row that
    holds anything else fails loud instead of reaching a worker as loose values.
    """

    impl = JSONB(none_as_null=True)
    cache_ok = True

    def process_bind_param(self, value: JobPayload | None, dialect: Dialect) -> Any:
        return None if value is None else JOB_PAYLOAD_ADAPTER.dump_python(value, mode="json")

    def process_result_value(self, value: Any, dialect: Dialect) -> JobPayload | None:
        return None if value is None else JOB_PAYLOAD_ADAPTER.validate_python(value)
