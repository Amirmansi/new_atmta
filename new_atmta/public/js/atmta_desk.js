/* ATMTA Desk — faster navigation + API response caching */
(function () {
	"use strict";

	const LOADER_ID = "atmta-route-loader";
	const SIDEBAR_CACHE_KEY = "atmta_workspace_sidebar_v4";
	const LEGACY_SIDEBAR_CACHE_KEYS = [
		"atmta_workspace_sidebar_v1",
		"atmta_workspace_sidebar_v2",
		"atmta_workspace_sidebar_v3",
	];
	let loaderTimer = null;
	let hooksBound = false;
	let callHooked = false;

	function ensureLoader() {
		if (document.getElementById(LOADER_ID)) return;
		const bar = document.createElement("div");
		bar.id = LOADER_ID;
		bar.className = "atmta-route-loader";
		bar.setAttribute("aria-hidden", "true");
		document.body.appendChild(bar);
	}

	function showLoader() {
		ensureLoader();
		const bar = document.getElementById(LOADER_ID);
		if (!bar) return;
		clearTimeout(loaderTimer);
		loaderTimer = setTimeout(() => bar.classList.add("active"), 30);
	}

	function hideLoader() {
		clearTimeout(loaderTimer);
		const bar = document.getElementById(LOADER_ID);
		if (bar) bar.classList.remove("active");
	}

	function markPageReady() {
		document.body.classList.add("atmta-page-ready");
		hideLoader();
	}

	function prefetchRoute(route) {
		if (!route || !frappe.model || !frappe.model.with_doctype) return;
		const parts = route.split("/");
		if (parts[0] !== "List" && parts[0] !== "Form") return;
		const doctype = decodeURIComponent(parts[1] || "");
		if (!doctype) return;
		frappe.model.with_doctype(doctype, () => {});
	}

	function bindWorkspacePrefetch() {
		$(document).on(
			"mouseenter.atmta focusin.atmta",
			".sidebar-item-container a.item-anchor, .desk-sidebar .item-anchor",
			function () {
				const href = $(this).attr("href") || "";
				if (href.startsWith("/app/")) {
					prefetchRoute(href.replace("/app/", ""));
				}
			}
		);
	}

	function clearLegacySidebarCache() {
		sessionStorage.removeItem(SIDEBAR_CACHE_KEY);
		LEGACY_SIDEBAR_CACHE_KEYS.forEach((key) => sessionStorage.removeItem(key));
	}

	function hasRenderableWorkspaceContent(response) {
		const pages = response && response.message && response.message.pages;
		if (!Array.isArray(pages) || !pages.length) return false;
		return pages.some((page) => typeof page.content === "string" && page.content.length > 2);
	}

	function hookFrappeCallCache() {
		if (callHooked || !frappe.call) return;
		callHooked = true;

		const originalCall = frappe.call.bind(frappe);
		frappe.call = function (opts) {
			const method = opts && (opts.method || opts.cmd);
			if (
				method === "frappe.desk.desktop.get_workspace_sidebar_items" &&
				sessionStorage.getItem(SIDEBAR_CACHE_KEY)
			) {
				try {
					const cached = JSON.parse(sessionStorage.getItem(SIDEBAR_CACHE_KEY));
					if (
						cached &&
						cached.expires > Date.now() &&
						hasRenderableWorkspaceContent(cached.data)
					) {
						const callback = opts.callback;
						if (callback) {
							setTimeout(() => callback(cached.data), 0);
						}
						if (opts.always) opts.always(cached.data);
						return Promise.resolve(cached.data);
					}
					sessionStorage.removeItem(SIDEBAR_CACHE_KEY);
				} catch (e) {
					sessionStorage.removeItem(SIDEBAR_CACHE_KEY);
				}
			}

			const userCallback = opts.callback;
			opts.callback = function (r) {
				if (
					method === "frappe.desk.desktop.get_workspace_sidebar_items" &&
					r &&
					r.message &&
					hasRenderableWorkspaceContent(r)
				) {
					sessionStorage.setItem(
						SIDEBAR_CACHE_KEY,
						JSON.stringify({
							expires: Date.now() + 5 * 60 * 1000,
							data: r,
						})
					);
				}
				if (userCallback) userCallback(r);
			};
			return originalCall(opts);
		};
	}

	function withTimeout(promise, ms, label) {
		let timeoutId;
		const timeout = new Promise((resolve) => {
			timeoutId = setTimeout(() => {
				console.warn(`[ATMTA Desk] ${label} timed out; continuing render.`);
				resolve();
			}, ms);
		});
		return Promise.race([promise, timeout]).finally(() => clearTimeout(timeoutId));
	}

	function hookWorkspaceRecovery() {
		const Workspace = frappe.views && frappe.views.Workspace;
		if (!Workspace || Workspace.prototype.__atmta_recovery_hooked) return false;

		Workspace.prototype.__atmta_recovery_hooked = true;
		const originalGetData = Workspace.prototype.get_data;
		const originalShowPage = Workspace.prototype.show_page;

		Workspace.prototype.get_data = function (...args) {
			const promise = Promise.resolve(originalGetData.apply(this, args)).catch((error) => {
				console.error("[ATMTA Desk] Workspace data failed", error);
				this.page_data = this.page_data || {};
			});
			return withTimeout(promise, 8000, "Workspace data load");
		};

		Workspace.prototype.show_page = async function (...args) {
			try {
				return await originalShowPage.apply(this, args);
			} catch (error) {
				console.error("[ATMTA Desk] Workspace render failed", error);
			} finally {
				if (typeof this.remove_page_skeleton === "function") {
					this.remove_page_skeleton();
				}
				if (typeof this.remove_sidebar_skeleton === "function") {
					this.remove_sidebar_skeleton();
				}
			}
		};

		return true;
	}

	function waitForWorkspaceRecovery() {
		if (hookWorkspaceRecovery()) return;
		let attempts = 0;
		const timer = setInterval(() => {
			attempts += 1;
			if (hookWorkspaceRecovery() || attempts > 40) {
				clearInterval(timer);
			}
		}, 250);
	}

	function bindRouteHooks() {
		if (hooksBound || !frappe.router) return;
		hooksBound = true;

		const originalSetRoute = frappe.router.set_route.bind(frappe.router);
		frappe.router.set_route = function (...args) {
			document.body.classList.remove("atmta-page-ready");
			showLoader();
			return originalSetRoute(...args);
		};

		frappe.router.on("change", () => {
			requestAnimationFrame(markPageReady);
		});
	}

	function init() {
		clearLegacySidebarCache();
		ensureLoader();
		// Server-side Redis cache is safer than browser sessionStorage for Workspaces.
		// Keep the call hook disabled to avoid stale Chrome state and xcall edge cases.
		bindRouteHooks();
		bindWorkspacePrefetch();
		waitForWorkspaceRecovery();
		markPageReady();
	}

	$(document).ready(init);
	$(document).on("app_ready", init);
})();
