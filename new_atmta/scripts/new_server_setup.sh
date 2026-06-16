#!/bin/bash
# =============================================================
# NEW SERVER SETUP — Install new_atmta and restore all sites
# =============================================================
# Run this on the NEW server after:
#   1. Setting up frappe-bench
#   2. Restoring site backups
#   3. Copying apps/new_atmta into the new bench
#
# Usage:
#   bash new_server_setup.sh              # install for all sites
#   bash new_server_setup.sh andal.atmta-erp.com   # one site only
# =============================================================

BENCH_PATH="/home/frappe/frappe-bench"
cd "$BENCH_PATH" || exit 1

SITES=(
    "andal.atmta-erp.com"
    "atmta.atmta-erp.com"
    "atmta-finance.atmta-erp.com"
    "ayash.atmta-erp.com"
    "btack.atmta-erp.com"
    "gazzal.atmta-erp.com"
    "hila.atmta-erp.com"
    "striangle.atmta-erp.com"
    "tagmira.atmta-erp.com"
    "tagmir.atmta-erp.com"
    "training.atmta-erp.com"
)

# If a site argument is given, only process that site
if [ -n "$1" ]; then
    SITES=("$1")
fi

SUCCESS=0
FAILED=0

for site in "${SITES[@]}"; do
    echo ""
    echo "============================================================"
    echo "Processing: $site"
    echo "============================================================"

    # Check site exists
    if [ ! -d "$BENCH_PATH/sites/$site" ]; then
        echo "SKIP: $site — site directory not found"
        continue
    fi

    # Install app if not already installed
    INSTALLED=$(bench --site "$site" list-apps 2>/dev/null | grep "new_atmta")
    if [ -z "$INSTALLED" ]; then
        echo ">>> Installing new_atmta on $site..."
        bench --site "$site" install-app new_atmta 2>&1
    else
        echo ">>> new_atmta already installed on $site"
    fi

    # Import fixtures (skip existing, no force)
    echo ">>> Importing customizations..."
    env/bin/python import_new_atmta.py "$site" 2>&1

    # Migrate
    echo ">>> Running bench migrate..."
    bench --site "$site" migrate 2>&1

    echo ">>> Done: $site"
    SUCCESS=$((SUCCESS + 1))
done

echo ""
echo "============================================================"
echo "Setup complete: $SUCCESS success, $FAILED failed"
echo "============================================================"
