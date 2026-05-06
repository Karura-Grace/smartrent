import MySQLdb, MySQLdb.cursors
conn=MySQLdb.connect(host='localhost',user='root',passwd='',db='smartrent',charset='utf8mb4',cursorclass=MySQLdb.cursors.DictCursor)
cur=conn.cursor()

# All payments for landlord 8 May 2026 - full detail
cur.execute("""
    SELECT pay.id, pay.tenant_id, t.name, pay.Amount, pay.month, pay.paid_on, pay.method, pay.reference
    FROM payments pay
    JOIN properties p ON p.id=pay.property_id
    JOIN tenant t ON t.id=pay.tenant_id
    WHERE p.landlord_id=8 AND pay.paid_on >= '2026-05-01' AND pay.paid_on < '2026-06-01'
    ORDER BY pay.tenant_id, pay.id
""")
print('All payments landlord 8 May:')
for r in cur.fetchall(): print(r)

print()
# All payments for landlord 5 May 2026
cur.execute("""
    SELECT pay.id, pay.tenant_id, t.name, pay.Amount, pay.month, pay.paid_on, pay.method, pay.reference
    FROM payments pay
    JOIN properties p ON p.id=pay.property_id
    JOIN tenant t ON t.id=pay.tenant_id
    WHERE p.landlord_id=5 AND pay.paid_on >= '2026-05-01' AND pay.paid_on < '2026-06-01'
    ORDER BY pay.tenant_id, pay.id
""")
print('All payments landlord 5 May:')
for r in cur.fetchall(): print(r)

print()
# What is the actual rent amount per tenant
cur.execute("""
    SELECT t.id, t.name, t.amount as rent, p.landlord_id
    FROM tenant t JOIN properties p ON p.id=t.property_id
    WHERE p.landlord_id IN (5,8)
    ORDER BY p.landlord_id, t.id
""")
print('Tenant rents:')
for r in cur.fetchall(): print(r)
