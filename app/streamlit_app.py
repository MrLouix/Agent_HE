"""Point d'entrée Streamlit : `uv run streamlit run app/streamlit_app.py`."""

import streamlit as st

st.set_page_config(page_title="Agent HE", page_icon=":material/spa:", layout="wide")

page = st.navigation(
    {
        "": [
            st.Page(
                "app_pages/assistant.py", title="Assistant", icon=":material/spa:", default=True
            ),
        ],
        "Administration": [
            st.Page(
                "app_pages/boutiques.py",
                title="Boutiques (CGU)",
                icon=":material/storefront:",
            ),
            st.Page(
                "app_pages/securite.py",
                title="Table de sécurité",
                icon=":material/health_and_safety:",
            ),
        ],
    },
    position="top",
)
if page.title != "Assistant":
    st.title(page.title, icon=page.icon)
page.run()
