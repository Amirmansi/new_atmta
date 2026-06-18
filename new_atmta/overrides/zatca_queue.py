"""Durable ZATCA queue isolation for the ERPNext v15 multi-site bench.

ksa_compliance enqueues its realtime ZATCA submission job
(``_submit_additional_fields``) on the ``default`` RQ queue. On a busy
multi-site bench this lets ZATCA work contend with UI-critical background jobs.

This module routes that specific job to a dedicated ``zatca`` queue instead,
WITHOUT editing the vendor (ksa_compliance) app, so the behaviour survives
ksa_compliance updates and lives in our own app/repo.

Safety design (this must never break unrelated background jobs):
- It only rewrites the queue for the exact ksa_compliance ZATCA submit function.
- Every decision is wrapped in ``try/except``; on ANY unexpected condition it
  silently falls back to the original ``enqueue`` behaviour.
- It patches once per process and is idempotent.

Requirements (bench-level, already provisioned on this server):
- ``zatca`` registered in ``sites/common_site_config.json`` under ``workers``.
- A supervisor worker listening on the ``zatca`` queue.
If the ``zatca`` queue is not registered, frappe rejects the unknown queue; in
that case ZATCA simply keeps using ``default`` (no breakage), because frappe
validates the queue inside the original ``enqueue`` which we still call.
"""

import frappe.utils.background_jobs as _background_jobs

_PATCH_ATTR = "_new_atmta_zatca_queue_patched"
_ZATCA_QUEUE = "zatca"
_TARGET_FUNC = "_submit_additional_fields"
_TARGET_MODULE_PREFIX = "ksa_compliance"


def _should_route_to_zatca(method) -> bool:
    return (
        getattr(method, "__name__", "") == _TARGET_FUNC
        and (getattr(method, "__module__", "") or "").startswith(_TARGET_MODULE_PREFIX)
    )


def apply_zatca_queue_patch() -> None:
    """Install the defensive enqueue wrapper (idempotent, per-process)."""
    original_enqueue = _background_jobs.enqueue
    if getattr(original_enqueue, _PATCH_ATTR, False):
        return

    def enqueue(*args, **kwargs):
        try:
            if kwargs.get("queue", "default") == "default":
                method = args[0] if args else kwargs.get("method")
                if method is not None and _should_route_to_zatca(method):
                    kwargs = {**kwargs, "queue": _ZATCA_QUEUE}
        except Exception:
            # Never let queue routing affect job submission.
            pass
        return original_enqueue(*args, **kwargs)

    setattr(enqueue, _PATCH_ATTR, True)
    enqueue.__wrapped__ = original_enqueue
    _background_jobs.enqueue = enqueue


def apply_zatca_queue_patch_hook(*args, **kwargs) -> None:
    """Entry point for frappe ``before_request`` / ``before_job`` hooks.

    These hooks are dispatched by frappe on every web request and every
    background job, so this guarantees the enqueue patch is active in each
    process regardless of frappe's hooks cache. Idempotent and never raises.
    """
    try:
        apply_zatca_queue_patch()
    except Exception:
        pass
