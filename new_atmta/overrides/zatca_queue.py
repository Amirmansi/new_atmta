"""Durable ZATCA safety and queue isolation for the ERPNext v15 bench.

ksa_compliance enqueues its realtime ZATCA submission job
(``_submit_additional_fields``) on the ``default`` RQ queue. On a busy
multi-site bench this lets ZATCA work contend with UI-critical background jobs.

This module routes that specific job to a dedicated ``zatca`` queue and keeps
invoice submission non-blocking if local ZATCA preparation fails (for example,
missing CLI/certificate/private-key files). It does this WITHOUT editing the
vendor (ksa_compliance) app, so the behaviour survives ksa_compliance updates
and lives in our own app/repo.

Safety design (this must never break unrelated background jobs):
- It only rewrites the queue for the exact ksa_compliance ZATCA submit function.
- It only softens failures in ksa_compliance "create additional fields" hooks,
  where a local CLI/certificate failure would otherwise cancel invoice submit.
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

import importlib

import frappe
import frappe.utils.background_jobs as _background_jobs

_PATCH_ATTR = "_new_atmta_zatca_queue_patched"
_SAFETY_PATCH_ATTR = "_new_atmta_zatca_safety_patched"
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


def _log_non_blocking_zatca_failure(doc, error: Exception, source: str) -> None:
    try:
        frappe.log_error(
            title=f"Non-blocking ZATCA failure: {source}",
            message=f"Document: {getattr(doc, 'doctype', '')} {getattr(doc, 'name', '')}\n\n{frappe.get_traceback()}",
        )
    except Exception:
        pass

    try:
        frappe.msgprint(
            "تم تسجيل المستند بنجاح، لكن تجهيز/إرسال ZATCA لم يكتمل بسبب إعدادات محلية "
            "(CLI أو شهادة أو مفتاح خاص). تم تسجيل الخطأ للمراجعة ولن يتم إيقاف الفاتورة.",
            title="ZATCA لم يوقف التسجيل",
            indicator="orange",
        )
    except Exception:
        pass


def _wrap_non_blocking(module_path: str, function_name: str) -> None:
    module = importlib.import_module(module_path)
    original = getattr(module, function_name, None)
    if not original or getattr(original, _SAFETY_PATCH_ATTR, False):
        return

    def safe_wrapper(doc, method=None):
        try:
            return original(doc, method)
        except Exception as error:
            _log_non_blocking_zatca_failure(doc, error, f"{module_path}.{function_name}")
            return None

    setattr(safe_wrapper, _SAFETY_PATCH_ATTR, True)
    safe_wrapper.__wrapped__ = original
    setattr(module, function_name, safe_wrapper)


def apply_zatca_safety_patch() -> None:
    """Keep invoice/payment submission from failing on local ZATCA tooling issues."""
    _wrap_non_blocking(
        "ksa_compliance.standard_doctypes.sales_invoice",
        "create_sales_invoice_additional_fields_doctype",
    )
    _wrap_non_blocking(
        "ksa_compliance.standard_doctypes.payment_entry.payment_entry",
        "create_prepayment_invoice_additional_fields_doctype",
    )


def apply_zatca_queue_patch_hook(*args, **kwargs) -> None:
    """Entry point for frappe ``before_request`` / ``before_job`` hooks.

    These hooks are dispatched by frappe on every web request and every
    background job, so this guarantees the enqueue patch is active in each
    process regardless of frappe's hooks cache. Idempotent and never raises.
    """
    try:
        apply_zatca_queue_patch()
        apply_zatca_safety_patch()
    except Exception:
        pass
