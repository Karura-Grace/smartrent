from datetime import date, datetime

def get_dashboard_stats(cur, tenant_info, tenant_id):
    stats = {}

    # 🔹 1. Monthly Rent
    rent_amount = tenant_info.get("amount") or 0
    if (not rent_amount) and tenant_info.get("unit_id"):
        cur.execute("SELECT rent FROM units WHERE id = %s LIMIT 1", (tenant_info.get("unit_id"),))
        rent_amount = (cur.fetchone() or {}).get("rent") or 0

    stats["rent_amount"] = f"KES {float(rent_amount):,.0f}"

    # 🔹 2. Pending Bills + Next Due Date
    cur.execute("""
        SELECT amount, due_date
        FROM bills
        WHERE tenant_id = %s AND TRIM(LOWER(status)) != 'paid'
        ORDER BY due_date ASC
    """, (tenant_id,))
    
    bills = cur.fetchall()

    stats["pending_bills"] = len(bills)

    next_due_date = None
    for bill in bills:
        due = bill.get("due_date")
        if due:
            if isinstance(due, str):
                try:
                    due = datetime.strptime(due, "%Y-%m-%d").date()
                except:
                    due = None
        if due and (next_due_date is None or due < next_due_date):
            next_due_date = due

    stats["next_due_date"] = str(next_due_date) if next_due_date else "N/A"

    # 🔹 3. Payments Made
    cur.execute("""
        SELECT COUNT(*) AS total
        FROM payments
        WHERE tenant_id = %s
        AND LOWER(status) = 'paid'
    """, (tenant_id,))

    stats["payments_made"] = (cur.fetchone() or {}).get("total", 0)

    # 🔹 4. Active Requests
    cur.execute("""
        SELECT COUNT(*) AS total
        FROM maintenance_requests
        WHERE tenant_id = %s
        AND LOWER(status) IN ('open','pending','in progress')
    """, (tenant_id,))

    stats["active_requests"] = (cur.fetchone() or {}).get("total", 0)

    return stats
