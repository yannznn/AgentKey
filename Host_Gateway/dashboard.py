import os
import sqlite3
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="Enterprise Gateway Live Monitor")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "enterprise_customers.db")


def get_db_connection():
    conn = sqlite3.connect(DB_FILE, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/", response_class=HTMLResponse)
def render_dashboard():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT customer_id, name, email, role, balance_myr, status FROM customers ORDER BY customer_id ASC")
        customers = cur.fetchall()

        cur.execute(
            "SELECT timestamp, risk_tier, tool_name, action_payload, auth_status, authorized_by FROM audit_logs ORDER BY log_id DESC LIMIT 8"
        )
        logs = cur.fetchall()
        conn.close()
    except Exception as e:
        return f"<h3 style='font-family:sans-serif;color:red;'>Database sync error: {e}</h3>"

    cust_rows = "".join([
        f"""<tr>
            <td><code>{c['customer_id']}</code></td>
            <td><b>{c['name']}</b></td>
            <td>{c['email']}</td>
            <td><span class='badge role-{c['role'].lower()}'>{c['role']}</span></td>
            <td class='balance'>RM {c['balance_myr']:,.2f}</td>
            <td><span class='badge status-{c['status'].lower()}'>{c['status']}</span></td>
        </tr>""" for c in customers
    ])

    log_rows = "".join([
        f"""<tr>
            <td>{l['timestamp']}</td>
            <td><span class='badge tier-{l['risk_tier'].lower()}'>{l['risk_tier']}</span></td>
            <td><code>{l['tool_name']}</code></td>
            <td>{l['action_payload']}</td>
            <td><span class='badge status-{'approved' if 'APPROVED' in l['auth_status'] else ('bypass' if 'BYPASS' in l['auth_status'] else 'denied')}'>{l['auth_status']}</span></td>
            <td><code class='signer-tag'>{l['authorized_by']}</code></td>
        </tr>""" for l in logs
    ])

    return f"""<!DOCTYPE html>
<html>
<head>
    <title>Enterprise Security Gateway - Hardware Gated Ledger</title>
    <meta http-equiv="refresh" content="2">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0b0f19; color: #f1f5f9; margin: 0; padding: 24px; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        h1 {{ font-size: 24px; color: #38bdf8; margin-bottom: 4px; display: flex; align-items: center; gap: 10px; }}
        p.subtitle {{ color: #64748b; font-size: 14px; margin-top: 0; margin-bottom: 24px; }}
        .live-dot {{ height: 10px; width: 10px; background-color: #22c55e; border-radius: 50%; display: inline-block; box-shadow: 0 0 8px #22c55e; }}
        .card {{ background: #131d31; border: 1px solid #1e293b; border-radius: 10px; padding: 20px; margin-bottom: 24px; }}
        h2 {{ font-size: 15px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; margin-top: 0; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 10px 14px; text-align: left; font-size: 14px; border-bottom: 1px solid #1e293b; }}
        th {{ color: #64748b; font-weight: 600; font-size: 13px; }}
        .balance {{ font-family: monospace; font-size: 15px; color: #38bdf8; font-weight: bold; }}
        .badge {{ padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; text-transform: uppercase; }}
        .signer-tag {{ color: #38bdf8; background: #082f49; padding: 2px 6px; border-radius: 4px; font-size: 12px; }}
        .role-admin {{ background: #7c3aed; color: #fff; }}
        .role-premium {{ background: #0284c7; color: #fff; }}
        .role-user {{ background: #334155; color: #cbd5e1; }}
        .status-active {{ background: #065f46; color: #34d399; }}
        .tier-low {{ background: #1e293b; color: #94a3b8; }}
        .tier-medium {{ background: #854d0e; color: #fde047; }}
        .tier-high, .tier-critical {{ background: #991b1b; color: #fca5a5; }}
        .status-approved {{ background: #065f46; color: #34d399; }}
        .status-bypass {{ background: #1e293b; color: #94a3b8; }}
        .status-denied {{ background: #7f1d1d; color: #fca5a5; }}
    </style>
</head>
<body>
    <div class="container">
        <h1><span class="live-dot"></span> Hardware-Gated Enterprise Node</h1>
        <p class="subtitle">Localhost HITL Verification Controller | Real-time SQLite Polling (2s)</p>

        <div class="card">
            <h2>Active Customer Ledger</h2>
            <table>
                <tr><th>ID</th><th>Customer Name</th><th>Email</th><th>Role</th><th>Balance</th><th>Status</th></tr>
                {cust_rows}
            </table>
        </div>

        <div class="card">
            <h2>Hardware Security Audit Trail</h2>
            <table>
                <tr><th>Timestamp</th><th>Risk Tier</th><th>Tool Invoked</th><th>Action Target</th><th>Gateway Verdict</th><th>Signer Identity</th></tr>
                {log_rows}
            </table>
        </div>
    </div>
</body>
</html>"""