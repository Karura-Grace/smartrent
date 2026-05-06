import MySQLdb, MySQLdb.cursors
conn=MySQLdb.connect(host='localhost',user='root',passwd='',db='smartrent',charset='utf8mb4',cursorclass=MySQLdb.cursors.DictCursor)
cur=conn.cursor()

# All transactions
cur.execute('SELECT id, payment_id, tenant_id, property_id, amount, status, paid_on FROM transactions ORDER BY paid_on DESC')
print('ALL TRANSACTIONS:')
for r in cur.fetchall(): print(r)

print()
# Income from payments vs transactions for landlord 8
cur.execute("""
    SELECT SUM(pay.Amount) as pay_total
    FROM payments pay JOIN properties p ON p.id=pay.property_id
    WHERE p.landlord_id=8 AND LOWER(pay.status)='paid'
    AND pay.paid_on >= '2026-05-01' AND pay.paid_on < '2026-06-01'
""")
print('payments income landlord 8 May:', cur.fetchone())

cur.execute("""
    SELECT SUM(tx.amount) as tx_total
    FROM transactions tx JOIN properties p ON p.id=tx.property_id
    WHERE p.landlord_id=8 AND LOWER(tx.status)='paid'
    AND tx.paid_on >= '2026-05-01' AND tx.paid_on < '2026-06-01'
""")
print('transactions income landlord 8 May:', cur.fetchone())

# bills amount_paid for landlord 8
cur.execute("""
    SELECT SUM(b.amount_paid) as billed_paid
    FROM bills b JOIN tenant t ON t.id=b.tenant_id
    JOIN properties p ON p.id=t.property_id
    WHERE p.landlord_id=8 AND b.month='May 2026'
""")
print('bills amount_paid landlord 8 May:', cur.fetchone())

# What is the expected rent for landlord 8 (total billed rent)
cur.execute("""
    SELECT SUM(b.amount) as total_billed
    FROM bills b JOIN tenant t ON t.id=b.tenant_id
    JOIN properties p ON p.id=t.property_id
    WHERE p.landlord_id=8 AND b.month='May 2026' AND LOWER(b.bill_type)='rent'
""")
print('total rent billed landlord 8 May:', cur.fetchone())
