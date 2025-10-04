import os
import streamlit as st
import pandas as pd
import mysql.connector
from dotenv import load_dotenv
import openai
import json
import plotly.express as px

# ---------- Load environment ----------
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

DB_CONFIG = {
    'host': os.getenv("DB_HOST"),
    'user': os.getenv("DB_USER"),
    'password': os.getenv("DB_PASS"),
    'database': os.getenv("DB_NAME"),
    'port': int(os.getenv("DB_PORT", 3306))
}

# ---------- Database connection ----------
@st.cache_resource
def get_db_conn():
    return mysql.connector.connect(**DB_CONFIG)

def fetch_employees(conn):
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM employees")
    rows = cursor.fetchall()
    cursor.close()
    return rows

# ---------- Skill normalization ----------
def normalize_skills(skill_text):
    if not skill_text:
        return []
    return [s.strip().lower().replace(' ', '') for s in skill_text.split(',') if s.strip()]

# ---------- Extract skills ----------
def extract_skills(project_text):
    if ',' in project_text and len(project_text.split()) <= 10:
        return normalize_skills(project_text)
    prompt = f"Extract the main technical skills from this project description and return as a JSON array:\n{project_text}\nReturn only JSON."
    try:
        resp = openai.Completion.create(
            engine="text-davinci-003",
            prompt=prompt,
            max_tokens=150
        )
        skills = json.loads(resp.choices[0].text.strip())
        return normalize_skills(','.join(skills))
    except:
        return normalize_skills(project_text)

# ---------- Streamlit UI ----------
st.set_page_config(layout="wide", page_title="Employee Skill Matcher")
st.title("🧑‍💻 AI Powered Resource Allocation Tool")

with st.sidebar:
    st.header("Project Input")
    project_text = st.text_area("Enter Project Requirement", height=150)
    project_type = st.selectbox("Project Type", ["Software Dev", "Cloud", "Data", "AI", "QA"])
    analyze_btn = st.button("Analyze Fit")

# ---------- Main logic ----------
if analyze_btn and project_text.strip():
    conn = get_db_conn()
    employees = fetch_employees(conn)

    # Extract required skills
    req_skills = extract_skills(project_text)
    if not req_skills:
        st.warning("No skills found in the input!")
        st.stop()

    # Prepare employee skills
    for e in employees:
        e['skill_list'] = normalize_skills(e['skills'])
        e['skill_text'] = ', '.join(e['skill_list'])

    # Compute fit % and missing skills
    results = []
    for e in employees:
        overlap = len(set(req_skills).intersection(set(e['skill_list'])))
        if overlap == 0:
            continue  # Only employees with ≥1 matching skill
        fit_pct = round((overlap / len(req_skills)) * 100)
        missing = list(set(req_skills) - set(e['skill_list']))
        results.append({
            'id': e['id'], 'name': e['name'],
            'fit_pct': fit_pct,
            'skills': e['skill_list'],
            'missing': missing
        })

    if not results:
        st.warning("No employees matched the project requirements.")
        st.stop()

    # Store in session_state
    st.session_state['df'] = pd.DataFrame(results)
    st.session_state['results'] = results
    st.session_state['req_skills'] = req_skills

# ---------- Fetch from session_state ----------
df = st.session_state.get('df')
results = st.session_state.get('results')
req_skills = st.session_state.get('req_skills')

if df is not None and results is not None:

    # ---------- 1️⃣ Recommendations ----------
    st.subheader("🏆 Employee Recommendations")
    df_sorted = df.sort_values('fit_pct', ascending=False)
    for _, row in df_sorted.iterrows():
        st.markdown(f"**{row['name']}** — Fit: **{row['fit_pct']}%**")
        st.write("✔ Has:", ', '.join([s for s in row['skills'] if s in req_skills]))
        st.write("✘ Missing:", ', '.join(row['missing']) if row['missing'] else "None")
        if row['missing']:
            st.info(f"Recommendation: Training required in {', '.join(row['missing'])}")
        else:
            st.success("Good fit — no training required.")
    st.markdown("---")

    # ---------- 2️⃣ Bar Chart: Employee Fit % ----------
    st.subheader("📊 Employee Match %")
    df['fit_category'] = df['fit_pct'].apply(lambda f: 'green' if f>=70 else 'orange' if f>=40 else 'red')
    fig_bar = px.bar(
        df,
        x='name',
        y='fit_pct',
        text='fit_pct',
        color='fit_category',
        color_discrete_map={'green':'green','orange':'orange','red':'red'},
        title="Employee Fit %"
    )
    fig_bar.update_layout(yaxis_title="Fit %", xaxis_title="Employee")
    st.plotly_chart(fig_bar, use_container_width=True)

    # ---------- Bubble Chart: Missing Skills per Employee ----------
    st.subheader("📌 Missing Skills per Employee")
    missing_records = []
    for e in results:
        for skill in e['missing']:
            missing_records.append({'Employee': e['name'], 'MissingSkill': skill})
    if missing_records:
        df_missing = pd.DataFrame(missing_records)
        fig_bubble = px.scatter(
            df_missing,
            x='Employee',
            y='MissingSkill',
            size=[1]*len(df_missing),
            color='MissingSkill',
            title="Missing Skills per Employee",
            size_max=20
        )
        st.plotly_chart(fig_bubble, use_container_width=True)
    else:
        st.info("All employees have all required skills!")

    # ---------- 3️⃣ Team Fit Suggestion ----------
    st.subheader("👥 Team Fit Suggestion")
    if st.button("Show Team Fit"):
        # Simply suggest top 5 employees
        top5 = list(df_sorted['name'].head(5))
        st.success(f"Suggested team to cover all skills (Top 5): {', '.join(top5)}")

    # ---------- Download CSV ----------
    st.download_button("📥 Download Results CSV", df.to_csv(index=False), file_name="skill_matches.csv")

