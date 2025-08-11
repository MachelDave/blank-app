# Usage and Quickstart

## Prerequisites
- Python 3.9+
- pip

## Installation
```bash
pip install -r requirements.txt
```

## Run the app
```bash
streamlit run streamlit_app.py
```

Streamlit will start a local server and open the app in your browser.

## Project structure
```
.
├── README.md
├── requirements.txt
├── streamlit_app.py
└── docs/
    ├── index.md
    ├── usage.md
    ├── api.md
    └── components.md
```

## Customization
Open `streamlit_app.py` and modify or add UI elements. For example, to accept a name and greet the user:

```python
import streamlit as st

st.title("🎈 My new app")
name = st.text_input("Your name")
if name:
    st.success(f"Hello, {name}!")
```

Run again with `streamlit run streamlit_app.py`.