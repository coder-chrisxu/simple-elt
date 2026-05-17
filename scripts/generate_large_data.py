"""
Generate large test data in Oracle for volume testing.

Usage: uv run python scripts/generate_large_data.py [--rows N] [--batch-size N]

Default: 10,000,000 rows in batches of 100,000.
"""
import argparse
import time

import oracledb

SOURCE_DSN = "source_user/SourcePass123@localhost:1521/XEPDB1"
TARGET_DSN = "target_user/TargetPass123@localhost:1521/XEPDB1"


def create_tables(source_conn, target_conn):
    src = source_conn.cursor()
    tgt = target_conn.cursor()

    # Only create if not exists
    src.execute("SELECT COUNT(*) FROM user_tables WHERE table_name = 'LARGE_EVENTS'")
    if src.fetchone()[0] == 0:
        src.execute("""
            CREATE TABLE large_events (
                event_id      NUMBER PRIMARY KEY,
                session_id    NUMBER NOT NULL,
                user_id       NUMBER NOT NULL,
                event_type    VARCHAR2(50) NOT NULL,
                payload       VARCHAR2(500),
                amount        NUMBER(12,2),
                currency      VARCHAR2(3),
                region        VARCHAR2(10),
                created_at    TIMESTAMP NOT NULL,
                is_processed  NUMBER(1) DEFAULT 0
            )
        """)
        print("Created large_events")
    else:
        print("large_events already exists")

    tgt.execute("SELECT COUNT(*) FROM user_tables WHERE table_name = 'STG_LARGE_EVENTS'")
    if tgt.fetchone()[0] == 0:
        tgt.execute("""
            CREATE TABLE stg_large_events (
                event_id      NUMBER,
                session_id    NUMBER,
                user_id       NUMBER,
                event_type    VARCHAR2(50),
                payload       VARCHAR2(500),
                amount        NUMBER(12,2),
                currency      VARCHAR2(3),
                region        VARCHAR2(10),
                created_at    TIMESTAMP,
                is_processed  NUMBER(1)
            )
        """)
        print("Created stg_large_events")
    else:
        print("stg_large_events already exists")

    src.close()
    tgt.close()


def generate_data(conn, total_rows, batch_size):
    cursor = conn.cursor()

    plsql = """
    DECLARE
        TYPE id_array     IS TABLE OF NUMBER INDEX BY PLS_INTEGER;
        TYPE sess_array   IS TABLE OF NUMBER INDEX BY PLS_INTEGER;
        TYPE user_array   IS TABLE OF NUMBER INDEX BY PLS_INTEGER;
        TYPE type_array   IS TABLE OF VARCHAR2(50) INDEX BY PLS_INTEGER;
        TYPE payload_arr  IS TABLE OF VARCHAR2(500) INDEX BY PLS_INTEGER;
        TYPE amt_array    IS TABLE OF NUMBER INDEX BY PLS_INTEGER;
        TYPE curr_array   IS TABLE OF VARCHAR2(3) INDEX BY PLS_INTEGER;
        TYPE region_arr   IS TABLE OF VARCHAR2(10) INDEX BY PLS_INTEGER;
        TYPE ts_array     IS TABLE OF TIMESTAMP INDEX BY PLS_INTEGER;
        TYPE proc_array   IS TABLE OF NUMBER(1) INDEX BY PLS_INTEGER;

        l_ids       id_array;
        l_sess      sess_array;
        l_users     user_array;
        l_types     type_array;
        l_payloads  payload_arr;
        l_amts      amt_array;
        l_currs     curr_array;
        l_regions   region_arr;
        l_ts        ts_array;
        l_proc      proc_array;

        l_start_id  NUMBER;
        l_batch     NUMBER;
        l_idx       NUMBER;
    BEGIN
        l_start_id := :start_id;
        l_batch := :batch_size;

        FOR i IN 1..l_batch LOOP
            l_ids(i)       := l_start_id + i - 1;
            l_sess(i)      := ROUND(DBMS_RANDOM.VALUE(1, 5000000));
            l_users(i)     := ROUND(DBMS_RANDOM.VALUE(1, 2000000));
            l_idx := MOD(i - 1, 8) + 1;
            l_types(i)     := CASE l_idx
                WHEN 1 THEN 'VIEW' WHEN 2 THEN 'CLICK' WHEN 3 THEN 'PURCHASE'
                WHEN 4 THEN 'ADD_TO_CART' WHEN 5 THEN 'LOGIN' WHEN 6 THEN 'LOGOUT'
                WHEN 7 THEN 'SEARCH' ELSE 'SHARE' END;
            l_payloads(i)  := 'event_payload_' || (l_start_id + i - 1);
            l_amts(i)      := ROUND(DBMS_RANDOM.VALUE(1, 9999), 2);
            l_idx := MOD(i - 1, 6) + 1;
            l_currs(i)     := CASE l_idx
                WHEN 1 THEN 'USD' WHEN 2 THEN 'EUR' WHEN 3 THEN 'GBP'
                WHEN 4 THEN 'JPY' WHEN 5 THEN 'CAD' ELSE 'AUD' END;
            l_idx := MOD(i - 1, 6) + 1;
            l_regions(i)   := CASE l_idx
                WHEN 1 THEN 'US' WHEN 2 THEN 'EU' WHEN 3 THEN 'UK'
                WHEN 4 THEN 'JP' WHEN 5 THEN 'APAC' ELSE 'LATAM' END;
            l_ts(i)        := TO_TIMESTAMP('2025-01-01 00:00:00','YYYY-MM-DD HH24:MI:SS')
                              + NUMTODSINTERVAL(MOD(i, 31536000), 'SECOND');
            l_proc(i)      := MOD(i, 10);
        END LOOP;

        FORALL i IN 1..l_batch
            INSERT INTO large_events (event_id, session_id, user_id, event_type,
                                       payload, amount, currency, region, created_at, is_processed)
            VALUES (l_ids(i), l_sess(i), l_users(i), l_types(i),
                    l_payloads(i), l_amts(i), l_currs(i), l_regions(i), l_ts(i), l_proc(i));

        COMMIT;
    END;
    """

    batches = (total_rows + batch_size - 1) // batch_size
    start_time = time.time()

    # Find where we left off (if resuming)
    try:
        cursor.execute("SELECT NVL(MAX(event_id), 0) FROM large_events")
        max_id = cursor.fetchone()[0]
    except Exception:
        max_id = 0
    start_batch = max_id // batch_size

    if start_batch > 0:
        print(f"  Resuming from batch {start_batch + 1} (existing {max_id:,} rows)")

    for i in range(start_batch, batches):
        start_id = i * batch_size + 1
        actual_batch = min(batch_size, total_rows - i * batch_size)

        for attempt in range(3):
            try:
                cursor.execute(plsql, {"start_id": start_id, "batch_size": actual_batch})
                break
            except Exception as e:
                if attempt < 2:
                    print(f"  Connection lost, waiting 10s and reconnecting... ({attempt+1}/3)")
                    time.sleep(10)
                    try:
                        conn.close()
                    except Exception:
                        pass
                    conn = oracledb.connect(
                        user="source_user", password="SourcePass123",
                        host="localhost", port=1521, service_name="XEPDB1"
                    )
                    cursor = conn.cursor()
                else:
                    raise

        rows_done = min((i + 1) * batch_size, total_rows)
        elapsed = time.time() - start_time
        rate = rows_done / elapsed if elapsed > 0 else 0
        print(f"  Batch {i+1}/{batches}: {rows_done:,} rows inserted "
              f"({elapsed:.1f}s, {rate:,.0f} rows/s)")

    cursor.close()
    total_time = time.time() - start_time
    print(f"\n  Total: {total_rows:,} rows in {total_time:.1f}s "
          f"({total_rows/total_time:,.0f} rows/s)")
    return conn


def main():
    parser = argparse.ArgumentParser(description="Generate large test data for ELT framework")
    parser.add_argument("--rows", type=int, default=10_000_000, help="Total rows to generate")
    parser.add_argument("--batch-size", type=int, default=100_000, help="Rows per PL/SQL batch")
    args = parser.parse_args()

    print(f"Generating {args.rows:,} rows (batch size: {args.batch_size:,})...")
    print()

    source_conn = oracledb.connect(
        user="source_user", password="SourcePass123",
        host="localhost", port=1521, service_name="XEPDB1"
    )
    target_conn = oracledb.connect(
        user="target_user", password="TargetPass123",
        host="localhost", port=1521, service_name="XEPDB1"
    )

    print("Creating tables...")
    create_tables(source_conn, target_conn)

    print(f"\nInserting {args.rows:,} rows into large_events...")
    source_conn = generate_data(source_conn, args.rows, args.batch_size)

    # Verify
    cursor = source_conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM large_events")
    count = cursor.fetchone()[0]
    print(f"\nVerification: large_events has {count:,} rows")
    cursor.close()

    source_conn.close()
    target_conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
