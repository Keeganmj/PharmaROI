import streamlit as st
import pandas as pd
import numpy as np

# Set page config
st.set_page_config(page_title="Streamlit Charts Demo", layout="wide")

# Title
st.title("📊 Streamlit Charts Demo")

# Sidebar for chart selection
chart_type = st.sidebar.selectbox(
    "Select Chart Type",
    ["Line Chart", "Area Chart", "Bar Chart", "Scatter Chart"]
)

# Generate sample data
@st.cache_data
def generate_data():
    dates = pd.date_range('2024-01-01', periods=30, freq='D')
    df = pd.DataFrame({
        'date': dates,
        'Sales': np.random.randint(100, 500, 30),
        'Revenue': np.random.randint(1000, 5000, 30),
        'Customers': np.random.randint(50, 200, 30)
    })
    return df

df = generate_data()

# Display selected chart
st.subheader(f"{chart_type} Example")

if chart_type == "Line Chart":
    st.line_chart(df.set_index('date')[['Sales', 'Revenue']])
    
elif chart_type == "Area Chart":
    st.area_chart(df.set_index('date')[['Sales', 'Revenue']])
    
elif chart_type == "Bar Chart":
    st.bar_chart(df.set_index('date')['Sales'])
    
elif chart_type == "Scatter Chart":
    chart_data = pd.DataFrame({
        'x': np.random.randn(100),
        'y': np.random.randn(100)
    })
    st.scatter_chart(chart_data)

# Show raw data
if st.checkbox("Show raw data"):
    st.subheader("Raw Data")
    st.dataframe(df)

# Additional metrics
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Avg Sales", f"${df['Sales'].mean():.0f}")
with col2:
    st.metric("Avg Revenue", f"${df['Revenue'].mean():.0f}")
with col3:
    st.metric("Avg Customers", f"{df['Customers'].mean():.0f}")
