"""web.api.core — Core API handlers (shared JSON surface for both engines)."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from gp_control_plane import core_api
from gp_control_plane.backups import (
    create_snapshot_if_idle,
    delete_snapshot_if_idle,
    restore_snapshot_if_idle,
)
from gp_control_plane.bs_engine import bs_triage_domain, export_nfconf, stop_blockchecks
from gp_control_plane.discovery_engine import (
    campaign_lock_busy_message,
    check_blockchecks_install,
    is_blockchecks_job,
    normalize_engine,
)
from gp_control_plane.engine_cleaner import force_clean_engine_switch
from gp_control_plane.settings import read_run_settings, save_run_settings
from gp_control_plane.state import now_iso, read_state
from gp_control_plane.storage import append_run
from gp_control_plane.web.api import HandlerContext, register_get, register_post
from gp_control_plane.web.api_server._errors import RuntimeBusyError
from gp_control_plane.web.api_server._events import (
    _current_run_latest_log_payload,
    _events_response_payload,
    _latest_log_payload,
)
from gp_control_plane.web.api_server._helpers import _query_one
from gp_control_plane.web.api_server._jobs import (
    _clean_install_vault_create_response,
    _clean_install_vault_public_metadata,
    _clean_install_vault_restore_response,
    _job_discovery,
)
from gp_control_plane.zapret2 import cleanup_nft_blockcheck_tables

log = logging.getLogger(__name__)


def _ctx_query(ctx: HandlerContext) -> dict[str, list[str]]:
    return ctx.query


@register_get("/api/core/status")
def core_status(ctx: HandlerContext) -> dict[str, Any]:
    return core_api.status_payload(ctx.config)


@register_get("/api/core/strategy-discovery/current-run-progress")
def core_progress(ctx: HandlerContext) -> dict[str, Any]:
    return core_api.current_progress_payload(ctx.config)


@register_get("/api/core/strategy-discovery/current-run-latest-log")
def core_run_log(ctx: HandlerContext) -> dict[str, Any]:
    return _current_run_latest_log_payload(ctx.config, _ctx_query(ctx))


@register_get("/api/core/strategy-discovery/preflight")
def core_preflight(ctx: HandlerContext) -> dict[str, Any]:
    if normalize_engine(read_run_settings(ctx.config).get("discovery_engine")) == "blockchecks":
        return check_blockchecks_install()
    return core_api.preflight_payload(ctx.config)


@register_get("/api/core/strategy-discovery/triage")
def core_triage(ctx: HandlerContext) -> dict[str, Any]:
    domain = _query_one(_ctx_query(ctx), "domain")
    result = bs_triage_domain(domain)
    _record_triage(ctx.config.output.state_dir, domain, result)
    return result


def _record_triage(state_dir: Path, domain: str, result: dict[str, Any]) -> None:
    """Persist a triage check into the runs history (kind='triage')."""
    try:
        ts = now_iso()
        triage = result.get("triage") if isinstance(result.get("triage"), dict) else {}
        phase = (triage.get("domain_phases") or {}).get(domain) or triage.get(
            "handshake_phase"
        ) or ""
        append_run(
            state_dir,
            {
                "id": uuid.uuid4().hex,
                "kind": "triage",
                "status": "success" if str(result.get("status") or "") == "ok" else "error",
                "timestamp": ts,
                "started_at": ts,
                "completed_at": ts,
                "domains": [str(domain or "")] if domain else [],
                "discovery_engine": "blockchecks",
                "phase": "triage",
                "domain": str(domain or ""),
                "provider": str(result.get("provider") or ""),
                "phase_summary": str(phase or ""),
                "message": str(result.get("message") or result.get("output") or ""),
            },
        )
    except Exception:  # noqa: BLE001 — history must never break triage itself
        return


@register_get("/api/core/presets/domain-lists")
def core_presets(ctx: HandlerContext) -> dict[str, Any]:
    return core_api.domain_lists_payload(ctx.config)


@register_get("/api/core/presets/v2fly/categories")
def core_v2fly_categories(ctx: HandlerContext) -> dict[str, Any]:
    return core_api.v2fly_categories_payload(ctx.config, _ctx_query(ctx))


@register_get("/api/core/presets/v2fly/category-domains")
def core_v2fly_category_domains(ctx: HandlerContext) -> dict[str, Any]:
    return core_api.v2fly_category_domains_payload(ctx.config, _ctx_query(ctx))


@register_get("/api/core/backups/list")
def core_backups_list(ctx: HandlerContext) -> dict[str, Any]:
    return core_api.backups_list_payload(ctx.config)


@register_get("/api/core/clean-install-vaults/list")
def core_vaults_list(ctx: HandlerContext) -> dict[str, Any]:
    return {
        "vaults": [
            _clean_install_vault_public_metadata(item)
            for item in (core_api.clean_install_vault_list_payload(ctx.config).get("vaults") or [])
            if isinstance(item, dict)
        ]
    }


@register_get("/api/core/clean-install-vaults/status")
def core_vault_status(ctx: HandlerContext) -> dict[str, Any]:
    return _clean_install_vault_public_metadata(
        core_api.clean_install_vault_status_payload(ctx.config, _ctx_query(ctx))
    )


@register_get("/api/core/run-settings")
def core_run_settings(ctx: HandlerContext) -> dict[str, Any]:
    return core_api.run_settings_payload(read_run_settings(ctx.config))


@register_get("/api/core/runs/history")
def core_runs_history(ctx: HandlerContext) -> dict[str, Any]:
    return core_api.runs_history_payload(ctx.config, _ctx_query(ctx))


@register_get("/api/core/runs/latest-log")
def core_runs_latest_log(ctx: HandlerContext) -> dict[str, Any]:
    return _latest_log_payload(ctx.config, _ctx_query(ctx))


@register_get("/api/core/strategy-candidates")
def core_strategy_candidates(ctx: HandlerContext) -> dict[str, Any]:
    return core_api.strategy_candidates_payload(ctx.config, _ctx_query(ctx))


@register_get("/api/core/strategy-pairs")
def core_strategy_pairs(ctx: HandlerContext) -> dict[str, Any]:
    return core_api.strategy_pairs_payload(ctx.config, _ctx_query(ctx))


@register_get("/api/core/events")
def core_events(ctx: HandlerContext) -> dict[str, Any]:
    return _events_response_payload(ctx.config, _ctx_query(ctx), stream="core")


@register_post("/api/core/strategy-discovery/stop-current-run", error_status=409, value_error_status=409)
def core_stop_run(ctx: HandlerContext) -> tuple[dict[str, Any], int]:
    payload = ctx.body or {}
    if payload.get("dry_run"):
        state = read_state(ctx.config.output.state_dir)
        return (
            {
                "accepted": True,
                "status": "dry_run",
                "run_id": str(state.get("current_run_id") or ""),
            },
            202,
        )
    job = ctx.runner.cancel_active()
    return core_api.action_accepted_payload(job), 202


@register_post("/api/core/strategy-discovery/start-run", error_status=409, value_error_status=400)
def core_start_run(ctx: HandlerContext) -> tuple[dict[str, Any], int]:
    payload = dict(ctx.body or {})
    resume_run_id = str(payload.get("resume_run_id") or "").strip()
    incoming = dict(payload)
    raw_settings = incoming.get("settings")
    nested = dict(raw_settings) if isinstance(raw_settings, dict) else {}
    if "discovery_engine" not in nested:
        nested["discovery_engine"] = read_run_settings(ctx.config).get("discovery_engine")
        incoming["settings"] = nested
    resume_run_id_override: str | None = None
    if resume_run_id:
        # Resume = re-run the SAME blockcheckS run (reuse its per-run db):
        # parameters are rebuilt server-side from the persisted run record.
        if not (
            len(resume_run_id) == 32 and all(c in "0123456789abcdef" for c in resume_run_id)
        ):
            raise ValueError("resume_run_id must be a 32-char hex id")
        incoming = core_api.resume_discovery_request(ctx.config.output.state_dir, resume_run_id)
        resume_run_id_override = resume_run_id
    name, core_payload = core_api.strategy_discovery_job_payload(incoming)
    if is_blockchecks_job(name) and campaign_lock_busy_message():
        raise RuntimeBusyError()
    # Starting an engine different from the one that produced the previous
    # run may leave host residue behind (nft *_test tables, bs netns/shm).
    # Force-clean the engine being left, best-effort, before launching.
    try:
        cleanup = force_clean_engine_switch(
            ctx.config.output.state_dir,
            str(core_payload.get("discovery_engine") or "blockcheck2"),
        )
        if cleanup.get("cleaned"):
            log.info("engine switch cleanup before %s: %s", name, cleanup)
    except Exception:  # noqa: BLE001 — cleanup must never block run start
        log.warning("engine switch cleanup failed; continuing run start", exc_info=True)
    func = lambda stop, run_id: _job_discovery(ctx.config, name, core_payload, stop, run_id)
    cancel_hook = stop_blockchecks if is_blockchecks_job(name) else cleanup_nft_blockcheck_tables
    job = ctx.runner.start(name, func, cancel_hook=cancel_hook, run_id=resume_run_id_override)
    return core_api.run_accepted_payload(job), 202


@register_post("/api/core/strategy-discovery/export-nfconf", error_status=409, value_error_status=400)
def core_export_nfconf(ctx: HandlerContext) -> tuple[dict[str, Any], int]:
    payload = ctx.body or {}
    raw_dir = payload.get("out_dir")
    out_dir = Path(str(raw_dir)) if raw_dir else None
    limit = int(payload.get("limit") or 5)
    return export_nfconf(out_dir=out_dir, limit=limit), 200


@register_post("/api/core/presets/save-domain-list", error_status=400, value_error_status=400)
def core_save_domain_list(ctx: HandlerContext) -> tuple[dict[str, Any], int]:
    return core_api.save_domain_list_payload(ctx.config, ctx.body or {}), 200


@register_post("/api/core/presets/delete-user-domain-list", error_status=400, value_error_status=400)
def core_delete_user_domain_list(ctx: HandlerContext) -> tuple[dict[str, Any], int]:
    return core_api.delete_user_domain_list_payload(ctx.config, ctx.body or {}), 200


@register_post("/api/core/backups/create", error_status=409, value_error_status=409)
def core_backup_create(ctx: HandlerContext) -> tuple[dict[str, Any], int]:
    created = create_snapshot_if_idle(ctx.config.output.state_dir)
    if created.get("queued"):
        raise RuntimeBusyError()
    return core_api.backup_snapshot_payload(created.get("snapshot") or {}), 201


@register_post("/api/core/backups/restore", error_status=409, value_error_status=409)
def core_backup_restore(ctx: HandlerContext) -> tuple[dict[str, Any], int]:
    snapshot_id = core_api.payload_snapshot_id(ctx.body or {})
    restored = restore_snapshot_if_idle(ctx.config.output.state_dir, snapshot_id)
    if restored.get("queued"):
        raise RuntimeBusyError()
    return {"accepted": True, "status": "success", "snapshot_id": snapshot_id}, 202


@register_post("/api/core/backups/delete", error_status=409, value_error_status=409)
def core_backup_delete(ctx: HandlerContext) -> tuple[dict[str, Any], int]:
    snapshot_id = core_api.payload_snapshot_id(ctx.body or {})
    deleted = delete_snapshot_if_idle(ctx.config.output.state_dir, snapshot_id)
    if deleted.get("queued"):
        raise RuntimeBusyError()
    return {"deleted": 1}, 200


@register_post("/api/core/clean-install-vaults/create", error_status=409, value_error_status=400)
def core_vault_create(ctx: HandlerContext) -> tuple[dict[str, Any], int]:
    payload = ctx.body or {}
    if payload:
        raise ValueError("clean-install vault create does not accept request fields")
    created = core_api.clean_install_vault_create_payload(ctx.config, payload)
    return _clean_install_vault_create_response(created), 201


@register_post("/api/core/clean-install-vaults/restore", error_status=409, value_error_status=400)
def core_vault_restore(ctx: HandlerContext) -> tuple[dict[str, Any], int]:
    payload = ctx.body or {}
    allowed = {"vault_id", "confirm_restore"}
    unknown = sorted(str(key) for key in payload if str(key) not in allowed)
    if unknown:
        raise ValueError(f"unsupported clean-install vault restore fields: {', '.join(unknown)}")
    restored = core_api.clean_install_vault_restore_payload(ctx.config, payload)
    public_response = _clean_install_vault_restore_response(restored, "")
    if not (
        public_response["completed"]
        and public_response["verification"]["verified"]
        and public_response["storage_status"]["ready"]
        and public_response["cleanup"]["source_deleted"]
    ):
        raise RuntimeError("clean-install vault restore did not complete; source retained")
    return public_response, 200


@register_post("/api/core/run-settings/save", error_status=400, value_error_status=400)
def core_save_run_settings(ctx: HandlerContext) -> tuple[dict[str, Any], int]:
    payload = ctx.body or {}
    return (
        core_api.run_settings_payload(save_run_settings(ctx.config, payload.get("settings") or payload)),
        200,
    )
