#!/usr/bin/env bash
# Smoke test для Recipe Manager.
# Запуск: docker exec rm-standalone bash /app/smoke_test.sh
# Или через deploy_dev.sh: ssh vm "docker exec rm-standalone bash /app/smoke_test.sh"
set -u

BASE="${1:-http://localhost:8099}"
TOKEN="${TEST_TOKEN:-dev-smoke-test-token}"
PASS=0
FAIL=0
FAILED=()

if [ -z "$TOKEN" ]; then
    echo "❌ TEST_TOKEN не задан. Установите TEST_MODE=true и TEST_TOKEN в .env (dev)."
    exit 2
fi

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

# --- Вспомогательные функции ------------------------------------------------

_req() {
    # $1 метод, $2 путь, $3 тело (optional)
    local method="$1" path="$2" body="${3:-}"
    if [ "$method" = "GET" ]; then
        curl -s -o /tmp/smoke.json -w "%{http_code}" --max-time 10 \
            -H "X-Test-Token: $TOKEN" "$BASE$path" 2>/dev/null || echo "000"
    else
        curl -s -o /tmp/smoke.json -w "%{http_code}" --max-time 10 \
            -X "$method" -H "X-Test-Token: $TOKEN" \
            -H "Content-Type: application/json" -d "$body" "$BASE$path" 2>/dev/null || echo "000"
    fi
}

_status() {
    # Строгий: должен быть конкретный статус
    local method="$1" path="$2" expected="$3" body="${4:-}"
    local code
    code=$(_req "$method" "$path" "$body")
    if [ "$code" = "$expected" ]; then
        printf "  ${GREEN}✓${NC} %-5s %s [%s]\n" "$method" "$path" "$code"
        PASS=$((PASS+1))
    else
        printf "  ${RED}✗${NC} %-5s %s [%s] (expected %s)\n" "$method" "$path" "$code" "$expected"
        FAIL=$((FAIL+1))
        FAILED+=("$method $path → $code (expected $expected)")
        # Выводим тело ответа для отладки
        local resp_body
        resp_body=$(cat /tmp/smoke.json 2>/dev/null | head -c 300)
        echo "     Body: $resp_body"
    fi
}

_ok() {
    # Строгий: должен быть 200
    local method="$1" path="$2"
    local code
    code=$(_req "$method" "$path")
    if [ "$code" = "200" ]; then
        printf "  ${GREEN}✓${NC} %-5s %s [%s]\n" "$method" "$path" "$code"
        PASS=$((PASS+1))
    else
        printf "  ${RED}✗${NC} %-5s %s [%s]\n" "$method" "$path" "$code"
        FAIL=$((FAIL+1))
        FAILED+=("$method $path → $code")
    fi
}

_exists() {
    # Нестрогий: главное не 404/405 (роут есть и не перекрыт)
    local method="$1" path="$2"
    local code
    code=$(_req "$method" "$path")
    if [ "$code" = "404" ] || [ "$code" = "405" ] || [ "$code" = "000" ]; then
        printf "  ${RED}✗${NC} %-5s %s [%s] (missing/shadowed)\n" "$method" "$path" "$code"
        FAIL=$((FAIL+1))
        FAILED+=("$method $path → $code (missing/shadowed)")
    else
        printf "  ${GREEN}✓${NC} %-5s %s [%s]\n" "$method" "$path" "$code"
        PASS=$((PASS+1))
    fi
}

_field() {
    # GET + JSON field exists
    local path="$1" field="$2"
    local code
    code=$(_req GET "$path")
    if [ "$code" != "200" ]; then
        printf "  ${RED}✗${NC} GET   %s [%s] (no 200)\n" "$path" "$code"
        FAIL=$((FAIL+1)); FAILED+=("$path no 200")
        return
    fi
    if jq -e ".$field" /tmp/smoke.json >/dev/null 2>&1; then
        printf "  ${GREEN}✓${NC} GET   %s [field: %s]\n" "$path" "$field"
        PASS=$((PASS+1))
    else
        printf "  ${RED}✗${NC} GET   %s [missing: %s]\n" "$path" "$field"
        FAIL=$((FAIL+1)); FAILED+=("$path missing $field")
    fi
}

# --- Тесты ----------------------------------------------------------------

echo "================================================================"
echo "🧪 Smoke test: $BASE"
echo "================================================================"

echo
echo "--- Health & status ---"
_ok GET /api/health
_field /api/health status
_ok GET /api/generator/status
_field /api/generator/status providers
_ok GET /api/generator/diag
_ok GET /api/matcher/status

echo
echo "--- Auth & profile ---"
_ok GET /api/me
_field /api/me authenticated
_ok GET /api/me/llm

echo
echo "--- Recipes ---"
_ok GET /api/recipes
_field /api/recipes recipes
_status GET /api/recipes/nonexistent-id-12345 404

echo
echo "--- Shopping ---"
_ok GET /api/shopping
_field /api/shopping items
_ok GET "/api/shopping/export-for-connector?store_id=vkusvill"
_field "/api/shopping/export-for-connector?store_id=vkusvill" items

echo
echo "--- Meal plan ---"
_ok GET "/api/meal-plan?start=2026-10-01&end=2026-10-31"

echo
echo "--- Products & ingredients ---"
_ok GET /api/ingredients
_ok GET /api/ingredients/categories
_ok GET /api/products/unlinked

echo
echo "--- Profiles ---"
_ok GET /api/profiles
_ok GET /api/profiles/active

echo
echo "--- Generator ---"
_ok GET "/api/generator/suggestions?status=all"
_ok GET /api/generator/jobs

echo
echo "--- Admin & sync ---"
_ok GET /api/admin/users
_status GET /api/sync/status 200

echo
echo "--- Settings ---"
_ok GET /api/settings
_field /api/settings generator_max_tokens

echo
echo "--- Embedding service ---"
_ok GET /v1/models

echo
echo "--- Static & SPA ---"
_status GET / 307
_ok GET /static/js/app.js
_ok GET /static/css/style.css
_exists GET /favicon.ico
_exists GET /

echo
echo "--- POST (read-only) ---"
_status POST "/api/recipes/-/find-by-ingredients" 200 '{"ingredients":["лук","морковь"]}'
# _field для POST не работает — используем _status выше

echo
echo "================================================================"
if [ "$FAIL" -eq 0 ]; then
    printf "${GREEN}✅ ВСЁ ОК${NC}: %d проверок\n" "$PASS"
    exit 0
else
    printf "${RED}❌ ПРОВАЛ${NC}: %d прошло, %d упало\n" "$PASS" "$FAIL"
    echo
    echo "Failed:"
    for line in "${FAILED[@]}"; do echo "  - $line"; done
    exit 1
fi
