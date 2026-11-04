echo "=== A. Устаревшие api/products в JS ==="
grep -rn "api/products" app/static/js/ 2>/dev/null

echo ""
echo "=== B. Ключ продукта в store ==="
grep -n "def add\|def get\|def get_active\|def set_vector\|\"id\"\|'id'\|product_id" app/stores/ingredients.py | head -30

echo ""
echo "=== C. Использование p\[\"product_id\"\] в cascade ==="
grep -n 'p\["product_id"\]\|\["product_id"\]' app/services/matcher/cascade.py

echo ""
echo "=== D. MatchCandidate.product_id ==="
grep -n "product_id" app/services/matcher/base.py | head