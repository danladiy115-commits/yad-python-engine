from decimal import Decimal, ROUND_DOWN, ROUND_CEILING
from datetime import date


def money(value):
    return Decimal(str(value))


def format_money(value):
    return f"{value:,.2f}"


def calculate_rsa(balance, dob, calculation_year=2026):
    """
    YAD mortgage and RSA calculation rules.
    RSA 25% is truncated, never rounded.
    Property amount is rounded upward to a
    multiple of N500,000.
    """

    rsa_balance = money(balance)

    if rsa_balance <= 0:
        raise ValueError("RSA balance must be greater than zero.")

    try:
        birth_date = date.fromisoformat(dob)
    except (ValueError, TypeError):
        raise ValueError("DOB must use YYYY-MM-DD format.")

    if birth_date.year > calculation_year:
        raise ValueError("Birth year cannot be in the future.")

    # 25% RSA: keep first two decimal places.
    rsa_25 = (rsa_balance / Decimal("4")).quantize(
        Decimal("0.01"),
        rounding=ROUND_DOWN
    )

    # Property amount: add N500,000, then round up.
    property_base = rsa_25 + Decimal("500000")

    property_amount = (
        (property_base / Decimal("500000"))
        .to_integral_value(rounding=ROUND_CEILING)
        * Decimal("500000")
    )

    force_sale_value = property_amount - Decimal("1000000")

    admin_charges = (
        rsa_25 * Decimal("0.03")
    ).quantize(Decimal("0.01"), rounding=ROUND_DOWN)

    loan_amount = property_amount - rsa_25

    kbl_premium = (
        property_amount * Decimal("0.004")
    ).quantize(Decimal("0.01"), rounding=ROUND_DOWN)

    credit_life_premium = (
        loan_amount * Decimal("0.006")
    ).quantize(Decimal("0.01"), rounding=ROUND_DOWN)

    # Retirement tenure uses birth year only.
    age_by_year = calculation_year - birth_date.year
    tenure = 60 - age_by_year

    if tenure <= 0:
        raise ValueError(
            "Retirement tenure is zero or negative. Review DOB."
        )

    months = tenure * 12

    monthly_repayment = (
        loan_amount / Decimal(months)
    ).quantize(Decimal("0.01"), rounding=ROUND_DOWN)

    return {
        "calculation_year": calculation_year,
        "rsa_balance": format_money(rsa_balance),
        "rsa_25_percent": format_money(rsa_25),
        "property_amount": format_money(property_amount),
        "force_sale_value": format_money(force_sale_value),
        "admin_charges_3_percent": format_money(admin_charges),
        "loan_amount": format_money(loan_amount),
        "kbl_premium_0_4_percent": format_money(kbl_premium),
        "credit_life_premium_0_6_percent": format_money(
            credit_life_premium
        ),
        "birth_year": birth_date.year,
        "age_by_year": age_by_year,
        "retirement_tenure_years": tenure,
        "repayment_months": months,
        "monthly_repayment": format_money(monthly_repayment)
      }
