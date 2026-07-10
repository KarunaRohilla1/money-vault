from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def format_money(amount):
    try:
        value = Decimal(str(amount or 0)).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )
    except (InvalidOperation, ValueError):
        value = Decimal("0.00")

    if value == value.to_integral_value():
        return f"₹{value:,.0f}"

    return f"₹{value:,.2f}"
