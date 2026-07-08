import streamlit as st


def hero_card(
    title,
    value,
    subtitle="",
    message="",
    variant=""
):

    st.markdown(
        f"""<div class="hero-card {variant}">
            <div class="hero-glow"></div>
            <div>
                <div class="hero-title">{title}</div>
                <div class="hero-message">{message}</div>
            </div>
            <div class="hero-value">{value}</div>
        </div>""",unsafe_allow_html=True
    )


def metric_card(
    title,
    value,
    variant=""
):

    st.markdown(f"""
        <div class="metric-card {variant}">
            <div class="metric-title">{title}</div>
            <div class="metric-value">{value}</div>
        </div>""",
        unsafe_allow_html=True
    )
    

def get_spending_message(
    safe_to_spend
):

    if safe_to_spend < 5000:
        return (
            "⚠️ Tight cycle. "
            "Be mindful of discretionary spending."
        )

    elif safe_to_spend < 15000:
        return (
            "✅ You're comfortably within budget."
        )

    return (
        "🎉 Plenty of room left this cycle."
    )
