"""Skill taxonomy: canonical skill -> regex aliases, grouped by kind. Used to
extract requirements from job descriptions and to verify that tailored resume
text never introduces a skill the applicant has not claimed."""
from __future__ import annotations

import re
from functools import lru_cache

# canonical: (kind, [alias regexes]) — aliases are matched case-insensitively
# with word boundaries.
SKILLS: dict[str, tuple[str, list[str]]] = {
    # languages
    "Python": ("language", [r"python"]),
    "SQL": ("language", [r"sql", r"t-sql", r"pl/sql", r"structured query language"]),
    "R": ("language", [r"r(?= programming| language|,| and | or |/|\))", r"rstudio", r"tidyverse"]),
    "Java": ("language", [r"java(?!script)"]),
    "C++": ("language", [r"c\+\+", r"cpp"]),
    "C": ("language", [r"(?<![\w+#])c(?= programming| language|,| and | or |/)"]),
    "C#": ("language", [r"c#", r"\.net", r"dotnet"]),
    "JavaScript": ("language", [r"javascript", r"js(?!on)", r"ecmascript"]),
    "TypeScript": ("language", [r"typescript"]),
    "HTML/CSS": ("language", [r"html5?", r"css3?"]),
    "Go": ("language", [r"golang"]),
    "Rust": ("language", [r"rust(?! belt)"]),
    "Scala": ("language", [r"scala"]),
    "MATLAB": ("language", [r"matlab"]),
    "SAS": ("language", [r"sas(?! token)"]),
    "Julia": ("language", [r"julia"]),
    "Bash": ("language", [r"bash", r"shell scripting", r"unix shell"]),
    "Kotlin": ("language", [r"kotlin"]),
    "Swift": ("language", [r"swift(?!ly)"]),
    "VBA": ("language", [r"vba"]),
    # data science / ML
    "Pandas": ("library", [r"pandas"]),
    "NumPy": ("library", [r"numpy"]),
    "scikit-learn": ("library", [r"scikit[- ]?learn", r"sklearn"]),
    "spaCy": ("library", [r"spacy"]),
    "TensorFlow": ("library", [r"tensorflow", r"keras"]),
    "PyTorch": ("library", [r"pytorch", r"torch"]),
    "XGBoost": ("library", [r"xgboost", r"lightgbm", r"catboost"]),
    "Hugging Face": ("library", [r"hugging ?face", r"transformers library"]),
    "LangChain": ("library", [r"langchain", r"llamaindex"]),
    "Matplotlib": ("library", [r"matplotlib", r"seaborn", r"plotly"]),
    "SciPy": ("library", [r"scipy"]),
    "Statsmodels": ("library", [r"statsmodels"]),
    "BeautifulSoup": ("library", [r"beautiful ?soup", r"bs4"]),
    "Requests": ("library", [r"requests library", r"python requests"]),
    "NLP": ("method", [r"nlp", r"natural language processing", r"text mining", r"text analytics"]),
    "Machine Learning": ("method", [r"machine learning", r"ml(?!s)", r"predictive model(?:ing|s)?", r"statistical learning"]),
    "Deep Learning": ("method", [r"deep learning", r"neural networks?", r"cnns?", r"rnns?", r"transformers?(?= model)"]),
    "LLMs": ("method", [r"llms?", r"large language models?", r"generative ai", r"genai", r"prompt engineering", r"rag"]),
    "Computer Vision": ("method", [r"computer vision", r"image (?:processing|recognition)"]),
    "Regression": ("method", [r"regression", r"linear models?", r"logistic regression"]),
    "Classification": ("method", [r"classification", r"classifiers?"]),
    "Random Forest": ("method", [r"random forests?", r"decision trees?", r"gradient boost(?:ing|ed)", r"tree-based"]),
    "Clustering": ("method", [r"clustering", r"k-?means", r"segmentation"]),
    "Feature Engineering": ("method", [r"feature engineering", r"feature selection"]),
    "Hypothesis Testing": ("method", [r"hypothesis test(?:ing|s)?", r"a/b test(?:ing|s)?", r"statistical (?:significance|tests?)", r"experiment(?:ation| design)"]),
    "EDA": ("method", [r"eda", r"exploratory data analysis", r"exploratory analysis"]),
    "Statistics": ("method", [r"statistics", r"statistical (?:analysis|methods|modeling)", r"probability", r"inferential"]),
    "Time Series": ("method", [r"time[- ]series", r"forecasting", r"arima"]),
    "Optimization": ("method", [r"optimization", r"linear programming", r"operations research", r"mixed[- ]integer"]),
    "Data Cleaning": ("method", [r"data cleaning", r"data wrangling", r"data preparation", r"data munging", r"data quality"]),
    "Data Visualization": ("method", [r"data visuali[sz]ation", r"visuali[sz]ations?", r"dashboards?"]),
    "Web Scraping": ("method", [r"web scraping", r"scrap(?:ing|er|ed)", r"crawl(?:ing|er)"]),
    "Thematic Analysis": ("method", [r"thematic analysis", r"qualitative (?:analysis|research|coding)"]),
    "Data Analysis": ("method", [r"data analysis", r"analy[sz]e data", r"analyzing (?:large )?(?:data|datasets)", r"data analytics"]),
    # tools / frameworks
    "FastAPI": ("tool", [r"fastapi"]),
    "Flask": ("tool", [r"flask"]),
    "Django": ("tool", [r"django"]),
    "React": ("tool", [r"react(?:\.js|js)?(?! native)"]),
    "Node.js": ("tool", [r"node(?:\.js|js)?", r"express(?:\.js|js)?"]),
    "Express": ("tool", [r"express\.js", r"expressjs"]),
    "Spring": ("tool", [r"spring boot", r"spring framework"]),
    "PostgreSQL": ("tool", [r"postgres(?:ql)?"]),
    "MySQL": ("tool", [r"mysql"]),
    "SQLite": ("tool", [r"sqlite"]),
    "SQL Server": ("tool", [r"sql server", r"mssql", r"ssis", r"ssrs"]),
    "Oracle": ("tool", [r"oracle (?:database|db|sql)"]),
    "MongoDB": ("tool", [r"mongodb", r"mongo", r"nosql"]),
    "Snowflake": ("tool", [r"snowflake"]),
    "BigQuery": ("tool", [r"bigquery"]),
    "Redshift": ("tool", [r"redshift"]),
    "Databricks": ("tool", [r"databricks"]),
    "Spark": ("tool", [r"spark", r"pyspark"]),
    "Hadoop": ("tool", [r"hadoop", r"hive", r"hdfs"]),
    "Kafka": ("tool", [r"kafka"]),
    "Airflow": ("tool", [r"airflow"]),
    "dbt": ("tool", [r"dbt"]),
    "ETL Pipelines": ("tool", [r"etl", r"elt", r"data pipelines?", r"pipelines?(?= for data)"]),
    "REST APIs": ("tool", [r"rest(?:ful)? apis?", r"rest(?:ful)? (?:services|endpoints)", r"apis?"]),
    "GraphQL": ("tool", [r"graphql"]),
    "Docker": ("tool", [r"docker", r"containeri[sz](?:ed|ing|ation)", r"containers?"]),
    "Kubernetes": ("tool", [r"kubernetes", r"k8s"]),
    "CI/CD": ("tool", [r"ci/cd", r"continuous integration", r"continuous delivery", r"continuous deployment", r"github actions", r"jenkins"]),
    "Git": ("tool", [r"git(?!hub)", r"version control"]),
    "GitHub": ("tool", [r"github"]),
    "Reddit": ("tool", [r"reddit"]),
    "Linux": ("tool", [r"linux", r"unix"]),
    "AWS": ("tool", [r"aws", r"amazon web services", r"s3", r"ec2", r"lambda", r"sagemaker"]),
    "Azure": ("tool", [r"azure"]),
    "GCP": ("tool", [r"gcp", r"google cloud"]),
    "Power BI": ("tool", [r"power ?bi", r"dax"]),
    "Tableau": ("tool", [r"tableau"]),
    "Looker": ("tool", [r"looker"]),
    "Excel": ("tool", [r"excel", r"spreadsheets?", r"pivot tables?", r"vlookup"]),
    "Streamlit": ("tool", [r"streamlit"]),
    "Jupyter": ("tool", [r"jupyter", r"notebooks?"]),
    "Salesforce": ("tool", [r"salesforce"]),
    "SAP": ("tool", [r"sap(?! hana)"]),
    "Jira": ("tool", [r"jira", r"agile", r"scrum"]),
    "Figma": ("tool", [r"figma"]),
    "Full-Stack Development": ("method", [r"full[- ]?stack"]),
    "Backend Development": ("method", [r"back[- ]?end"]),
    "Frontend Development": ("method", [r"front[- ]?end"]),
    "Data Structures & Algorithms": ("method", [r"data structures", r"algorithms"]),
    "Object-Oriented Programming": ("method", [r"object[- ]oriented", r"oop"]),
    "Database Design": ("method", [r"database design", r"schema design", r"data model(?:ing|ling)", r"normaliz(?:ed|ation)"]),
    "Cybersecurity": ("method", [r"cyber ?security", r"threat detection", r"information security", r"infosec"]),
    "Communication": ("soft", [r"communication skills", r"communicat(?:e|ing) (?:findings|results|insights)", r"present(?:ing|ation)s?"]),
    "Research": ("soft", [r"research"]),
    "Problem Solving": ("soft", [r"problem[- ]solving"]),
    "Teamwork": ("soft", [r"team ?work", r"collaborat(?:e|ion|ive)", r"cross-functional"]),
    "Business Acumen": ("soft", [r"business acumen", r"stakeholders?", r"business requirements"]),
}

ROLE_TERMS = {
    "data_science": ["data science", "machine learning", "statistics", "modeling", "python"],
    "data_analytics": ["analytics", "sql", "dashboards", "reporting", "insights"],
    "ml_ai": ["machine learning", "deep learning", "nlp", "llm", "ai"],
    "software": ["software", "backend", "frontend", "apis", "full-stack"],
    "data_engineering": ["etl", "pipelines", "data warehouse", "spark", "sql"],
    "quant": ["quantitative", "statistics", "probability", "python", "c++"],
    "business_analytics": ["business", "requirements", "stakeholders", "sql", "excel"],
    "research": ["research", "analysis", "experiments", "python"],
    "operations_research": ["optimization", "simulation", "operations research"],
}


@lru_cache
def _compiled() -> list[tuple[str, str, re.Pattern]]:
    out = []
    for canon, (kind, aliases) in SKILLS.items():
        pat = r"(?<![\w])(?:" + "|".join(aliases) + r")(?![\w])"
        out.append((canon, kind, re.compile(pat, re.I)))
    return out


def extract_skills(text: str) -> dict[str, int]:
    """canonical skill -> occurrence count"""
    found: dict[str, int] = {}
    if not text:
        return found
    for canon, _kind, rx in _compiled():
        n = len(rx.findall(text))
        if n:
            found[canon] = n
    return found


def skill_kind(canon: str) -> str:
    return SKILLS.get(canon, ("other", []))[0]


def canonicalize(name: str) -> str | None:
    """Map a free-form skill string (e.g. 'Node.js/Express') to a canonical skill."""
    for canon, _kind, rx in _compiled():
        if canon.lower() == name.lower() or rx.fullmatch(name.strip()):
            return canon
    found = extract_skills(name)
    return max(found, key=found.get) if found else None


# Implications: having the key implies familiarity with the values (used only
# for matching credit, never to add skills to a resume).
IMPLIES = {
    "PostgreSQL": ["SQL", "Database Design"],
    "SQLite": ["SQL"],
    "Pandas": ["Data Cleaning", "Data Analysis"],
    "scikit-learn": ["Machine Learning"],
    "Random Forest": ["Machine Learning", "Classification"],
    "Regression": ["Statistics", "Machine Learning"],
    "Classification": ["Machine Learning"],
    "Hypothesis Testing": ["Statistics"],
    "EDA": ["Data Analysis", "Data Visualization"],
    "Power BI": ["Data Visualization"],
    "Tableau": ["Data Visualization"],
    "spaCy": ["NLP"],
    "NLP": ["Machine Learning"],
    "React": ["JavaScript", "Frontend Development"],
    "Node.js": ["JavaScript", "Backend Development"],
    "FastAPI": ["Python", "REST APIs", "Backend Development"],
    "ETL Pipelines": ["Data Cleaning"],
    "Docker": ["CI/CD"],
    "Git": ["GitHub"],
    "Streamlit": ["Data Visualization"],
    "BeautifulSoup": ["Web Scraping"],
    "Thematic Analysis": ["Research"],
}
