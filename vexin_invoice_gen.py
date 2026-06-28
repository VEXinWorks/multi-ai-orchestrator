#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
e-Kuatia compatible invoice generator in JSON format.

Usage example:
    python3 vexin_invoice_gen.py --ruc 12345678 --timbrado 10 --iva 1.10 --total 100.00

"""

import argparse
from datetime import date
import json

def generate_invoice(ruc: str, timbrado: float, iva: float, total: float) -> dict:
    """
    Generate a Paraguay electronic invoice (factura electrónica).

    Args:
        ruc (str): Taxpayer's RUC.
        timbrado (float): Timbrado value.
        iva (float): IVA percentage (e.g. 1.10 for 10%).
        total (float): Invoice total.

    Returns:
        dict: JSON-formatted invoice dictionary.
    """
    try:
        invoice = {
            "ruc": ruc,
            "timbrado": timbrado,
            "iva": iva,
            "total": total,
            "fecha_emision": date.today().isoformat(),
            "detalle": [
                {"descripcion": "Product 1", "cantidad": 2, "precio_unitario": 10.00},
                {"descripcion": "Product 2", "cantidad": 3, "precio_unitario": 20.00}
            ]
        }
        return invoice
    except Exception as e:
        print(f"Error generating invoice: {e}")
        return None

def main():
    parser = argparse.ArgumentParser(description="Generate an e-Kuatia compatible invoice.")
    parser.add_argument("--ruc", help="Taxpayer's RUC.", required=True)
    parser.add_argument("--timbrado", type=float, help="Timbrado value.", required=True)
    parser.add_argument("--iva", type=float, help="IVA percentage (e.g. 1.10 for 10 percent).", required=True)
    parser.add_argument("--total", type=float, help="Invoice total.", required=True)
    args = parser.parse_args()

    invoice = generate_invoice(args.ruc, args.timbrado, args.iva, args.total)

    if invoice:
        print("Human-readable format:")
        for key, value in invoice.items():
            print(f"{key}: {value}")

        print("\nMachine-readable format (JSON):")
        json_output = json.dumps(invoice, indent=4)
        print(json_output)

if __name__ == "__main__":
    main()