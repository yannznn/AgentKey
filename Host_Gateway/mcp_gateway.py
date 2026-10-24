import os
import sys
import time
import sqlite3
import serial
import serial.tools.list_ports
from pathlib import Path
from mcp.server.fastmcp import FastMCP

# 1. Initialize FastMCP
mcp = FastMCP("EnterpriseCustomerGateway")

# Cross-platform path handling
BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "enterprise_customers.db"
BAUD_RATE = 115200


def get_universal_serial_port() -> str:
    """
    Auto-detects the ESP32-S3 port across Windows (COMx), Linux (/dev/tty*),
    and macOS (/dev/cu.*). Supports manual override via environment variable.
    """
    # 1. Environment variable override (highest priority)
    env_port = os.environ.get("GATEWAY_COM_PORT")
    if env_port:
        sys.stderr.write(f"[SERIAL] Using explicit port from environment: {env_port}\n")
        return env_port

    # 2. Known USB Vendor/Product IDs for ESP32-S3 (Espressif native USB CDC & common bridges)
    # Espressif native CDC: VID 0x303A, PID 0x1001
    # CH340: VID 0x1A86, CP210x: VID 0x10C4, FTDI: VID 0x0403
    KNOWN_VIDS = {0x303A, 0x1A86, 0x10C4, 0x0403}

    available_ports = list(serial.tools.list_ports.comports())

    # Priority A: Check hardware VID/PID matches
    for p in available_ports:
        if p.vid in KNOWN_VIDS:
            sys.stderr.write(f"[SERIAL] Found hardware token by USB VID:PID -> {p.device} ({p.description})\n")
            return p.device

    # Priority B: Check string identifiers in description or hardware ID
    keywords = ["esp32", "usb jtag", "ch340", "cp210", "uart", "serial"]
    for p in available_ports:
        search_blob = f"{p.device} {p.description or ''} {p.hwid or ''}".lower()
        if any(kw in search_blob for kw in keywords):
            # On macOS, prefer /dev/cu.* over /dev/tty.* to avoid carrier-detect blocking
            if sys.platform == "darwin" and "/dev/tty." in p.device:
                cu_candidate = p.device.replace("/dev/tty.", "/dev/cu.")
                if Path(cu_candidate).exists():
                    return cu_candidate
            return p.device

    # Priority C: OS-specific default fallbacks
    if sys.platform.startswith("win"):
        return "COM11"
    elif sys.platform == "darwin":
        return "/dev/cu.usbmodem1"
    else:
        return "/dev/ttyACM0"


SERIAL_PORT = get_universal_serial_port()


# -------------------------------------------------------------
# Database Setup & Audit Logging
# -------------------------------------------------------------

def init_customer_db():
    conn = sqlite3.connect(str(DB_FILE), timeout=5.0)
    cursor = conn.cursor()

    cursor.execute("""
                   CREATE TABLE IF NOT EXISTS customers
                   (
                       customer_id
                       INTEGER
                       PRIMARY
                       KEY,
                       name
                       TEXT
                       NOT
                       NULL,
                       email
                       TEXT
                       UNIQUE
                       NOT
                       NULL,
                       role
                       TEXT
                       NOT
                       NULL
                       DEFAULT
                       'USER',
                       balance_myr
                       REAL
                       NOT
                       NULL,
                       status
                       TEXT
                       NOT
                       NULL
                       DEFAULT
                       'ACTIVE'
                   )
                   """)

    cursor.execute("""
                   CREATE TABLE IF NOT EXISTS audit_logs
                   (
                       log_id
                       INTEGER
                       PRIMARY
                       KEY
                       AUTOINCREMENT,
                       timestamp
                       TEXT
                       NOT
                       NULL,
                       risk_tier
                       TEXT
                       NOT
                       NULL,
                       tool_name
                       TEXT
                       NOT
                       NULL,
                       action_payload
                       TEXT,
                       auth_status
                       TEXT
                       NOT
                       NULL,
                       authorized_by
                       TEXT
                       NOT
                       NULL
                       DEFAULT
                       'SYSTEM_AUTONOMOUS'
                   )
                   """)

    cursor.execute("PRAGMA table_info(audit_logs)")
    columns = [col[1] for col in cursor.fetchall()]
    if "authorized_by" not in columns:
        cursor.execute("ALTER TABLE audit_logs ADD COLUMN authorized_by TEXT NOT NULL DEFAULT 'SYSTEM_AUTONOMOUS'")

    cursor.execute("""
                   INSERT
                   OR IGNORE INTO customers VALUES
        (1001, 'Alice Tan', 'alice.tan@enterprise.my', 'PREMIUM', 15400.50, 'ACTIVE'),
        (1002, 'Bob Chen', 'bob.chen@cloudcorp.com', 'USER', 2300.00, 'ACTIVE'),
        (1003, 'David Lee', 'david.lee@cybervault.io', 'ADMIN', 89500.00, 'ACTIVE'),
        (1004, 'Siti Nurhaliza', 'siti@fintech.my', 'USER', 450.20, 'ACTIVE')
                   """)

    conn.commit()
    conn.close()


init_customer_db()


def log_audit(risk_tier: str, tool_name: str, payload: str, status: str, authorized_by: str = "SYSTEM_AUTONOMOUS"):
    try:
        conn = sqlite3.connect(str(DB_FILE), timeout=5.0)
        cursor = conn.cursor()
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
                       INSERT INTO audit_logs (timestamp, risk_tier, tool_name, action_payload, auth_status,
                                               authorized_by)
                       VALUES (?, ?, ?, ?, ?, ?)
                       """, (timestamp, risk_tier, tool_name, payload, status, authorized_by))
        conn.commit()
        conn.close()
    except Exception as e:
        sys.stderr.write(f"[AUDIT ERROR] {e}\n")
        sys.stderr.flush()


# -------------------------------------------------------------
# Hardware Verification Handshake
# -------------------------------------------------------------

def request_hardware_approval(action_label: str, timeout: int = 15) -> tuple[bool, str]:
    try:
        # Cross-platform serial open with DTR/RTS suppression to avoid unintended reboots
        ser = serial.Serial()
        ser.port = SERIAL_PORT
        ser.baudrate = BAUD_RATE
        ser.timeout = 1
        ser.dtr = False
        ser.rts = False
        ser.open()

        # Allow MCU serial link to settle
        time.sleep(1.2)

        payload = f"AUTH_REQ:{action_label[:14]}\n"
        ser.write(payload.encode("utf-8"))
        sys.stderr.write(f"\n[SECURITY GATEWAY] Risk Threshold Exceeded -> Gated by ESP32: '{action_label}'\n")
        sys.stderr.write("[SECURITY GATEWAY] Awaiting physical verification on hardware dongle...\n")
        sys.stderr.flush()

        start_time = time.time()
        while time.time() - start_time < timeout:
            if ser.in_waiting > 0:
                resp = ser.readline().decode("utf-8", errors="ignore").strip()
                sys.stderr.write(f"[HARDWARE DONGLE] Response: {resp}\n")
                sys.stderr.flush()

                if resp.startswith("AUTH_OK"):
                    ser.close()
                    parts = resp.split(":", 1)
                    signer = parts[1] if len(parts) > 1 else "ESP32_TOUCH_TOKEN"
                    return True, signer
                elif resp.startswith("AUTH_TIMEOUT") or resp.startswith("AUTH_FAIL"):
                    ser.close()
                    return False, "HARDWARE_TIMEOUT"
            time.sleep(0.05)

        ser.close()
        sys.stderr.write("[SECURITY GATEWAY] Authorization timed out.\n")
        sys.stderr.flush()
        return False, "GATEWAY_TIMEOUT"
    except Exception as e:
        sys.stderr.write(f"[GATEWAY ERROR] Serial communication failed on {SERIAL_PORT}: {e}\n")
        sys.stderr.flush()
        return False, "SERIAL_IO_ERROR"


# =============================================================
# TOOLS: TIER 1, 2, & 3
# =============================================================

@mcp.tool()
def search_customer(query: str) -> str:
    """[LOW RISK] Search customer records by name or email keyword."""
    log_audit("LOW", "search_customer", f"query='{query}'", "ALLOWED_BYPASS", "SYSTEM_AUTONOMOUS")
    conn = sqlite3.connect(str(DB_FILE), timeout=5.0)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT customer_id, name, email, role, balance_myr, status FROM customers WHERE name LIKE ? OR email LIKE ?",
        (f"%{query}%", f"%{query}%")
    )
    results = cursor.fetchall()
    conn.close()
    if not results:
        return f"No customer records found matching '{query}'."
    return f"Search Results: {results}"


@mcp.tool()
def get_customer(customer_id: int) -> str:
    """[LOW RISK] Fetch full profile details of a single customer by their ID."""
    log_audit("LOW", "get_customer", f"customer_id={customer_id}", "ALLOWED_BYPASS", "SYSTEM_AUTONOMOUS")
    conn = sqlite3.connect(str(DB_FILE), timeout=5.0)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM customers WHERE customer_id = ?", (customer_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return f"Customer ID {customer_id} not found."
    return f"Customer Record: ID={row[0]} | Name={row[1]} | Email={row[2]} | Role={row[3]} | Balance=RM{row[4]:.2f} | Status={row[5]}"


@mcp.tool()
def create_customer(customer_id: int, name: str, email: str, initial_balance: float = 0.0) -> str:
    """[DYNAMIC RISK] Register a customer. Initial balance > 0 requires physical confirmation."""
    payload = f"id={customer_id}, name='{name}', bal={initial_balance:.2f}"
    is_high_risk = initial_balance > 0.0
    signer_id = "SYSTEM_AUTONOMOUS"

    if is_high_risk:
        label = f"MINT_{customer_id}"
        approved, signer_id = request_hardware_approval(label)
        if not approved:
            log_audit("HIGH", "create_customer", payload, "DENIED_HARDWARE_REJECTED", "REJECTED")
            return f"REJECTED: Account creation with initial funds (RM {initial_balance:.2f}) requires physical verification."

    conn = sqlite3.connect(str(DB_FILE), timeout=5.0)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO customers (customer_id, name, email, balance_myr) VALUES (?, ?, ?, ?)",
            (customer_id, name, email, initial_balance)
        )
        conn.commit()
        tier = "HIGH" if is_high_risk else "MEDIUM"
        status = "APPROVED_HARDWARE_SIGN" if is_high_risk else "ALLOWED_BYPASS"
        log_audit(tier, "create_customer", payload, status, signer_id)
        return f"SUCCESS: Created customer {customer_id} for '{name}' with balance RM {initial_balance:.2f}. Signed by [{signer_id}]."
    except sqlite3.IntegrityError:
        log_audit("MEDIUM" if not is_high_risk else "HIGH", "create_customer", payload, "REJECTED_DUPLICATE", signer_id)
        return f"ERROR: Customer ID {customer_id} or email '{email}' already exists."
    finally:
        conn.close()


@mcp.tool()
def update_customer_balance(customer_id: int, new_balance: float) -> str:
    """[HIGH RISK] Modify account balance. Requires physical confirmation."""
    label = f"BAL_{customer_id}"
    payload = f"customer_id={customer_id}, new_balance={new_balance:.2f}"

    approved, signer_id = request_hardware_approval(label)
    if not approved:
        log_audit("HIGH", "update_customer_balance", payload, "DENIED_HARDWARE_REJECTED", "REJECTED")
        return f"REJECTED: Physical confirmation failed. Account {customer_id} balance was NOT altered."

    conn = sqlite3.connect(str(DB_FILE), timeout=5.0)
    cursor = conn.cursor()
    cursor.execute("UPDATE customers SET balance_myr = ? WHERE customer_id = ?", (new_balance, customer_id))
    conn.commit()
    conn.close()

    log_audit("HIGH", "update_customer_balance", payload, "APPROVED_HARDWARE_SIGN", signer_id)
    return f"SUCCESS: Updated Customer {customer_id} balance to RM {new_balance:.2f}. Signed by [{signer_id}]."


@mcp.tool()
def delete_customer(customer_id: int) -> str:
    """[CRITICAL RISK] Irreversibly drop customer record. Requires physical confirmation."""
    label = f"DEL_{customer_id}"
    payload = f"customer_id={customer_id}"

    approved, signer_id = request_hardware_approval(label)
    if not approved:
        log_audit("CRITICAL", "delete_customer", payload, "DENIED_HARDWARE_REJECTED", "REJECTED")
        return f"REJECTED: Physical confirmation failed. Customer {customer_id} was NOT deleted."

    conn = sqlite3.connect(str(DB_FILE), timeout=5.0)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM customers WHERE customer_id = ?", (customer_id,))
    rows_affected = cursor.rowcount
    conn.commit()
    conn.close()

    if rows_affected > 0:
        log_audit("CRITICAL", "delete_customer", payload, "APPROVED_HARDWARE_SIGN", signer_id)
        return f"SUCCESS: Customer record {customer_id} deleted permanently. Signed by [{signer_id}]."
    return f"NOTICE: Customer ID {customer_id} did not exist."


@mcp.tool()
def change_customer_role(customer_id: int, new_role: str) -> str:
    """[CRITICAL RISK] Privilege Escalation: Grant ADMIN or VIP role. Requires physical confirmation."""
    label = f"ROLE_{customer_id}"
    payload = f"customer_id={customer_id}, new_role='{new_role.upper()}'"

    approved, signer_id = request_hardware_approval(label)
    if not approved:
        log_audit("CRITICAL", "change_customer_role", payload, "DENIED_HARDWARE_REJECTED", "REJECTED")
        return f"REJECTED: Hardware verification declined. Role for {customer_id} remains unchanged."

    conn = sqlite3.connect(str(DB_FILE), timeout=5.0)
    cursor = conn.cursor()
    cursor.execute("UPDATE customers SET role = ? WHERE customer_id = ?", (new_role.upper(), customer_id))
    conn.commit()
    conn.close()

    log_audit("CRITICAL", "change_customer_role", payload, "APPROVED_HARDWARE_SIGN", signer_id)
    return f"SUCCESS: Customer {customer_id} role elevated to '{new_role.upper()}'. Signed by [{signer_id}]."


@mcp.tool()
def export_customer_data() -> str:
    """[CRITICAL RISK] Full PII ledger dump. Requires physical confirmation."""
    approved, signer_id = request_hardware_approval("EXPORT_PII")
    if not approved:
        log_audit("CRITICAL", "export_customer_data", "all_records", "DENIED_HARDWARE_REJECTED", "REJECTED")
        return "REJECTED: Data export blocked. Physical presence not proven."

    conn = sqlite3.connect(str(DB_FILE), timeout=5.0)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM customers")
    rows = cursor.fetchall()
    conn.close()

    log_audit("CRITICAL", "export_customer_data", "all_records", "APPROVED_HARDWARE_SIGN", signer_id)
    return f"AUTHORIZED EXPORT (PII Ledger Dump): {rows}"


@mcp.tool()
def backup_database() -> str:
    """[HIGH RISK] Snapshot database state. Requires physical confirmation."""
    approved, signer_id = request_hardware_approval("BACKUP_DB")
    if not approved:
        log_audit("HIGH", "backup_database", "snapshot", "DENIED_HARDWARE_REJECTED", "REJECTED")
        return "REJECTED: Backup initiation denied by hardware dongle."

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    backup_filename = BASE_DIR / f"backup_{timestamp}.db"

    src = sqlite3.connect(str(DB_FILE))
    dst = sqlite3.connect(str(backup_filename))
    src.backup(dst)
    dst.close()
    src.close()

    log_audit("HIGH", "backup_database", f"file='{backup_filename.name}'", "APPROVED_HARDWARE_SIGN", signer_id)
    return f"SUCCESS: Database snapshot created -> {backup_filename}"


if __name__ == "__main__":
    mcp.run(transport="stdio")