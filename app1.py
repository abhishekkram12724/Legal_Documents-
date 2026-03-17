import os
import sqlite3
from flask import Flask, request, render_template, redirect, url_for, session, flash
import fitz  # PyMuPDF
import nltk
from nltk.tokenize import sent_tokenize
from deep_translator import GoogleTranslator
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import spacy

# Initialize
nltk.download('punkt')
nlp = spacy.load("en_core_web_sm")

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

DATABASE = 'users.db'

# --- DB Setup ---
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as db:
        db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            )
        ''')
init_db()

# --- NLP Functions ---
def extract_text_from_pdf(pdf_path):
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text

def simple_summarize(text, num_sentences=5):
    sentences = sent_tokenize(text)
    return ' '.join(sentences[:num_sentences])

def translate_text(text, dest_lang):
    try:
        translated = GoogleTranslator(source='auto', target=dest_lang).translate(text)
        return translated
    except Exception as e:
        print(f"Translation error: {e}")
        return "Translation error"

def predict_legal_type(text):
    legal_keywords = {
        "contract": ["contract", "agreement", "terms", "party", "obligation"],
        "will": ["will", "testament", "bequeath", "inherit", "executor"],
        "lease": ["lease", "rent", "tenant", "landlord", "premises"],
        "notice": ["notice", "termination", "resignation", "warning"],
        "nda": ["confidential", "non-disclosure", "nda", "proprietary"],
        "affidavit": ["affidavit", "sworn", "declaration", "under oath"]
    }

    text_lower = text.lower()
    matched_types = [k for k, v in legal_keywords.items() if any(word in text_lower for word in v)]
    is_legal = len(matched_types) > 0
    predicted_type = matched_types[0] if matched_types else "Unknown"
    return is_legal, predicted_type

def extract_named_entities(text):
    doc = nlp(text)
    return [(ent.text, ent.label_) for ent in doc.ents]

# --- Auth Decorator ---
def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login first.')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapped

# --- Auth Routes ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if not username or not password:
            flash('Please provide both username and password.')
            return redirect(url_for('register'))

        db = get_db()
        user = db.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
        if user:
            flash('Username already exists.')
            return redirect(url_for('register'))

        password_hash = generate_password_hash(password)
        db.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)', (username, password_hash))
        db.commit()
        flash('Registration successful. Please login.')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/', methods=['GET', 'POST'])
@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('predict'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        db = get_db()
        user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()

        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            return redirect(url_for('predict'))
        else:
            flash('Invalid username or password.')

    return render_template('index.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.')
    return redirect(url_for('login'))

# --- Main Prediction Route ---
@app.route('/predict', methods=['GET', 'POST'])
@login_required
def predict():
    original_text = None
    summarized_text = None
    translated_text = None
    selected_lang = None
    is_legal = None
    legal_type = None
    named_entities = None

    if request.method == 'POST':
        if 'pdf_file' in request.files:
            file = request.files.get('pdf_file')
            if file and file.filename.endswith('.pdf'):
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
                file.save(filepath)
                original_text = extract_text_from_pdf(filepath)

                # Predict legal status
                is_legal, legal_type = predict_legal_type(original_text)

                # Extract named entities
                named_entities = extract_named_entities(original_text)

            else:
                flash("Please upload a valid PDF file.")
                return render_template('predict.html')

        elif 'summarize' in request.form:
            original_text = request.form.get('original_text')
            summarized_text = simple_summarize(original_text)

        elif 'translate' in request.form:
            summarized_text = request.form.get('summarized_text')
            selected_lang = request.form.get('language')
            if summarized_text and selected_lang:
                translated_text = translate_text(summarized_text, selected_lang)
            else:
                flash("Please provide summary and language to translate.")

    return render_template('predict.html',
                           original_text=original_text,
                           summarized_text=summarized_text,
                           translated_text=translated_text,
                           selected_lang=selected_lang,
                           is_legal=is_legal,
                           legal_type=legal_type,
                           named_entities=named_entities,
                           username=session.get('username'))

if __name__ == '__main__':
    app.run(debug=False)
