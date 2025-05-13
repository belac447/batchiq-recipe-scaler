# middleware.py

from functools import wraps
from flask import request, jsonify
from datetime import datetime
from supabase_client import supabase  # 👈 import your supabase client

FREE_LIMIT = 5

def enforce_usage_limit(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        email = request.headers.get("X-User-Email")  # Replace with JWT logic later

        if not email:
            return jsonify({"error": "Missing user email"}), 400

        result = supabase.table("users").select("*").eq("email", email).single().execute()

        if result.error or result.data is None:
            return jsonify({"error": "User not found"}), 404

        user = result.data
        usage_count = user.get("usage_count", 0)
        tier = user.get("tier", "free")
        paid = user.get("paid", False)

        if tier == "free" and not paid and usage_count >= FREE_LIMIT:
            return jsonify({
                "error": "Usage limit reached. Please upgrade.",
                "limit": FREE_LIMIT,
                "tier": tier
            }), 402

        supabase.table("users").update({
            "usage_count": usage_count + 1,
            "last_used": datetime.utcnow().isoformat()
        }).eq("email", email).execute()

        return f(*args, **kwargs)

    return decorated_function
