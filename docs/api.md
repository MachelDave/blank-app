# Public API Reference

This repository is a minimal Streamlit app template. It currently exposes no user-defined public Python APIs (functions, classes, or modules) intended for reuse. All logic resides at the top level of `streamlit_app.py` and directly uses Streamlit's APIs.

## Module: `streamlit_app`
- Purpose: Render the app's UI.
- Public objects: None (no reusable functions or classes yet).
- External APIs used: `streamlit` (e.g., `st.title`, `st.write`).

### Current behavior
```python
import streamlit as st

st.title("🎈 My new app")
st.write(
    "Let's start building! For help and inspiration, head over to docs.streamlit.io."
)
```

### Example: Adding a reusable function (extension pattern)
While there are no public APIs now, you can add your own and import them into the app. For example:

```python
# file: utils/text.py
from typing import Final

GREETING_PREFIX: Final[str] = "Hello"

def build_greeting(name: str) -> str:
    """Return a friendly greeting for a given name.
    
    Args:
        name: Person's name.
    Returns:
        A greeting string like "Hello, Alice!".
    """
    safe_name = name.strip() or "there"
    return f"{GREETING_PREFIX}, {safe_name}!"
```

Use it in the app:

```python
# file: streamlit_app.py
import streamlit as st
from utils.text import build_greeting

st.title("🎈 My new app")
name = st.text_input("Your name")
if name:
    st.success(build_greeting(name))
```

Expose functions in a package (e.g., `src/yourpkg/`) if you plan to publish and reuse them.