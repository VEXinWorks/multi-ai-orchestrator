#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vexin_customer_crm.py — Simple CRM for VEXinWorks

Tracks customers, quotes, and follow-ups in SQLite. Designed for a small
Paraguay business doing 3D printing and AI services.

Database: /home/vexin/projects/crm.db (auto-created)

Usage:
    python3 vexin_customer_crm.py add-customer --name "Juan Perez" --phone "+595981234567"
    python3 vexin_customer_crm.py list-customers
    python3 vexin_customer_crm.py add-quote --customer-id 1 --description "20 keychains" --amount 150000
    python3 vexin_customer_crm.py list-quotes
    python3 vexin_customer_crm.py mark-follow-up-done --quote-id 1
    python3 vexin_customer_crm.py search --query "juan"
    python3 vexin_customer_crm.py stats
"""

import argparse
import sqlite3
import sys
from datetime import datetime, date
from typing import List, Dict, Optional


DB_PATH = "/home/vexin/projects/crm.db"


def connect_db() -> sqlite3.Connection:
    """Connect to SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def create_tables(conn: sqlite3.Connection) -> None:
    """Create customers, quotes, and follow_ups tables if they don't exist."""
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT,
            email TEXT,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS quotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            amount_pyg INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            follow_up_done INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers (id)
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS follow_ups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quote_id INTEGER NOT NULL,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (quote_id) REFERENCES quotes (id)
        )
    ''')
    conn.commit()


def add_customer(conn: sqlite3.Connection, name: str, phone: str = None,
                 email: str = None, notes: str = None) -> int:
    """Add a new customer. Returns customer ID."""
    cur = conn.cursor()
    cur.execute(
        'INSERT INTO customers (name, phone, email, notes) VALUES (?, ?, ?, ?)',
        (name, phone, email, notes),
    )
    conn.commit()
    return cur.lastrowid


def list_customers(conn: sqlite3.Connection) -> List[Dict]:
    """List all customers."""
    cur = conn.cursor()
    cur.execute('SELECT * FROM customers ORDER BY created_at DESC')
    return [dict(row) for row in cur.fetchall()]


def add_quote(conn: sqlite3.Connection, customer_id: int, description: str,
              amount_pyg: int = 0) -> int:
    """Add a quote for a customer. Returns quote ID."""
    cur = conn.cursor()
    cur.execute(
        'INSERT INTO quotes (customer_id, description, amount_pyg) VALUES (?, ?, ?)',
        (customer_id, description, amount_pyg),
    )
    conn.commit()
    return cur.lastrowid


def list_quotes(conn: sqlite3.Connection, customer_id: Optional[int] = None) -> List[Dict]:
    """List quotes, optionally filtered by customer."""
    cur = conn.cursor()
    if customer_id:
        cur.execute(
            'SELECT q.*, c.name as customer_name FROM quotes q '
            'JOIN customers c ON q.customer_id = c.id '
            'WHERE q.customer_id = ? ORDER BY q.created_at DESC',
            (customer_id,),
        )
    else:
        cur.execute(
            'SELECT q.*, c.name as customer_name FROM quotes q '
            'JOIN customers c ON q.customer_id = c.id '
            'ORDER BY q.created_at DESC'
        )
    return [dict(row) for row in cur.fetchall()]


def mark_follow_up_done(conn: sqlite3.Connection, quote_id: int, notes: str = None) -> None:
    """Mark a quote's follow-up as done and add optional notes."""
    cur = conn.cursor()
    cur.execute('UPDATE quotes SET follow_up_done = 1 WHERE id = ?', (quote_id,))
    if notes:
        cur.execute(
            'INSERT INTO follow_ups (quote_id, notes) VALUES (?, ?)',
            (quote_id, notes),
        )
    conn.commit()


def search_customers(conn: sqlite3.Connection, query: str) -> List[Dict]:
    """Search customers by name, phone, or email."""
    cur = conn.cursor()
    q = f'%{query}%'
    cur.execute(
        'SELECT * FROM customers WHERE name LIKE ? OR phone LIKE ? OR email LIKE ?',
        (q, q, q),
    )
    return [dict(row) for row in cur.fetchall()]


def get_stats(conn: sqlite3.Connection) -> Dict:
    """Get CRM statistics."""
    cur = conn.cursor()
    stats = {}
    cur.execute('SELECT COUNT(*) FROM customers')
    stats['total_customers'] = cur.fetchone()[0]
    cur.execute('SELECT COUNT(*) FROM quotes')
    stats['total_quotes'] = cur.fetchone()[0]
    cur.execute('SELECT COUNT(*) FROM quotes WHERE status = "pending"')
    stats['pending_quotes'] = cur.fetchone()[0]
    cur.execute('SELECT COUNT(*) FROM quotes WHERE follow_up_done = 0')
    stats['open_follow_ups'] = cur.fetchone()[0]
    cur.execute('SELECT COALESCE(SUM(amount_pyg), 0) FROM quotes')
    stats['total_quoted_pyg'] = cur.fetchone()[0]
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="VEXinWorks CRM — customers, quotes, follow-ups",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Database: {DB_PATH}

Examples:
  %(prog)s add-customer --name "Juan" --phone "+595981234567" --email juan@x.com
  %(prog)s add-quote --customer-id 1 --description "20 keychains" --amount 150000
  %(prog)s list-customers
  %(prog)s list-quotes
  %(prog)s mark-follow-up-done --quote-id 1 --notes "WhatsApped, will pick up tomorrow"
  %(prog)s search --query "juan"
  %(prog)s stats
        """,
    )
    subparsers = parser.add_subparsers(dest='command', required=True)

    # add-customer
    p = subparsers.add_parser('add-customer', help='Add new customer')
    p.add_argument('--name', required=True, help='Customer full name')
    p.add_argument('--phone', help='Phone number (Paraguay format: +595981234567)')
    p.add_argument('--email', help='Email address')
    p.add_argument('--notes', help='Free-form notes')

    # list-customers
    subparsers.add_parser('list-customers', help='List all customers')

    # add-quote
    p = subparsers.add_parser('add-quote', help='Add a quote for a customer')
    p.add_argument('--customer-id', type=int, required=True)
    p.add_argument('--description', required=True, help='What is the quote for')
    p.add_argument('--amount', type=int, default=0, help='Amount in PYG (₲)')

    # list-quotes
    p = subparsers.add_parser('list-quotes', help='List all quotes')
    p.add_argument('--customer-id', type=int, help='Filter by customer ID')

    # mark-follow-up-done
    p = subparsers.add_parser('mark-follow-up-done', help='Mark follow-up as done')
    p.add_argument('--quote-id', type=int, required=True)
    p.add_argument('--notes', help='What happened in the follow-up')

    # search
    p = subparsers.add_parser('search', help='Search customers')
    p.add_argument('--query', required=True, help='Search term (name, phone, email)')

    # stats
    subparsers.add_parser('stats', help='Show CRM statistics')

    args = parser.parse_args()
    conn = connect_db()
    create_tables(conn)

    if args.command == 'add-customer':
        cid = add_customer(conn, args.name, args.phone, args.email, args.notes)
        print(f"✓ Customer added with ID {cid}")
    elif args.command == 'list-customers':
        customers = list_customers(conn)
        if not customers:
            print("No customers yet. Add one with: add-customer --name '...'", file=sys.stderr)
        for c in customers:
            print(f"  [{c['id']}] {c['name']} | {c.get('phone') or 'no phone'} | {c.get('email') or 'no email'}")
    elif args.command == 'add-quote':
        qid = add_quote(conn, args.customer_id, args.description, args.amount)
        print(f"✓ Quote added with ID {qid}")
        if args.amount:
            print(f"  Amount: ₲{args.amount:,}")
    elif args.command == 'list-quotes':
        quotes = list_quotes(conn, args.customer_id)
        for q in quotes:
            status = "✓" if q.get('follow_up_done') else "○"
            amount = f"₲{q['amount_pyg']:,}" if q.get('amount_pyg') else 'no amount'
            print(f"  {status} [{q['id']}] {q['customer_name']}: {q['description']} ({amount})")
    elif args.command == 'mark-follow-up-done':
        mark_follow_up_done(conn, args.quote_id, args.notes)
        print(f"✓ Follow-up marked done for quote {args.quote_id}")
    elif args.command == 'search':
        results = search_customers(conn, args.query)
        for c in results:
            print(f"  [{c['id']}] {c['name']} | {c.get('phone') or 'no phone'} | {c.get('email') or 'no email'}")
    elif args.command == 'stats':
        stats = get_stats(conn)
        print(f"\n📊 VEXinWorks CRM Stats")
        print(f"  Total customers:    {stats['total_customers']}")
        print(f"  Total quotes:       {stats['total_quotes']}")
        print(f"  Pending quotes:     {stats['pending_quotes']}")
        print(f"  Open follow-ups:    {stats['open_follow_ups']}")
        print(f"  Total quoted:       ₲{stats['total_quoted_pyg']:,}")

    conn.close()


if __name__ == '__main__':
    main()