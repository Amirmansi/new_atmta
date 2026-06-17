"""
Bench-level performance tuning for frappe-bench-v15.

Tuned for 18-core / 94GB server (shared with V16 bench).
"""

from __future__ import annotations

import json
import os
import re

import frappe

V15_GUNICORN_WORKERS = 14
V15_BACKGROUND_WORKERS = 8
V15_GUNICORN_WORKER_CLASS = "gevent"
V15_GUNICORN_WORKER_CONNECTIONS = 512
NGINX_UPSTREAM_KEEPALIVE = 64


def _bench_path() -> str:
	return frappe.utils.get_bench_path()


def _common_site_config_path() -> str:
	return os.path.join(_bench_path(), "sites", "common_site_config.json")


def tune_common_site_config() -> dict:
	"""Update shared bench config for higher concurrency."""
	path = _common_site_config_path()
	with open(path, encoding="utf-8") as f:
		config = json.load(f)

	changes = {}
	updates = {
		"gunicorn_workers": V15_GUNICORN_WORKERS,
		"background_workers": V15_BACKGROUND_WORKERS,
		"http_timeout": 120,
		"live_reload": False,
		"server_script_enabled": True,
	}
	for key, value in updates.items():
		if config.get(key) != value:
			config[key] = value
			changes[key] = value

	if changes:
		with open(path, "w", encoding="utf-8") as f:
			json.dump(config, f, indent=1, ensure_ascii=False)
			f.write("\n")

	return {"updated": changes, "gunicorn_workers": config.get("gunicorn_workers")}


def tune_nginx_keepalive() -> dict:
	"""Enable upstream keepalive + HTTP/1.1 reuse for faster page loads."""
	nginx_path = os.path.join(_bench_path(), "config", "nginx.conf")
	if not os.path.exists(nginx_path):
		return {"skipped": "nginx.conf not found"}

	with open(nginx_path, encoding="utf-8") as f:
		content = f.read()

	original = content

	# Upstream keepalive pool
	if "keepalive" not in content.split("upstream frappe-bench-v15-frappe")[1].split("}")[0]:
		content = content.replace(
			"upstream frappe-bench-v15-frappe {\n\tserver 127.0.0.1:8000 fail_timeout=0;\n}",
			f"upstream frappe-bench-v15-frappe {{\n\tserver 127.0.0.1:8000 fail_timeout=0;\n\tkeepalive {NGINX_UPSTREAM_KEEPALIVE};\n}}",
		)

	# Reuse connections to gunicorn in all @webserver proxy blocks
	if 'proxy_set_header Connection ""' not in content:
		content = content.replace(
			"proxy_http_version 1.1;\n\t\tproxy_set_header X-Forwarded-For",
			'proxy_http_version 1.1;\n\t\tproxy_set_header Connection "";\n\t\tproxy_set_header X-Forwarded-For',
		)

	# Faster static asset delivery
	if "tcp_nopush on" not in content:
		content = content.replace(
			"sendfile on;\n\tkeepalive_timeout 15;",
			"sendfile on;\n\ttcp_nopush on;\n\ttcp_nodelay on;\n\tkeepalive_timeout 30;",
		)

	if content != original:
		with open(nginx_path, "w", encoding="utf-8") as f:
			f.write(content)
		return {"nginx_patched": True, "keepalive": NGINX_UPSTREAM_KEEPALIVE}

	return {"nginx_patched": False}


def tune_redis_cache() -> dict:
	"""Ensure Redis cache has adequate memory for 7 sites."""
	redis_conf = os.path.join(_bench_path(), "config", "redis_cache.conf")
	if not os.path.exists(redis_conf):
		return {"skipped": "redis_cache.conf not found"}

	with open(redis_conf, encoding="utf-8") as f:
		content = f.read()

	target = "maxmemory 12288mb"
	if target in content:
		return {"redis_patched": False}

	new_content = re.sub(r"maxmemory \d+mb", target, content)
	if new_content != content:
		with open(redis_conf, "w", encoding="utf-8") as f:
			f.write(new_content)
		return {"redis_patched": True, "maxmemory": "12GB"}

	return {"redis_patched": False}


def ensure_gevent() -> dict:
	"""Install gevent for async gunicorn workers if missing."""
	import subprocess
	import sys

	try:
		import gevent  # noqa: F401

		return {"gevent": "installed"}
	except ImportError:
		bench_path = _bench_path()
		python = os.path.join(bench_path, "env", "bin", "python")
		subprocess.run(
			[python, "-m", "pip", "install", "gevent"],
			check=True,
			capture_output=True,
			text=True,
		)
		return {"gevent": "installed_now"}


def tune_supervisor_gunicorn() -> dict:
	"""Patch supervisor gunicorn command for gevent workers."""
	supervisor_path = os.path.join(_bench_path(), "config", "supervisor.conf")
	if not os.path.exists(supervisor_path):
		return {"skipped": "supervisor.conf not found"}

	with open(supervisor_path, encoding="utf-8") as f:
		content = f.read()

	original = content
	worker_flag = f"-w {V15_GUNICORN_WORKERS}"
	gevent_flags = (
		f"--worker-class {V15_GUNICORN_WORKER_CLASS} "
		f"--worker-connections {V15_GUNICORN_WORKER_CONNECTIONS}"
	)

	# Normalize worker count
	content = re.sub(r"-w \d+", worker_flag, content)

	if V15_GUNICORN_WORKER_CLASS not in content:
		content = content.replace(
			"frappe.app:application --preload",
			f"frappe.app:application {gevent_flags} --preload",
		)

	if content != original:
		with open(supervisor_path, "w", encoding="utf-8") as f:
			f.write(content)
		return {"supervisor_patched": True, "worker_class": V15_GUNICORN_WORKER_CLASS}

	return {"supervisor_patched": False}


def tune_v15_bench() -> dict:
	"""Run all bench-level performance tunings (idempotent)."""
	return {
		"gevent": ensure_gevent(),
		"common_config": tune_common_site_config(),
		"supervisor": tune_supervisor_gunicorn(),
		"nginx": tune_nginx_keepalive(),
		"redis": tune_redis_cache(),
	}
