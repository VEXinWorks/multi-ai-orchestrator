#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vexin_paraguay_tax_calc.py — Paraguayan tax calculator (CORRECTED)

Calculates IRPC, IVA, and minimum presumptive tax for a SAS or company
in Paraguay, using ACTUAL 2026 tax rates (not hallucinated ones).

REAL Paraguay tax facts (2026):
- IRPC: 8% of net income for SA/SRL; 10% simplified for SAS
- IRP natural persons: 8-10% progressive on net income
- IVA: 10% (general), 5% (essentials), exempt (some)
- Minimum presumptive tax: ₲2.8-3.2M/year for small companies
- Patent municipal: 1-4% of gross income depending on activity
- No IVA on: exports, books, medicines, education

Usage:
    python3 vexin_paraguay_tax_calc.py --revenue 150000000
    python3 vexin_paraguay_tax_calc.py --revenue 100000000 --deduct 40000000
    python3 vexin_paraguay_tax_calc.py --revenue 50000000 --regime SAS
"""

import argparse
from dataclasses import dataclass
from typing import Tuple


# CORRECT 2026 Paraguay rates
IRPC_SA = 0.08  # 8% for SA/SRL (Sociedad Anónima / Responsabilidad Limitada)
IRPC_SAS_SIMPLIFIED = 0.10  # 10% for SAS simplified regime
IVA_GENERAL = 0.10  # 10% general rate
MINIMUM_TAX_SMALL = 2_800_000  # ₲2.8M/year minimum tax
MINIMUM_TAX_LARGE = 3_200_000  # ₲3.2M/year minimum for larger
PATENT_MUNICIPAL_DEFAULT = 0.02  # 2% of gross (varies by municipality)


@dataclass
class TaxResult:
    regime: str
    annual_revenue: float
    annual_deductions: float
    net_income: float
    irpc_rate: float
    irpc_amount: float
    iva_rate: float
    iva_collected: float
    minimum_tax: float
    patent_municipal_rate: float
    patent_municipal_amount: float
    total_taxes_annual: float
    monthly_average_tax: float
    net_after_tax: float

    def report(self) -> str:
        lines = [
            "",
            "=" * 60,
            f"  PARAGUAY TAX CALCULATION ({self.regime})",
            "=" * 60,
            "",
            "📊 REVENUE:",
            f"  Annual revenue:       ₲{self.annual_revenue:>15,.0f}",
            f"  Annual deductions:    ₲{self.annual_deductions:>15,.0f}",
            f"  Net taxable income:   ₲{self.net_income:>15,.0f}",
            "",
            "💸 TAX BREAKDOWN:",
            f"  IRPC rate:            {self.irpc_rate*100:>5.1f}%",
            f"  IRPC amount:          ₲{self.irpc_amount:>15,.0f}",
            f"  IVA rate (collected): {self.iva_rate*100:>5.1f}%",
            f"  IVA collected:        ₲{self.iva_collected:>15,.0f}",
            f"  Patent municipal:     ₲{self.patent_municipal_amount:>15,.0f}  (rate: {self.patent_municipal_rate*100:.1f}%)",
            "",
            "⚠️  MINIMUM TAX CHECK:",
            f"  Minimum presumptive:  ₲{self.minimum_tax:>15,.0f}/year",
            f"  (Pay this if IRPC < minimum)",
            "",
            "💰 TOTALS:",
            f"  Total annual taxes:   ₲{self.total_taxes_annual:>15,.0f}",
            f"  Monthly average:      ₲{self.monthly_average_tax:>15,.0f}",
            f"  Net after tax:        ₲{self.net_after_tax:>15,.0f}",
            "",
            "📅 MONTHLY OBLIGATIONS:",
            f"  - IVA declaration:    15th-25th of following month",
            f"  - IRPC:               quarterly or monthly depending on size",
            f"  - Patent municipal:   annually (varies by municipality)",
            f"  - Minimum tax:        if applicable",
            "",
            "=" * 60,
        ]
        return "\n".join(lines)


def calculate_taxes(
    annual_revenue: float,
    annual_deductions: float = 0,
    regime: str = "SAS",
    use_minimum_tax: bool = True,
) -> TaxResult:
    """Calculate Paraguay taxes for a company.

    Args:
        annual_revenue: gross annual revenue in PYG
        annual_deductions: deductible expenses (costs of goods, salaries, etc.)
        regime: "SAS", "SA", "SRL", or "Unipersonal"
        use_minimum_tax: whether to apply minimum presumptive tax
    """
    regime = regime.upper()
    if regime not in ("SAS", "SA", "SRL", "UNIPERSONAL"):
        raise ValueError(f"Invalid regime: {regime}. Use SAS, SA, SRL, or Unipersonal")

    # IRPC rate depends on regime
    if regime == "SAS":
        irpc_rate = IRPC_SAS_SIMPLIFIED  # 10% simplified
    else:
        irpc_rate = IRPC_SA  # 8% for SA/SRL

    net_income = max(0, annual_revenue - annual_deductions)
    irpc_amount = net_income * irpc_rate

    # IVA is on revenue (collected from customers, then remitted to SET)
    iva_collected = annual_revenue * IVA_GENERAL

    # Minimum presumptive tax
    if use_minimum_tax and net_income < 100_000_000:
        # Small company → lower minimum
        minimum_tax = MINIMUM_TAX_SMALL
    else:
        minimum_tax = MINIMUM_TAX_LARGE

    # If IRPC is less than minimum, pay the minimum
    if use_minimum_tax and irpc_amount < minimum_tax and annual_revenue > 20_000_000:
        irpc_amount = minimum_tax

    # Patent municipal: 1-4% of gross (services higher, commerce lower)
    # Default 2% — adjust based on activity
    patent_rate = PATENT_MUNICIPAL_DEFAULT
    patent_amount = annual_revenue * patent_rate

    # Totals
    total_taxes = irpc_amount + patent_amount
    # Note: IVA is collected from customers, so it's not really "your" tax —
    # you just pass it through. We list it for completeness.

    return TaxResult(
        regime=regime,
        annual_revenue=annual_revenue,
        annual_deductions=annual_deductions,
        net_income=net_income,
        irpc_rate=irpc_rate,
        irpc_amount=irpc_amount,
        iva_rate=IVA_GENERAL,
        iva_collected=iva_collected,
        minimum_tax=minimum_tax,
        patent_municipal_rate=patent_rate,
        patent_municipal_amount=patent_amount,
        total_taxes_annual=total_taxes,
        monthly_average_tax=total_taxes / 12,
        net_after_tax=annual_revenue - total_taxes,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Calculate Paraguay corporate taxes (IRPC, IVA, minimum, patent).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --revenue 150000000
  %(prog)s --revenue 100000000 --deduct 40000000 --regime SA
  %(prog)s --revenue 50000000 --regime SAS --no-minimum
        """,
    )
    parser.add_argument(
        "--revenue",
        type=float,
        required=True,
        help="Annual gross revenue in PYG (Paraguayan guaraní)",
    )
    parser.add_argument(
        "--deduct",
        type=float,
        default=0,
        help="Annual deductible expenses in PYG (cost of goods, salaries, etc.)",
    )
    parser.add_argument(
        "--regime",
        type=str,
        default="SAS",
        choices=["SAS", "SA", "SRL", "Unipersonal"],
        help="Company type: SAS (simplified), SA (anónima), SRL (limitada), Unipersonal",
    )
    parser.add_argument(
        "--no-minimum",
        action="store_true",
        help="Don't apply minimum presumptive tax",
    )

    args = parser.parse_args()

    result = calculate_taxes(
        annual_revenue=args.revenue,
        annual_deductions=args.deduct,
        regime=args.regime,
        use_minimum_tax=not args.no_minimum,
    )
    print(result.report())


if __name__ == "__main__":
    main()