import MySQLdb, MySQLdb.cursors
conn=MySQLdb.connect(host='localhost',user='root',passwd='',db='smartrent',charset='utf8mb4',cursorclass=MySQLdb.cursors.DictCursor)
cur=conn.cursor()

cur.execute('SELECT id, tenant_id, property_id, Amount, status, paid_on, month, category, method FROM payments ORDER BY paid_on DESC')
print('ALL PAYMENTS:')
for r in cur.fetchall(): print(r)

print()
cur.execute('SELECT id, tenant_id, property_id, bill_type, amount, amount_due, amount_paid, status, month FROM bills')
print('ALL BILLS:')
for r in cur.fetchall(): print(r)

print()
# Total income per landlord
cur.execute("""
    SELECT p.landlord_id, SUM(pay.Amount) as total
    FROM payments pay
    JOIN properties p ON p.id=pay.property_id
    WHERE LOWER(pay.status)='paid'
    GROUP BY p.landlord_id
""")
print('INCOME BY LANDLORD:')
for r in cur.fetchall(): print(r)

print()
# Check transactions table
cur.execute('SELECT COUNT(*) as c FROM transactions')
print('transactions count:', cur.fetchone())
cur.execute('SELECT * FROM transactions LIMIT 5')
for r in cur.fetchall(): print(r)
