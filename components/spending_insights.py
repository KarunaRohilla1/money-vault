import streamlit as st
import pandas as pd
import plotly.express as px

from db.dashboard import (
    get_category_spending_this_month
)


def show_spending_insights(vault_id):

    st.markdown(
        """
        <div class="section-title">
            📊 Spending Insights
        </div>
        """,
        unsafe_allow_html=True
    )

    category_data = (
        get_category_spending_this_month(
            vault_id
        )
    )

    if not category_data:

        st.info(
            "No spending data available."
        )

        return

    chart_df = pd.DataFrame(
        category_data,
        columns=[
            "Category",
            "Amount"
        ]
    )

    total_spent = (
        chart_df["Amount"]
        .sum()
    )

    fig = px.pie(
        chart_df,
        names="Category",
        values="Amount",
        hole=0.72,
        color_discrete_sequence=[
            "#8B5CF6",
            "#A78BFA",
            "#EC4899",
            "#F472B6",
            "#F59E0B"
        ]
    )

    fig.update_traces(
        textinfo="none",
        marker=dict(
            line=dict(
                color="rgba(255,255,255,0.08)",
                width=2
            )
        )
    )

    fig.update_layout(
        height=460,

        showlegend=True,

        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",

        margin=dict(
            l=0,
            r=0,
            t=0,
            b=0
        ),

        legend=dict(
            orientation="v",
            yanchor="middle",
            y=0.5,
            xanchor="left",
            x=1.02,
            font=dict(
                color="#CBD5E1",
                size=13
            )
        ),

        annotations=[
            dict(
                text=(
                    f"<b>₹{total_spent:,.0f}</b>"
                    "<br>"
                    "<span style='font-size:14px'>Total Spent</span>"
                ),
                x=0.5,
                y=0.5,
                showarrow=False,
                font=dict(
                    size=24,
                    color="#E5E7EB"
                )
            )
        ]
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
        config={
            "displayModeBar": False
        }
    )
