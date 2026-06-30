def get_commitment_icon(name):

    icons = {

        "Rent":"🏠",

        "MF SIP":"📈",

        "RD":"🐷",

        "Electricity":"⚡",

        "Pre-EMI":"🚗"

    }

    return icons.get(
        name,
        "📌"
    )


def get_income_icon(_):

    return "💰"