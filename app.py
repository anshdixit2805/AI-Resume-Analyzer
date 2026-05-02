import os
import requests
from flask import session, redirect, url_for
from flask import Flask, request, render_template
from ibm_watson import NaturalLanguageUnderstandingV1
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
from cloudant.client import Cloudant

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY")

CLIENT_ID = os.environ.get("APPID_CLIENT_ID")
CLIENT_SECRET = os.environ.get("APPID_CLIENT_SECRET")
OAUTH_URL = os.environ.get("APPID_OAUTH_URL")
REDIRECT_URI = os.environ.get("REDIRECT_URI")

# -------- NLU SETUP --------
authenticator = IAMAuthenticator(os.environ.get("IBM_NLU_APIKEY"))
nlu = NaturalLanguageUnderstandingV1(
    version='2022-04-07',
    authenticator=authenticator
)
nlu.set_service_url(os.environ.get("IBM_NLU_URL"))

# -------- CLOUDANT SETUP --------
client = Cloudant("apikey-v2-1d0n6jkbpcl2fy5utu5af1s02m5dtpjje8igo3j9t65r", "73e5fdfb01638ff91478effe3fd5725a", url="https://apikey-v2-1d0n6jkbpcl2fy5utu5af1s02m5dtpjje8igo3j9t65r:73e5fdfb01638ff91478effe3fd5725a@dd45670d-4c3e-48e3-b139-3ea148e3430a-bluemix.cloudantnosqldb.appdomain.cloud")
client.connect()
db = client.create_database("resume_db", throw_on_exists=False)
@app.route('/login')
def login():
    auth_url = f"{OAUTH_URL}/authorization?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&scope=openid"
    return redirect(auth_url)

@app.route('/callback')
def callback():
    code = request.args.get('code')

    token_url = f"{OAUTH_URL}/token"

    data = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "code": code
    }

    response = requests.post(token_url, data=data)
    token_info = response.json()

    session['user'] = token_info
    return redirect(url_for('index'))

@app.route('/', methods=['GET', 'POST'])
def index():
    if 'user' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        resume = request.form['resume']
        role = request.form['role']

        # NLU ANALYSIS
        response = nlu.analyze(
            text=resume,
            features={
                "keywords": {"limit": 5},
                "entities": {"limit": 5}
            }
        ).get_result()

        keywords = [k['text'] for k in response['keywords']]
        entities = [e['text'] for e in response['entities']]
        resume_text = resume.lower()

        if role == "data_scientist":
            job_skills = ["python", "sql", "machine learning", "data analysis", "statistics"]

        elif role == "web_developer":
            job_skills = ["html", "css", "javascript", "react", "node.js"]

        elif role == "ai_engineer":
            job_skills = ["python", "deep learning", "nlp", "tensorflow", "pytorch"]

        else:
            job_skills = []
        # -------- JOB MATCH CALCULATION --------
        resume_words = set(resume_text.split())
        job_words = set(job_skills)

        common_words = resume_words.intersection(job_words)

        if len(job_words) > 0:
            job_match_score = int((len(common_words) / len(job_words)) * 100)
        else:
            job_match_score = 0

        matched = []

        for skill in job_skills:
           if skill in resume_text:
               matched.append(skill)

        # Better scoring
        if len(job_skills) > 0:
            score = int((len(matched) / len(job_skills)) * 100)
        else:
            score = 0
            # -------- ATS BREAKDOWN --------

            # 1. Skills Score
            if len(job_skills) > 0:
                skills_score = int((len(matched) / len(job_skills)) * 100)
            else:
                skills_score = 0

            # 2. Keyword Score
            keyword_score = min(len(keywords) * 10, 100)

            # 3. Resume Length Score
            word_count = len(resume.split())

            if word_count > 150:
                length_score = 100
            elif word_count > 100:
                length_score = 70
            elif word_count > 50:
                length_score = 50
            else:
                length_score = 30

            # 4. FINAL ATS SCORE (overwrite old score)
            score = int((skills_score + keyword_score + length_score) / 3)

            # STORE IN CLOUDANT
            doc = {
                "resume": resume,
                "keywords": keywords,
                "entities": entities
            }
            db.create_document(doc)

        # -------- AI SUGGESTIONS --------

        suggestions = []

        missing_skills = [skill for skill in job_skills if skill not in matched]
        # ATS Breakdown Scores
        skills_score = int((len(matched) / len(job_skills)) * 100) if job_skills else 0
        keyword_score = len(keywords) * 10
        length_score = min(len(resume.split()), 100)

        if missing_skills:
            suggestions.append(f"Consider adding these skills: {', '.join(missing_skills)}")

        if score < 50:
            suggestions.append("Your resume score is low. Try adding more relevant technical skills and projects.")

        if len(keywords) < 3:
            suggestions.append("Add more strong keywords related to your domain to improve visibility.")

        suggestions.append("Use action verbs like 'developed', 'built', 'designed', 'implemented'.")

        if len(resume.split()) < 100:
            suggestions.append("Your resume is too short. Add more details about your experience and projects.")

        return render_template("result.html",
                 keywords=keywords,
                 entities=entities,
                 score=score,
                 matched=matched,
                 missing_skills=missing_skills,
                 suggestions=suggestions,
                 role=role,
                 skills_score=skills_score,
                 keyword_score=keyword_score,
                 length_score=length_score,
                 job_match_score=job_match_score
            )

    return render_template("index.html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)