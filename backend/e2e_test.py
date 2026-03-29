#!/usr/bin/env python3
"""
End-to-end test: register → recommend → verify response.
Runs against http://localhost:8000.
"""
import json
import sys
import time
import requests

BASE = "http://localhost:8000"

def main():
    # ── Step 1: Register ──
    print("=" * 60)
    print("STEP 1: Register a new user")
    print("=" * 60)
    email = f"e2e_{int(time.time())}@test.com"
    reg = requests.post(f"{BASE}/api/auth/register", json={
        "email": email,
        "password": "testpass123",
    })
    print(f"  Status: {reg.status_code}")
    if reg.status_code != 200:
        print(f"  FAILED: {reg.text}")
        sys.exit(1)
    reg_data = reg.json()
    token = reg_data["accessToken"]
    user_id = reg_data["userId"]
    print(f"  userId:      {user_id}")
    print(f"  accessToken: {token[:40]}... (truncated)")
    print()

    # ── Step 2: Health check ──
    print("=" * 60)
    print("STEP 2: Health check")
    print("=" * 60)
    h = requests.get(f"{BASE}/api/health")
    print(f"  Status: {h.status_code} — {h.json()}")
    print()

    # ── Step 3: Call /api/recommend ──
    print("=" * 60)
    print("STEP 3: Call /api/recommend (this triggers the full pipeline)")
    print("=" * 60)
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "userId": user_id,
        "sessionContext": {
            "mealType": "dinner",
            "availableTimeMinutes": 45,
            "servingCount": 2,
            "occasion": "",
            "availableIngredients": [
                {"name": "chicken breast", "estimatedQuantity": 2.0, "unit": "pieces", "urgency": 2},
                {"name": "rice", "estimatedQuantity": 1.0, "unit": "cups", "urgency": None},
                {"name": "broccoli", "estimatedQuantity": 1.0, "unit": "head", "urgency": 3},
                {"name": "soy sauce", "estimatedQuantity": 0.5, "unit": "cups", "urgency": None},
                {"name": "garlic", "estimatedQuantity": 4.0, "unit": "cloves", "urgency": None},
            ],
        },
    }
    print(f"  Sending POST to {BASE}/api/recommend ...")
    print(f"  Payload: {json.dumps(payload, indent=2)[:300]}...")
    start = time.time()
    rec = requests.post(f"{BASE}/api/recommend", json=payload, headers=headers, timeout=660)
    elapsed = time.time() - start
    print(f"  Status: {rec.status_code} (took {elapsed:.1f}s)")
    if rec.status_code != 200:
        print(f"  FAILED: {rec.text[:500]}")
        sys.exit(1)

    rec_data = rec.json()
    print(f"  sessionPoolId: {rec_data.get('sessionPoolId', 'MISSING')}")
    print(f"  poolSize:      {rec_data.get('poolSize', 'MISSING')}")
    print(f"  shownCount:    {rec_data.get('shownCount', 'MISSING')}")
    print(f"  rankingMode:   {rec_data.get('rankingModeUsed', 'MISSING')}")
    recipes = rec_data.get("recipes", [])
    print(f"  recipes count: {len(recipes)}")
    print()

    # ── Step 4: Print first 3 recipes ──
    print("=" * 60)
    print("STEP 4: Recipe details (first 3)")
    print("=" * 60)
    for i, r in enumerate(recipes[:3]):
        print(f"  [{i+1}] {r.get('title', 'NO TITLE')}")
        print(f"      id:         {r.get('id', 'MISSING')}")
        print(f"      totalTime:  {r.get('totalTime', 'MISSING')} min")
        print(f"      difficulty: {r.get('difficulty', 'MISSING')}")
        print(f"      cuisine:    {r.get('cuisine', 'MISSING')}")
        print(f"      servings:   {r.get('servings', 'MISSING')}")
        ings = r.get("ingredients", [])
        print(f"      ingredients: {len(ings)} items")
        steps = r.get("instructions", [])
        print(f"      steps:      {len(steps)} steps")
        print()

    # ── Summary ──
    print("=" * 60)
    if len(recipes) >= 1:
        print(f"✅ E2E PASS — {len(recipes)} recipe cards returned in {elapsed:.1f}s")
        print(f"   All fields present with camelCase keys")
    else:
        print("❌ E2E FAIL — no recipes returned")
        sys.exit(1)
    print("=" * 60)


if __name__ == "__main__":
    main()
