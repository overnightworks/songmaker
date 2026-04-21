"""ACE-Step training HTTP client — scan, preprocess, LoKR train, export.

Thin pydantic-typed wrapper over the ACE-Step training routes registered
by ``register_training_api_routes``. Endpoints live in the SAME FastAPI
subprocess that serves generation, so training and generation cannot run
concurrently on the same worker — callers must serialize externally.

Wire naming mirrors the server's request/response envelopes:
* ``/v1/dataset/scan`` -> :meth:`AceStepTrainingClient.scan_dataset`
* ``/v1/dataset/preprocess_async`` -> :meth:`start_preprocess` + :meth:`poll_preprocess`
* ``/v1/training/start_lokr`` -> :meth:`start_lokr`
* ``/v1/training/status`` + ``/v1/training/stop`` -> :meth:`poll_training`, :meth:`stop_training`
* ``/v1/training/export`` -> :meth:`export_training`
"""

from __future__ import annotations

import json
import logging
import time
from typing import Final
from urllib.error import URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError

from acestep_engine.errors import AceStepError
from acestep_engine.models import LoraTrainingConfig
from acestep_engine.settings import get_engine_settings

log = logging.getLogger(__name__)


class TrainingRequestError(AceStepError):
    """Training HTTP request failed after retries."""


class TrainingResponseError(AceStepError):
    """Training server returned an unexpected payload."""


TRAINING_SUBMIT_RETRIES: Final[int] = 3
TRAINING_SUBMIT_RETRY_DELAYS: Final[tuple[float, ...]] = (1.0, 3.0, 10.0)
TRAINING_DEFAULT_TIMEOUT_SECONDS: Final[float] = 60.0
TRAINING_STATUS_TIMEOUT_SECONDS: Final[float] = 15.0


class ScanDatasetResult(BaseModel):
    num_samples: int = 0
    dataset_json_path: str = ""
    message: str = ""


class PreprocessTaskHandle(BaseModel):
    task_id: str
    total: int = 0


class PreprocessStatus(BaseModel):
    task_id: str
    status: str = ""
    progress: str = ""
    current: int = 0
    total: int = 0
    error: str | None = None
    num_tensors: int | None = None


class TrainingStatus(BaseModel):
    is_training: bool = False
    should_stop: bool = False
    current_step: int = 0
    current_epoch: int = 0
    current_loss: float | None = None
    status: str = ""
    steps_per_second: float = 0.0
    estimated_time_remaining: float = 0.0
    error: str | None = None
    run_id: str | None = None


class TrainingStartedHandle(BaseModel):
    tensor_dir: str
    output_dir: str
    message: str = ""


class ExportResult(BaseModel):
    export_path: str
    source: str = ""
    message: str = ""


class _ScanRequestPayload(BaseModel):
    audio_dir: str
    dataset_name: str = "songmaker_lora_dataset"
    custom_tag: str = ""
    tag_position: str = "replace"
    all_instrumental: bool = False


class _PreprocessRequestPayload(BaseModel):
    output_dir: str
    skip_existing: bool = False


class _StartLoKRRequestPayload(BaseModel):
    tensor_dir: str
    output_dir: str
    lokr_linear_dim: int = Field(64, ge=1, le=256)
    lokr_linear_alpha: int = Field(128, ge=1, le=512)
    lokr_factor: int = -1
    lokr_decompose_both: bool = False
    lokr_use_tucker: bool = False
    lokr_use_scalar: bool = False
    lokr_weight_decompose: bool = True
    learning_rate: float = Field(0.03, gt=0.0)
    train_epochs: int = Field(500, ge=1)
    train_batch_size: int = Field(1, ge=1)
    gradient_accumulation: int = Field(4, ge=1)
    save_every_n_epochs: int = Field(5, ge=1)
    training_shift: float = Field(3.0, ge=0.0)
    training_seed: int = 42
    gradient_checkpointing: bool = False


class _ExportRequestPayload(BaseModel):
    export_path: str
    lora_output_dir: str


def _default_base_url() -> str:
    settings = get_engine_settings()
    return f"{settings.acestep_host}:{settings.acestep_port}"


def _unwrap_data(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise TrainingResponseError(
            f"ACE-Step training response was not a JSON object: got {type(raw).__name__}",
        )
    if "data" in raw and isinstance(raw["data"], dict):
        return raw["data"]
    return raw


class AceStepTrainingClient:
    """Training HTTP client. All methods raise :class:`TrainingRequestError`
    on retriable transport errors and :class:`TrainingResponseError` on
    malformed responses."""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        timeout_seconds: float = TRAINING_DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if host is None or port is None:
            settings = get_engine_settings()
            host = host or settings.acestep_host
            port = port or settings.acestep_port
        self.base_url = f"{host}:{port}"
        self.timeout = timeout_seconds

    def _url(self, path: str) -> str:
        return urljoin(self.base_url + "/", path.lstrip("/"))

    def _request_json(
        self, path: str, payload: dict | None = None,
        *, method: str = "POST", timeout: float | None = None,
        retries: int = TRAINING_SUBMIT_RETRIES,
    ) -> dict:
        body = json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        url = self._url(path)

        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                req = Request(url, data=body, headers=headers, method=method)
                with urlopen(req, timeout=timeout or self.timeout) as resp:
                    raw = json.loads(resp.read())
                return _unwrap_data(raw)
            except (URLError, OSError) as exc:
                last_exc = exc
                if attempt < retries - 1:
                    delay = TRAINING_SUBMIT_RETRY_DELAYS[
                        min(attempt, len(TRAINING_SUBMIT_RETRY_DELAYS) - 1)
                    ]
                    log.warning(
                        "Training request to %s failed (%s), retry in %.1fs",
                        path, exc, delay,
                    )
                    time.sleep(delay)
            except (json.JSONDecodeError, PydanticValidationError) as exc:
                raise TrainingResponseError(
                    f"Bad training response from {path}: {exc}",
                ) from exc

        raise TrainingRequestError(
            f"Training request to {path} failed after {retries} attempts: {last_exc}",
        ) from last_exc

    def scan_dataset(self, dataset_dir: str) -> ScanDatasetResult:
        payload = _ScanRequestPayload(audio_dir=dataset_dir).model_dump()
        data = self._request_json("/v1/dataset/scan", payload)
        return ScanDatasetResult(
            num_samples=int(data.get("num_samples", 0)),
            dataset_json_path=str(data.get("dataset_json_path", "")),
            message=str(data.get("message", "")),
        )

    def start_preprocess(
        self, tensor_dir: str, *, skip_existing: bool = False,
    ) -> PreprocessTaskHandle:
        payload = _PreprocessRequestPayload(
            output_dir=tensor_dir, skip_existing=skip_existing,
        ).model_dump()
        data = self._request_json("/v1/dataset/preprocess_async", payload)
        task_id = data.get("task_id")
        if not task_id:
            raise TrainingResponseError(
                f"Preprocess did not return task_id: {data}",
            )
        return PreprocessTaskHandle(
            task_id=str(task_id), total=int(data.get("total", 0)),
        )

    def poll_preprocess(self, task_id: str) -> PreprocessStatus:
        data = self._request_json(
            f"/v1/dataset/preprocess_status/{task_id}",
            method="GET",
            timeout=TRAINING_STATUS_TIMEOUT_SECONDS,
        )
        result = data.get("result") or {}
        return PreprocessStatus(
            task_id=str(data.get("task_id", task_id)),
            status=str(data.get("status", "")),
            progress=str(data.get("progress", "")),
            current=int(data.get("current", 0)),
            total=int(data.get("total", 0)),
            error=data.get("error"),
            num_tensors=(
                int(result["num_tensors"]) if isinstance(result, dict)
                and "num_tensors" in result else None
            ),
        )

    def start_lokr(self, config: LoraTrainingConfig) -> TrainingStartedHandle:
        payload = _StartLoKRRequestPayload(
            tensor_dir=config.tensor_dir,
            output_dir=config.output_dir,
            lokr_linear_dim=config.lokr_linear_dim,
            lokr_linear_alpha=config.lokr_linear_alpha,
            lokr_factor=config.lokr_factor,
            lokr_decompose_both=config.lokr_decompose_both,
            lokr_use_tucker=config.lokr_use_tucker,
            lokr_use_scalar=config.lokr_use_scalar,
            lokr_weight_decompose=config.lokr_weight_decompose,
            learning_rate=config.learning_rate,
            train_epochs=config.train_epochs,
            train_batch_size=config.train_batch_size,
            gradient_accumulation=config.gradient_accumulation,
            save_every_n_epochs=config.save_every_n_epochs,
            training_shift=config.training_shift,
            training_seed=config.training_seed,
            gradient_checkpointing=config.gradient_checkpointing,
        ).model_dump()
        data = self._request_json("/v1/training/start_lokr", payload)
        return TrainingStartedHandle(
            tensor_dir=str(data.get("tensor_dir", config.tensor_dir)),
            output_dir=str(data.get("output_dir", config.output_dir)),
            message=str(data.get("message", "")),
        )

    def poll_training(self) -> TrainingStatus:
        data = self._request_json(
            "/v1/training/status",
            method="GET",
            timeout=TRAINING_STATUS_TIMEOUT_SECONDS,
        )
        return TrainingStatus(
            is_training=bool(data.get("is_training", False)),
            should_stop=bool(data.get("should_stop", False)),
            current_step=int(data.get("current_step", 0)),
            current_epoch=int(data.get("current_epoch", 0)),
            current_loss=(
                float(data["current_loss"])
                if data.get("current_loss") is not None else None
            ),
            status=str(data.get("status", "")),
            steps_per_second=float(data.get("steps_per_second", 0.0)),
            estimated_time_remaining=float(data.get("estimated_time_remaining", 0.0)),
            error=data.get("error"),
            run_id=(str(data["run_id"]) if data.get("run_id") else None),
        )

    def stop_training(self) -> None:
        self._request_json("/v1/training/stop")

    def export_training(
        self, lora_output_dir: str, export_path: str,
    ) -> ExportResult:
        payload = _ExportRequestPayload(
            export_path=export_path, lora_output_dir=lora_output_dir,
        ).model_dump()
        data = self._request_json("/v1/training/export", payload)
        return ExportResult(
            export_path=str(data.get("export_path", export_path)),
            source=str(data.get("source", "")),
            message=str(data.get("message", "")),
        )
