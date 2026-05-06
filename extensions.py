# extensions.py
import os
from flask_mysqldb import MySQL
import MySQLdb

mysql = MySQL()


def get_db_connection():
    """
    Direct MySQLdb connection fallback.

    Use the same env vars as `config.Config` so both mysql.init_app and raw
    connections point at the same database.
    """
    host = os.getenv('MYSQL_HOST', 'localhost')
    user = os.getenv('MYSQL_USER', 'root')
    passwd = os.getenv('MYSQL_PASSWORD', '')
    db = os.getenv('MYSQL_DB', 'smartrent')
    port = int(os.getenv('MYSQL_PORT', '3306') or 3306)

    return MySQLdb.connect(
        host=host,
        user=user,
        passwd=passwd,
        db=db,
        port=port,
        charset='utf8mb4',
        cursorclass=MySQLdb.cursors.DictCursor,
    )


def get_conn_and_cursor():
    """
    Returns (conn, cur, should_close_conn).

    - Uses flask_mysqldb connection when available (inside request/app context)
    - Falls back to direct MySQLdb connection when flask connection is None
    """
    try:
        conn = mysql.connection
        if conn is not None:
            cur = conn.cursor(MySQLdb.cursors.DictCursor)
            return conn, cur, False
    except Exception:
        pass

    conn = get_db_connection()
    cur = conn.cursor(MySQLdb.cursors.DictCursor)
    return conn, cur, True


def ensure_lease_tables():
    """
    Best-effort creation of lease-related tables.

    This avoids runtime crashes when features are used on a fresh DB.
    """
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS leases (
              id INT AUTO_INCREMENT PRIMARY KEY,
              landlord_id INT NOT NULL,
              property_id INT NULL,
              unit_id INT NULL,
              tenant_id INT NULL,
              tenant_name VARCHAR(191) NULL,
              tenant_email VARCHAR(191) NULL,
              tenant_phone VARCHAR(64) NULL,
              unit_number VARCHAR(64) NULL,
              rent_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
              deposit_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
              start_date DATE NULL,
              end_date DATE NULL,
              terms TEXT NULL,
              status VARCHAR(32) NOT NULL DEFAULT 'Draft',
              sign_token VARCHAR(64) NULL,
              signed_name VARCHAR(191) NULL,
              signed_at DATETIME NULL,
              signed_ip VARCHAR(64) NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NULL,
              INDEX idx_leases_landlord (landlord_id),
              INDEX idx_leases_tenant (tenant_id),
              INDEX idx_leases_unit (unit_id),
              INDEX idx_leases_sign_token (sign_token)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        conn.commit()
    except Exception as e:
        # Do not crash app startup if DB user can't CREATE TABLE.
        print(f"ensure_lease_tables skipped: {e}")
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def ensure_units_tenant_column():
    """
    Best-effort addition of tenant_id column to units table.

    This allows units to be linked to tenant directly.
    """
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Check if tenant_id column exists
        cur.execute("""
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = 'units' AND COLUMN_NAME = 'tenant_id'
        """)
        
        if not cur.fetchone():
            # Column doesn't exist, add it
            cur.execute("""
                ALTER TABLE units
                ADD COLUMN tenant_id INT NULL
                AFTER status
            """)
            conn.commit()
            print("Added tenant_id column to units table")
        else:
            print("tenant_id column already exists in units table")
    except Exception as e:
        # Do not crash app startup if DB user can't ALTER TABLE.
        print(f"ensure_units_tenant_column skipped: {e}")
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def ensure_units_tenant_fk():
    """
    Best-effort foreign key fix for units.tenant_id.

    The project treats `units.tenant_id` as a reference to `tenant.id`, but some
    DBs were created with a FK pointing to `users.id`, which breaks assigning a
    tenant record to a unit.
    """
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Ensure tenant table exists before attempting FK changes
        cur.execute(
            """
            SELECT 1
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'tenant'
            LIMIT 1
            """
        )
        if not cur.fetchone():
            print("ensure_units_tenant_fk skipped: tenant table missing")
            return

        # Find any existing FK on units(tenant_id)
        cur.execute(
            """
            SELECT CONSTRAINT_NAME, REFERENCED_TABLE_NAME
            FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'units'
              AND COLUMN_NAME = 'tenant_id'
              AND REFERENCED_TABLE_NAME IS NOT NULL
            """
        )
        fk_rows = cur.fetchall() or []

        # If it's already referencing tenant, nothing to do
        for row in fk_rows:
            # row may be tuple when using a non-dict cursor
            constraint_name = row[0]
            referenced_table = row[1]
            if (referenced_table or '').lower() == 'tenant':
                print("units.tenant_id FK already references tenant")
                return

        # Drop FK if it points at users (or anything else)
        for row in fk_rows:
            constraint_name = row[0]
            referenced_table = row[1]
            try:
                cur.execute(f"ALTER TABLE units DROP FOREIGN KEY `{constraint_name}`")
                conn.commit()
                print(f"Dropped FK {constraint_name} (was referencing {referenced_table})")
            except Exception as e:
                conn.rollback()
                print(f"ensure_units_tenant_fk: couldn't drop FK {constraint_name}: {e}")

        # Ensure there's an index on tenant_id (required for FK)
        try:
            cur.execute(
                """
                SELECT 1
                FROM INFORMATION_SCHEMA.STATISTICS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'units'
                  AND COLUMN_NAME = 'tenant_id'
                LIMIT 1
                """
            )
            if not cur.fetchone():
                cur.execute("CREATE INDEX idx_units_tenant_id ON units(tenant_id)")
                conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"ensure_units_tenant_fk: index check/create skipped: {e}")

        # Add FK to tenant(id) if none exists now
        cur.execute(
            """
            SELECT 1
            FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'units'
              AND COLUMN_NAME = 'tenant_id'
              AND REFERENCED_TABLE_NAME = 'tenant'
            LIMIT 1
            """
        )
        if cur.fetchone():
            print("units.tenant_id FK already present (tenant)")
            return

        try:
            cur.execute(
                """
                ALTER TABLE units
                ADD CONSTRAINT fk_units_tenant_id
                FOREIGN KEY (tenant_id) REFERENCES tenant(id)
                ON DELETE SET NULL
                """
            )
            conn.commit()
            print("Added FK fk_units_tenant_id: units.tenant_id -> tenant.id")
        except Exception as e:
            conn.rollback()
            print(f"ensure_units_tenant_fk skipped: {e}")
    except Exception as e:
        print(f"ensure_units_tenant_fk skipped: {e}")
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass

def ensure_payments_due_date_penalty_columns():
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = 'payments'
              AND TABLE_SCHEMA = DATABASE()
              AND COLUMN_NAME IN ('due_date', 'penalty_amount')
            """
        )
        existing = {row['COLUMN_NAME'] for row in cur.fetchall()}

        if 'due_date' not in existing:
            cur.execute("ALTER TABLE payments ADD COLUMN due_date DATE NULL AFTER paid_on")
            conn.commit()
            print('Added due_date column to payments table')
        if 'penalty_amount' not in existing:
            cur.execute("ALTER TABLE payments ADD COLUMN penalty_amount DECIMAL(12,2) NOT NULL DEFAULT 0 AFTER due_date")
            conn.commit()
            print('Added penalty_amount column to payments table')
    except Exception as e:
        print(f"ensure_payments_due_date_penalty_columns skipped: {e}")
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def ensure_transactions_table():
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
              id INT AUTO_INCREMENT PRIMARY KEY,
              payment_id INT NULL,
              tenant_id INT NOT NULL,
              property_id INT NULL,
              amount DECIMAL(12,2) NOT NULL DEFAULT 0,
              status VARCHAR(32) NOT NULL DEFAULT 'Pending',
              method VARCHAR(64) NULL,
              reference VARCHAR(100) NULL,
              due_date DATE NULL,
              paid_on DATE NULL,
              penalty_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              INDEX idx_transactions_tenant (tenant_id),
              INDEX idx_transactions_property (property_id),
              INDEX idx_transactions_status (status),
              INDEX idx_transactions_paid_on (paid_on)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        conn.commit()
    except Exception as e:
        print(f"ensure_transactions_table skipped: {e}")
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def ensure_bills_amount_paid_column():
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'bills'
              AND COLUMN_NAME = 'amount_paid'
        """)
        if not cur.fetchone():
            cur.execute("ALTER TABLE bills ADD COLUMN amount_paid DECIMAL(12,2) NOT NULL DEFAULT 0 AFTER amount_due")
            conn.commit()
            print("Added amount_paid column to bills")
    except Exception as e:
        print(f"ensure_bills_amount_paid_column skipped: {e}")
        try:
            if conn: conn.rollback()
        except Exception:
            pass
    finally:
        try:
            if cur: cur.close()
        except Exception:
            pass
        try:
            if conn: conn.close()
        except Exception:
            pass


def ensure_lease_tenant_signature_columns():
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'leases'
              AND COLUMN_NAME IN ('tenant_signed_name','tenant_signed_at')
        """)
        existing = {r[0] if not isinstance(r, dict) else r['COLUMN_NAME'] for r in cur.fetchall()}
        if 'tenant_signed_name' not in existing:
            cur.execute("ALTER TABLE leases ADD COLUMN tenant_signed_name VARCHAR(191) NULL")
            conn.commit()
        if 'tenant_signed_at' not in existing:
            cur.execute("ALTER TABLE leases ADD COLUMN tenant_signed_at DATETIME NULL")
            conn.commit()
    except Exception as e:
        print(f"ensure_lease_tenant_signature_columns skipped: {e}")
        try:
            if conn: conn.rollback()
        except Exception:
            pass
    finally:
        try:
            if cur: cur.close()
        except Exception:
            pass
        try:
            if conn: conn.close()
        except Exception:
            pass


def ensure_maintenance_assigned_to_column():
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'maintenance_requests'
              AND COLUMN_NAME = 'assigned_to'
        """)
        if not cur.fetchone():
            cur.execute("""
                ALTER TABLE maintenance_requests
                ADD COLUMN assigned_to INT NULL
            """)
            conn.commit()
            print("Added assigned_to column to maintenance_requests")
    except Exception as e:
        print(f"ensure_maintenance_assigned_to_column skipped: {e}")
        try:
            if conn: conn.rollback()
        except Exception:
            pass
    finally:
        try:
            if cur: cur.close()
        except Exception:
            pass
        try:
            if conn: conn.close()
        except Exception:
            pass


def record_transaction(payment_id, tenant_id, property_id, amount, status, method=None, reference=None, due_date=None, paid_on=None, penalty_amount=0):
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO transactions
                (payment_id, tenant_id, property_id, amount, status, method, reference, due_date, paid_on, penalty_amount)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (payment_id, tenant_id, property_id, amount, status, method, reference, due_date, paid_on, penalty_amount)
        )
        conn.commit()
    except Exception as e:
        print(f"record_transaction skipped: {e}")
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass
