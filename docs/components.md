# UI Components and Patterns

This template app currently renders two Streamlit UI calls:

- `st.title("🎈 My new app")`: Displays the page title.
- `st.write("…")`: Renders markdown/text content.

## Code excerpt
```python
import streamlit as st

st.title("🎈 My new app")
st.write(
    "Let's start building! For help and inspiration, head over to docs.streamlit.io."
)
```

## Common extension patterns
- Text input + reactive output:
  ```python
  name = st.text_input("Your name")
  if name:
      st.success(f"Hello, {name}!")
  ```
- File upload:
  ```python
  file = st.file_uploader("Upload a CSV", type=["csv"]) 
  if file is not None:
      import pandas as pd
      df = pd.read_csv(file)
      st.dataframe(df)
  ```
- Caching expensive work:
  ```python
  import streamlit as st

  @st.cache_data
  def load_data(url: str):
      import pandas as pd
      return pd.read_csv(url)

  df = load_data("https://example.com/data.csv")
  st.dataframe(df)
  ```

Use these patterns to build richer interfaces while keeping logic in small, testable functions.