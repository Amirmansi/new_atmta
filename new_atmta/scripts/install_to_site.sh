#!/bin/bash
# Install new_atmta app to a site and import its customizations
# Usage: bash install_to_site.sh <site_name> [--force]
# Example: bash install_to_site.sh andal.atmta-erp.com
# Example: bash install_to_site.sh andal.atmta-erp.com --force

BENCH_PATH="/home/frappe/frappe-bench"
cd "$BENCH_PATH" || exit 1

SITE="$1"
FORCE="${2:-}"

if [ -z "$SITE" ]; then
    echo "Usage: bash install_to_site.sh <site_name> [--force]"
    echo ""
    echo "Available sites:"
    echo "  andal.atmta-erp.com"
    echo "  atmta.atmta-erp.com"
    echo "  atmta-finance.atmta-erp.com"
    echo "  ayash.atmta-erp.com"
    echo "  btack.atmta-erp.com"
    echo "  gazzal.atmta-erp.com"
    echo "  hila.atmta-erp.com"
    echo "  striangle.atmta-erp.com"
    echo "  tagmira.atmta-erp.com"
    echo "  tagmir.atmta-erp.com"
    echo "  training.atmta-erp.com"
    exit 1
fi

echo "Installing new_atmta to: $SITE"
echo ""

# Install app if not already installed
INSTALLED=$(bench --site "$SITE" list-apps 2>/dev/null | grep "new_atmta")
if [ -z "$INSTALLED" ]; then
    echo ">>> Installing app..."
    bench --site "$SITE" install-app new_atmta
else
    echo ">>> App already installed, skipping install."
fi

# Import fixtures
echo ""
echo ">>> Importing customizations..."
if [ "$FORCE" = "--force" ]; then
    bench --site "$SITE" execute new_atmta.scripts.import_site.run --kwargs '{"force": true}'
else
    bench --site "$SITE" execute new_atmta.scripts.import_site.run
fi

# Run migrate
echo ""
echo ">>> Running migrate..."
bench --site "$SITE" migrate

echo ""
echo "=============================="
echo "Done: $SITE"
echo "=============================="
