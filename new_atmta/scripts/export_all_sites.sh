#!/bin/bash
# Export customizations from ALL sites into new_atmta/site_fixtures/
# Usage: bash export_all_sites.sh
# Run from: /home/frappe/frappe-bench

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

SUCCESS=0
FAILED=0

for site in "${SITES[@]}"; do
    echo ""
    echo ">>> Exporting: $site"
    bench --site "$site" execute new_atmta.scripts.export_site.run 2>&1
    if [ $? -eq 0 ]; then
        SUCCESS=$((SUCCESS + 1))
    else
        echo "FAILED: $site"
        FAILED=$((FAILED + 1))
    fi
done

echo ""
echo "=============================="
echo "Done: $SUCCESS success, $FAILED failed"
echo "=============================="
