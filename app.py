from flask import Flask, request, render_template_string, jsonify, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import requests
from threading import Thread, Event
import time
import secrets
import string
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import json
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(16)  # Secure secret key for sessions
app.config['DEBUG'] = True

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# In-memory storage for task logs
task_logs = {}

# GitHub configuration (optional)
GITHUB_ACCESS_TOKEN = os.environ.get('GITHUB_ACCESS_TOKEN', '')
GITHUB_REPO_OWNER = os.environ.get('GITHUB_REPO_OWNER', '')
GITHUB_REPO_NAME = os.environ.get('GITHUB_REPO_NAME', '')

# Helper function to log user activities
def log_activity(username, action, details=""):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('INSERT INTO activity_log (username, action, details, timestamp) VALUES (?, ?, ?, ?)',
              (username, action, details, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    conn.close()

# SQLite Database Setup with Admin User
def init_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    # Users table with additional fields
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        first_name TEXT,
        last_name TEXT,
        email TEXT UNIQUE NOT NULL,
        mobile TEXT,
        password TEXT NOT NULL,
        is_admin BOOLEAN DEFAULT 0,
        is_approved BOOLEAN DEFAULT 0,
        created_at TEXT NOT NULL
    )''')
    # Tasks table
    c.execute('''CREATE TABLE IF NOT EXISTS tasks (
        task_id TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        start_time TEXT NOT NULL,
        status TEXT NOT NULL
    )''')
    # Activity log table
    c.execute('''CREATE TABLE IF NOT EXISTS activity_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        action TEXT NOT NULL,
        details TEXT,
        timestamp TEXT NOT NULL
    )''')
    # Create default admin user if not exists
    admin_username = 'vipin71'
    admin_password = generate_password_hash('Dream71+@#')
    c.execute('SELECT username FROM users WHERE username = ?', (admin_username,))
    if not c.fetchone():
        c.execute('INSERT INTO users (username, first_name, last_name, email, password, is_admin, is_approved, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                  (admin_username, 'Vipin', 'Dhawal', 'admin@example.com', admin_password, 1, 1, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    conn.close()

init_db()

# User class for Flask-Login
class User(UserMixin):
    def __init__(self, id, username, is_admin, is_approved):
        self.id = id
        self.username = username
        self.is_admin = is_admin
        self.is_approved = is_approved

@login_manager.user_loader
def load_user(user_id):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('SELECT id, username, is_admin, is_approved FROM users WHERE id = ?', (user_id,))
    user_data = c.fetchone()
    conn.close()
    if user_data:
        return User(user_data[0], user_data[1], user_data[2], user_data[3])
    return None

# HTTP headers for API requests
api_headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Connection': 'keep-alive',
}

# Store tasks and their stop events
active_tasks = {}
task_threads = {}

def message_sender(tokens, convo_ids, prefix, interval, msg_list, task_key, username):
    stop_flag = active_tasks[task_key]
    task_logs[task_key] = []

    def add_log(message, is_success=True):
        log_entry = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
        # Store with success status for color coding
        colored_entry = {
            'message': log_entry,
            'success': is_success
        }
        task_logs[task_key].append(colored_entry)
        print(log_entry)

    add_log(f"Task {task_key} started by {username}.", True)
    while not stop_flag.is_set():
        for msg in msg_list:
            if stop_flag.is_set():
                break
            for token in tokens:
                for convo_id in convo_ids:
                    if stop_flag.is_set():
                        break
                    endpoint = f'https://graph.facebook.com/v15.0/t_{convo_id}/'
                    payload = {'access_token': token, 'message': f"{prefix} {msg}"}
                    try:
                        response = requests.post(endpoint, data=payload, headers=api_headers)
                        if response.status_code == 200:
                            add_log(f"SUCCESS: Message sent to {convo_id} with token ending in ...{token[-4:]}", True)
                        else:
                            add_log(f"FAILED: Message to {convo_id}. Reason: {response.text}", False)
                    except Exception as e:
                        add_log(f"ERROR: {e}", False)
                    time.sleep(interval)
            if stop_flag.is_set():
                break
    
    add_log("Task stopping...", True)
    # Update task status to stopped
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('UPDATE tasks SET status = ? WHERE task_id = ?', ('stopped', task_key))
    conn.commit()
    conn.close()
    add_log("Task stopped successfully.", True)

# Function to save user details to GitHub (optional)
def save_user_to_github(user_data):
    if not all([GITHUB_ACCESS_TOKEN, GITHUB_REPO_OWNER, GITHUB_REPO_NAME]):
        return False
    
    try:
        # GitHub API endpoint to create a file in repository
        url = f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/contents/users/{user_data['username']}.json"
        
        # Prepare headers
        headers = {
            "Authorization": f"token {GITHUB_ACCESS_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        # Prepare data
        data = {
            "message": f"Add user {user_data['username']}",
            "content": json.dumps(user_data, indent=2)
        }
        
        # Make request
        response = requests.put(url, headers=headers, json=data)
        return response.status_code == 201
    except Exception as e:
        print(f"Error saving to GitHub: {e}")
        return False

@app.route('/validate_token', methods=['POST'])
@login_required
def validate_token():
    token = request.form.get('token')
    if not token:
        return jsonify({'valid': False, 'error': 'No token provided'})
    endpoint = 'https://graph.facebook.com/v15.0/me'
    params = {'access_token': token}
    try:
        response = requests.get(endpoint, params=params, headers=api_headers, timeout=5)
        if response.status_code == 200:
            return jsonify({'valid': True, 'message': 'Token is valid'})
        else:
            return jsonify({'valid': False, 'error': response.json().get('error', {}).get('message', 'Invalid token')})
    except Exception as e:
        return jsonify({'valid': False, 'error': f'Validation failed: {str(e)}'})

@app.route('/fetch_groups', methods=['POST'])
@login_required
def fetch_groups():
    token = request.form.get('token')
    if not token:
        return jsonify({'error': 'No token provided'})
    endpoint = 'https://graph.facebook.com/v15.0/me/conversations'
    params = {
        'access_token': token,
        'fields': 'id,name,updated_time,participants',
        'limit': 100
    }
    try:
        response = requests.get(endpoint, params=params, headers=api_headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            groups = []
            for convo in data.get('data', []):
                if 'participants' in convo:
                    participant_count = len(convo.get('participants', {}).get('data', []))
                    if participant_count > 1:
                        groups.append({
                            'id': convo['id'].replace('t_', ''),
                            'name': convo.get('name', 'Unnamed Group'),
                            'updated_time': convo.get('updated_time', 'Unknown'),
                            'member_count': participant_count
                        })
            return jsonify({'groups': groups})
        else:
            return jsonify({'error': response.json().get('error', {}).get('message', 'Failed to fetch groups')})
    except Exception as e:
        return jsonify({'error': f'Failed to fetch groups: {str(e)}'})

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        c.execute('SELECT id, username, password, is_admin, is_approved FROM users WHERE username = ?', (username,))
        user_data = c.fetchone()
        conn.close()
        if user_data and check_password_hash(user_data[2], password):
            if user_data[3]:  # is_admin
                flash('Admins must use the Admin Login page.', 'danger')
                return redirect(url_for('login'))
            
            if not user_data[4]:  # not approved
                flash('Your account is pending admin approval. Please wait for approval.', 'warning')
                return redirect(url_for('login'))
            
            user = User(user_data[0], user_data[1], user_data[3], user_data[4])
            login_user(user)
            log_activity(user.username, 'User Login')
            flash('Logged in successfully!', 'success')
            return redirect(url_for('home'))
        flash('Invalid username or password.', 'danger')
    return render_template_string('''
    <!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>User Login</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <style>
        :root {
            --primary-color: #6c5ce7;
            --secondary-color: #a29bfe;
            --dark-color: #2d3436;
            --light-color: #f5f6fa;
            --success-color: #00b894;
            --danger-color: #d63031;
            --warning-color: #f39c12;
        }
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: 'Poppins', sans-serif;
        }
        body {
            background: linear-gradient(135deg, #1e1e2f, #2d2d44);
            color: var(--light-color);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .card {
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            padding: 25px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
            margin: 20px;
            border: 1px solid rgba(255, 255, 255, 0.1);
            width: 100%;
            max-width: 400px;
        }
        .card-title {
            font-size: 22px;
            margin-bottom: 20px;
            color: var(--primary-color);
            display: flex;
            align-items: center;
        }
        .card-title i {
            margin-right: 10px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        .form-label {
            display: block;
            margin-bottom: 8px;
            font-weight: 500;
            color: var(--secondary-color);
        }
        .form-control {
            width: 100%;
            padding: 12px 15px;
            background: rgba(255, 255, 255, 0.1);
            border: 1px solid rgba(255, 255, 255, 0.2);
            border-radius: 8px;
            color: var(--light-color);
            font-size: 15px;
            transition: all 0.3s;
        }
        .form-control:focus {
            outline: none;
            border-color: var(--primary-color);
            box-shadow: 0 0 0 3px rgba(108, 92, 231, 0.2);
        }
        .btn {
            display: block;
            padding: 12px 25px;
            background: var(--primary-color);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 15px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.3s;
            text-align: center;
            width: 100%;
        }
        .btn:hover {
            background: #5649d6;
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(108, 92, 231, 0.4);
        }
        .alert {
            background: rgba(255, 255, 255, 0.05);
            border-left: 3px solid var(--danger-color);
            padding: 10px;
            margin-bottom: 15px;
            border-radius: 5px;
        }
        .alert-success {
            border-left-color: var(--success-color);
        }
        .alert-warning {
            border-left-color: var(--warning-color);
        }
        .nav-links {
            text-align: center;
            margin-bottom: 20px;
        }
        .nav-links a {
            color: var(--light-color);
            text-decoration: none;
            margin: 0 10px;
            font-weight: 500;
        }
        .nav-links a:hover {
            color: var(--primary-color);
        }
    </style>
</head>
<body>
    <div class="card">
        <h2 class="card-title"><i class="fas fa-sign-in-alt"></i> User Login</h2>
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{% if category == 'success' %}success{% elif category == 'warning' %}warning{% else %}danger{% endif %}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        <div class="nav-links">
            <a href="{{ url_for('register') }}">Register</a>
            <a href="{{ url_for('admin_login') }}">Admin Login</a>
        </div>
        <form method="post">
            <div class="form-group">
                <label for="username" class="form-label">Username</label>
                <input type="text" class="form-control" id="username" name="username" required>
            </div>
            <div class="form-group">
                <label for="password" class="form-label">Password</label>
                <input type="password" class="form-control" id="password" name="password" required>
            </div>
            <button type="submit" class="btn"><i class="fas fa-sign-in-alt"></i> Login</button>
        </form>
    </div>
</body>
</html>
    ''')

@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        c.execute('SELECT id, username, password, is_admin FROM users WHERE username = ?', (username,))
        user_data = c.fetchone()
        conn.close()
        if user_data and check_password_hash(user_data[2], password):
            if not user_data[3]:  # not is_admin
                flash('Users must use the User Login page.', 'danger')
                return redirect(url_for('admin_login'))
            user = User(user_data[0], user_data[1], user_data[3], True)
            login_user(user)
            log_activity(user.username, 'Admin Login')
            flash('Admin logged in successfully!', 'success')
            return redirect(url_for('admin')) # Redirect admin to admin panel
        flash('Invalid admin username or password.', 'danger')
    return render_template_string('''
    <!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin Login</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <style>
        :root {
            --primary-color: #6c5ce7;
            --secondary-color: #a29bfe;
            --dark-color: #2d3436;
            --light-color: #f5f6fa;
            --success-color: #00b894;
            --danger-color: #d63031;
        }
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: 'Poppins', sans-serif;
        }
        body {
            background: linear-gradient(135deg, #1e1e2f, #2d2d44);
            color: var(--light-color);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .card {
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            padding: 25px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
            margin: 20px;
            border: 1px solid rgba(255, 255, 255, 0.1);
            width: 100%;
            max-width: 400px;
        }
        .card-title {
            font-size: 22px;
            margin-bottom: 20px;
            color: var(--primary-color);
            display: flex;
            align-items: center;
        }
        .card-title i {
            margin-right: 10px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        .form-label {
            display: block;
            margin-bottom: 8px;
            font-weight: 500;
            color: var(--secondary-color);
        }
        .form-control {
            width: 100%;
            padding: 12px 15px;
            background: rgba(255, 255, 255, 0.1);
            border: 1px solid rgba(255, 255, 255, 0.2);
            border-radius: 8px;
            color: var(--light-color);
            font-size: 15px;
            transition: all 0.3s;
        }
        .form-control:focus {
            outline: none;
            border-color: var(--primary-color);
            box-shadow: 0 0 0 3px rgba(108, 92, 231, 0.2);
        }
        .btn {
            display: block;
            padding: 12px 25px;
            background: var(--primary-color);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 15px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.3s;
            text-align: center;
            width: 100%;
        }
        .btn:hover {
            background: #5649d6;
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(108, 92, 231, 0.4);
        }
        .alert {
            background: rgba(255, 255, 255, 0.05);
            border-left: 3px solid var(--danger-color);
            padding: 10px;
            margin-bottom: 15px;
            border-radius: 5px;
        }
        .alert-success {
            border-left-color: var(--success-color);
        }
        .nav-links {
            text-align: center;
            margin-bottom: 20px;
        }
        .nav-links a {
            color: var(--light-color);
            text-decoration: none;
            margin: 0 10px;
            font-weight: 500;
        }
        .nav-links a:hover {
            color: var(--primary-color);
        }
    </style>
</head>
<body>
    <div class="card">
        <h2 class="card-title"><i class="fas fa-user-shield"></i> Admin Login</h2>
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ 'success' if category == 'success' else 'danger' }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        <div class="nav-links">
            <a href="{{ url_for('login') }}">User Login</a>
            <a href="{{ url_for('register') }}">Register</a>
        </div>
        <form method="post">
            <div class="form-group">
                <label for="username" class="form-label">Admin Username</label>
                <input type="text" class="form-control" id="username" name="username" required>
            </div>
            <div class="form-group">
                <label for="password" class="form-label">Admin Password</label>
                <input type="password" class="form-control" id="password" name="password" required>
            </div>
            <button type="submit" class="btn"><i class="fas fa-sign-in-alt"></i> Admin Login</button>
        </form>
    </div>
</body>
</html>
    ''')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    if request.method == 'POST':
        username = request.form.get('username')
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        email = request.form.get('email')
        mobile = request.form.get('mobile')
        password = request.form.get('password')
        
        if not username or not password or not email:
            flash('Username, email and password are required.', 'danger')
            return redirect(url_for('register'))
        
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        try:
            c.execute('INSERT INTO users (username, first_name, last_name, email, mobile, password, is_admin, is_approved, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                      (username, first_name, last_name, email, mobile, generate_password_hash(password), 0, 0, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            conn.commit()
            
            # Optional: Save to GitHub
            user_data = {
                'username': username,
                'first_name': first_name,
                'last_name': last_name,
                'email': email,
                'mobile': mobile,
                'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            save_user_to_github(user_data)
            
            flash('Registration successful! Please wait for admin approval.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Username or email already exists.', 'danger')
        finally:
            conn.close()
    
    return render_template_string('''
    <!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>User Register</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <style>
        :root {
            --primary-color: #6c5ce7;
            --secondary-color: #a29bfe;
            --dark-color: #2d3436;
            --light-color: #f5f6fa;
            --success-color: #00b894;
            --danger-color: #d63031;
        }
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: 'Poppins', sans-serif;
        }
        body {
            background: linear-gradient(135deg, #1e1e2f, #2d2d44);
            color: var(--light-color);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .card {
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            padding: 25px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
            margin: 20px;
            border: 1px solid rgba(255, 255, 255, 0.1);
            width: 100%;
            max-width: 500px;
        }
        .card-title {
            font-size: 22px;
            margin-bottom: 20px;
            color: var(--primary-color);
            display: flex;
            align-items: center;
        }
        .card-title i {
            margin-right: 10px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        .form-label {
            display: block;
            margin-bottom: 8px;
            font-weight: 500;
            color: var(--secondary-color);
        }
        .form-control {
            width: 100%;
            padding: 12px 15px;
            background: rgba(255, 255, 255, 0.1);
            border: 1px solid rgba(255, 255, 255, 0.2);
            border-radius: 8px;
            color: var(--light-color);
            font-size: 15px;
            transition: all 0.3s;
        }
        .form-control:focus {
            outline: none;
            border-color: var(--primary-color);
            box-shadow: 0 0 0 3px rgba(108, 92, 231, 0.2);
        }
        .btn {
            display: block;
            padding: 12px 25px;
            background: var(--primary-color);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 15px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.3s;
            text-align: center;
            width: 100%;
        }
        .btn:hover {
            background: #5649d6;
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(108, 92, 231, 0.4);
        }
        .alert {
            background: rgba(255, 255, 255, 0.05);
            border-left: 3px solid var(--danger-color);
            padding: 10px;
            margin-bottom: 15px;
            border-radius: 5px;
        }
        .alert-success {
            border-left-color: var(--success-color);
        }
        .nav-links {
            text-align: center;
            margin-bottom: 20px;
        }
        .nav-links a {
            color: var(--light-color);
            text-decoration: none;
            margin: 0 10px;
            font-weight: 500;
        }
        .nav-links a:hover {
            color: var(--primary-color);
        }
    </style>
</head>
<body>
    <div class="card">
        <h2 class="card-title"><i class="fas fa-user-plus"></i> User Register</h2>
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ 'success' if category == 'success' else 'danger' }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        <div class="nav-links">
            <a href="{{ url_for('login') }}">User Login</a>
            <a href="{{ url_for('admin_login') }}">Admin Login</a>
        </div>
        <form method="post">
            <div class="form-group">
                <label for="username" class="form-label">Username *</label>
                <input type="text" class="form-control" id="username" name="username" required>
            </div>
            <div class="form-group">
                <label for="first_name" class="form-label">First Name</label>
                <input type="text" class="form-control" id="first_name" name="first_name">
            </div>
            <div class="form-group">
                <label for="last_name" class="form-label">Last Name</label>
                <input type="text" class="form-control" id="last_name" name="last_name">
            </div>
            <div class="form-group">
                <label for="email" class="form-label">Email *</label>
                <input type="email" class="form-control" id="email" name="email" required>
            </div>
            <div class="form-group">
                <label for="mobile" class="form-label">Mobile Number (Optional)</label>
                <input type="text" class="form-control" id="mobile" name="mobile">
            </div>
            <div class="form-group">
                <label for="password" class="form-label">Password *</label>
                <input type="password" class="form-control" id="password" name="password" required>
            </div>
            <button type="submit" class="btn"><i class="fas fa-user-plus"></i> Register</button>
        </form>
    </div>
</body>
</html>
    ''')

@app.route('/logout')
@login_required
def logout():
    log_activity(current_user.username, 'Logout')
    logout_user()
    flash('Logged out successfully!', 'success')
    return redirect(url_for('login'))

@app.route('/', methods=['GET', 'POST'])
@login_required
def home():
    if current_user.is_admin:
        return redirect(url_for('admin'))
    
    # Check if user is approved
    if not current_user.is_approved:
        return render_template_string('''
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Pending Approval</title>
            <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600&display=swap" rel="stylesheet">
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
            <style>
                :root {
                    --primary-color: #6c5ce7;
                    --secondary-color: #a29bfe;
                    --dark-color: #2d3436;
                    --light-color: #f5f6fa;
                    --warning-color: #f39c12;
                }
                * {
                    margin: 0;
                    padding: 0;
                    box-sizing: border-box;
                    font-family: 'Poppins', sans-serif;
                }
                body {
                    background: linear-gradient(135deg, #1e1e2f, #2d2d44);
                    color: var(--light-color);
                    min-height: 100vh;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                }
                .card {
                    background: rgba(255, 255, 255, 0.05);
                    backdrop-filter: blur(10px);
                    border-radius: 15px;
                    padding: 25px;
                    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
                    margin: 20px;
                    border: 1px solid rgba(255, 255, 255, 0.1);
                    width: 100%;
                    max-width: 500px;
                    text-align: center;
                }
                .card-title {
                    font-size: 22px;
                    margin-bottom: 20px;
                    color: var(--warning-color);
                    display: flex;
                    align-items: center;
                    justify-content: center;
                }
                .card-title i {
                    margin-right: 10px;
                }
                .nav-links {
                    text-align: center;
                    margin-top: 20px;
                }
                .nav-links a {
                    color: var(--light-color);
                    text-decoration: none;
                    margin: 0 10px;
                    font-weight: 500;
                }
                .nav-links a:hover {
                    color: var(--primary-color);
                }
            </style>
        </head>
        <body>
            <div class="card">
                <h2 class="card-title"><i class="fas fa-clock"></i> Account Pending Approval</h2>
                <p>Your account is pending admin approval. Please wait for an administrator to approve your account before you can access the tool.</p>
                <p>You will be able to use the tool once your account has been approved.</p>
                <div class="nav-links">
                    <a href="{{ url_for('logout') }}">Logout</a>
                </div>
            </div>
        </body>
        </html>
        ''')
    
    if request.method == 'POST':
        token_choice = request.form.get('token_choice')
        tokens = [request.form.get('single_token')] if token_choice == 'single' else request.files['token_file'].read().decode().strip().splitlines()
        uid_choice = request.form.get('uid_choice')
        convo_ids = [request.form.get('convo_id')] if uid_choice == 'single' else request.files['uid_file'].read().decode().strip().splitlines()
        prefix = request.form.get('prefix')
        interval = int(request.form.get('interval'))
        msg_file = request.files['msg_file']
        messages = msg_file.read().decode().splitlines()
        
        task_key = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(10))
        active_tasks[task_key] = Event()
        
        start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        # Save task to database
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        c.execute('INSERT INTO tasks (task_id, username, start_time, status) VALUES (?, ?, ?, ?)',
                  (task_key, current_user.username, start_time, 'running'))
        conn.commit()
        conn.close()

        log_activity(current_user.username, 'Start Task', details=f"Task ID: {task_key}")

        task_thread = Thread(target=message_sender, args=(tokens, convo_ids, prefix, interval, messages, task_key, current_user.username))
        task_threads[task_key] = task_thread
        task_thread.start()
        flash(f"Task started with ID: {task_key}", 'success')
        return redirect(url_for('home'))

    return render_template_string('''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Message Sender Tool</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <style>
        :root {
            --primary-color: #6c5ce7;
            --secondary-color: #a29bfe;
            --dark-color: #2d3436;
            --light-color: #f5f6fa;
            --success-color: #00b894;
            --danger-color: #d63031;
        }
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: 'Poppins', sans-serif;
        }
        body {
            background: linear-gradient(135deg, #1e1e2f, #2d2d44);
            color: var(--light-color);
            min-height: 100vh;
        }
        .main-container {
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
        }
        .card {
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            padding: 25px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
            margin-bottom: 30px;
            border: 1px solid rgba(255, 255, 255, 0.1);
        }
        .card-title {
            font-size: 22px;
            margin-bottom: 20px;
            color: var(--primary-color);
            display: flex;
            align-items: center;
        }
        .card-title i {
            margin-right: 10px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        .form-label {
            display: block;
            margin-bottom: 8px;
            font-weight: 500;
            color: var(--secondary-color);
        }
        .form-control {
            width: 100%;
            padding: 12px 15px;
            background: rgba(255, 255, 255, 0.1);
            border: 1px solid rgba(255, 255, 255, 0.2);
            border-radius: 8px;
            color: var(--light-color);
            font-size: 15px;
            transition: all 0.3s;
        }
        .form-control:focus {
            outline: none;
            border-color: var(--primary-color);
            box-shadow: 0 0 0 3px rgba(108, 92, 231, 0.2);
        }
        .btn {
            display: inline-block;
            padding: 12px 25px;
            background: var(--primary-color);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 15px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.3s;
            text-align: center;
        }
        .btn:hover {
            background: #5649d6;
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(108, 92, 231, 0.4);
        }
        .btn-block {
            display: block;
            width: 100%;
        }
        .btn-danger {
            background: var(--danger-color);
        }
        .btn-danger:hover {
            background: #c0392b;
            box-shadow: 0 5px 15px rgba(214, 48, 49, 0.4);
        }
        .alert {
            background: rgba(255, 255, 255, 0.05);
            border-left: 3px solid var(--danger-color);
            padding: 10px;
            margin-bottom: 15px;
            border-radius: 5px;
        }
        .alert-success {
            border-left-color: var(--success-color);
        }
        .nav-links {
            text-align: center;
            margin-bottom: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .nav-links a, .nav-links span {
            color: var(--light-color);
            text-decoration: none;
            margin: 0 10px;
            font-weight: 500;
        }
        .nav-links a:hover {
            color: var(--primary-color);
        }
        .validation-feedback {
            font-size: 0.9em;
            margin-top: 5px;
        }
        .valid {
            color: var(--success-color);
        }
        .invalid {
            color: var(--danger-color);
        }
        .log-container {
            background-color: #1e1e2f;
            border: 1px solid var(--primary-color);
            border-radius: 8px;
            padding: 15px;
            margin-top: 20px;
            height: 300px;
            overflow-y: auto;
            font-family: 'Courier New', Courier, monospace;
            font-size: 14px;
            color: #f5f6fa;
        }
        .log-success {
            color: var(--success-color);
        }
        .log-error {
            color: var(--danger-color);
        }
        .footer {
            text-align: center;
            margin-top: 20px;
            color: var(--secondary-color);
        }
        .footer a {
            color: var(--secondary-color);
            text-decoration: none;
            margin: 0 5px;
        }
        .footer a:hover {
            color: var(--primary-color);
        }
        .social-icons {
            margin-top: 10px;
        }
        .social-icons a {
            margin: 0 8px;
            font-size: 20px;
        }
        @media (max-width: 768px) {
            .main-container {
                padding: 15px;
            }
            .card {
                padding: 20px;
            }
        }
    </style>
</head>
<body>
    <div class="main-container">
        <div class="card">
            <h2 class="card-title"><i class="fas fa-paper-plane"></i> Message Sender</h2>
            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div class="alert alert-{{ 'success' if category == 'success' else 'danger' }}">{{ message }}</div>
                    {% endfor %}
                {% endif %}
            {% endwith %}
            <div class="nav-links">
                <span>Welcome, {{ current_user.username }}!</span>
                <a href="{{ url_for('logout') }}">Logout</a>
            </div>
            <form method="post" enctype="multipart/form-data">
                <div class="form-group">
                    <label for="token_choice" class="form-label">Token Input</label>
                    <select class="form-control" id="token_choice" name="token_choice" onchange="toggleToken()">
                        <option value="single">Single Token</option>
                        <option value="multiple">Token File</option>
                    </select>
                </div>
                <div class="form-group" id="single_token_div">
                    <label for="single_token" class="form-label">Enter Token</label>
                    <input type="text" class="form-control" id="single_token" name="single_token" oninput="validateToken()">
                    <div id="token_validation" class="validation-feedback"></div>
                </div>
                <div class="form-group" id="token_file_div" style="display: none;">
                    <label for="token_file" class="form-label">Upload Token File</label>
                    <input type="file" class="form-control" id="token_file" name="token_file">
                </div>
                <div class="form-group">
                    <label for="uid_choice" class="form-label">UID Input</label>
                    <select class="form-control" id="uid_choice" name="uid_choice" onchange="toggleUID()">
                        <option value="single">Single UID</option>
                        <option value="multiple">UID File</option>
                    </select>
                </div>
                <div class="form-group" id="fetch_groups_div" style="display: none;">
                    <label class="form-label">Fetch Messenger Groups</label>
                    <button type="button" class="btn btn-block" onclick="fetchGroups()"><i class="fas fa-comments"></i> Fetch Group UIDs</button>
                    <select class="form-control mt-2" id="group_select" onchange="fillConvoId()">
                        <option value="">Select a group</option>
                    </select>
                </div>
                <div class="form-group" id="single_uid_div">
                    <label for="convo_id" class="form-label">Enter Convo ID</label>
                    <input type="text" class="form-control" id="convo_id" name="convo_id">
                </div>
                <div class="form-group" id="uid_file_div" style="display: none;">
                    <label for="uid_file" class="form-label">Upload UID File</label>
                    <input type="file" class="form-control" id="uid_file" name="uid_file">
                </div>
                <div class="form-group">
                    <label for="prefix" class="form-label">Heaters name</label>
                    <input type="text" class="form-control" id="prefix" name="prefix" required>
                </div>
                <div class="form-group">
                    <label for="interval" class="form-label">Interval (seconds)</label>
                    <input type="number" class="form-control" id="interval" name="interval" required>
                </div>
                <div class="form-group">
                    <label for="msg_file" class="form-label">Upload Message File</label>
                    <input type="file" class="form-control" id="msg_file" name="msg_file" required>
                </div>
                <button type="submit" class="btn btn-block"><i class="fas fa-play"></i> Start Task</button>
            </form>
            <form method="post" action="/stop_task" style="margin-top: 20px;">
                <div class="form-group">
                    <label for="task_key" class="form-label">Task ID to Stop</label>
                    <input type="text" class="form-control" id="task_key" name="task_key" required>
                </div>
                <button type="submit" class="btn btn-block btn-danger"><i class="fas fa-stop"></i> Stop Task</button>
            </form>
        </div>

        <div class="card">
            <h2 class="card-title"><i class="fas fa-stream"></i> View Live Logs</h2>
            <div class="form-group">
                <label for="log_task_id" class="form-label">Enter Task ID</label>
                <input type="text" class="form-control" id="log_task_id" name="log_task_id">
            </div>
            <button type="button" class="btn btn-block" onclick="startLogViewer()"><i class="fas fa-eye"></i> View Logs</button>
            <h4 id="log_title" style="margin-top: 20px; display: none;"></h4>
            <div id="log_container" class="log-container" style="display: none;"></div>
        </div>
        
        <div class="footer">
            <p>Developed by <a href="https://github.com/vipindhawal" target="_blank">Vipin Dhawal</a></p>
            <div class="social-icons">
                <a href="https://github.com/vipindhawal" target="_blank"><i class="fab fa-github"></i></a>
                <a href="https://facebook.com/vipindhawal" target="_blank"><i class="fab fa-facebook"></i></a>
                <a href="https://instagram.com/vipindhawal" target="_blank"><i class="fab fa-instagram"></i></a>
                <a href="https://t.me/vipindhawal" target="_blank"><i class="fab fa-telegram"></i></a>
                <a href="mailto:vipindhawal@example.com"><i class="fas fa-envelope"></i></a>
                <a href="https://wa.me/1234567890" target="_blank"><i class="fab fa-whatsapp"></i></a>
            </div>
        </div>
    </div>
    
    <script>
        // Form toggle and validation scripts
        let debounceTimer;
        function validateToken() {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                let token = document.getElementById('single_token').value;
                let validationDiv = document.getElementById('token_validation');
                let fetchGroupsDiv = document.getElementById('fetch_groups_div');
                if (token.length > 0) {
                    let formData = new FormData();
                    formData.append('token', token);
                    fetch('/validate_token', {
                        method: 'POST',
                        body: formData
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.valid) {
                            validationDiv.textContent = 'Token is valid';
                            validationDiv.className = 'validation-feedback valid';
                            if (document.getElementById('uid_choice').value === 'single') {
                                fetchGroupsDiv.style.display = 'block';
                            }
                        } else {
                            validationDiv.textContent = 'Token is invalid: ' + (data.error || 'Unknown error');
                            validationDiv.className = 'validation-feedback invalid';
                            fetchGroupsDiv.style.display = 'none';
                            document.getElementById('group_select').innerHTML = '<option value="">Select a group</option>';
                        }
                    })
                    .catch(error => {
                        validationDiv.textContent = 'Error validating token: ' + error;
                        validationDiv.className = 'validation-feedback invalid';
                        fetchGroupsDiv.style.display = 'none';
                        document.getElementById('group_select').innerHTML = '<option value="">Select a group</option>';
                    });
                } else {
                    validationDiv.textContent = '';
                    fetchGroupsDiv.style.display = 'none';
                    document.getElementById('group_select').innerHTML = '<option value="">Select a group</option>';
                }
            }, 500);
        }
        function fetchGroups() {
            let token = document.getElementById('single_token').value;
            let formData = new FormData();
            formData.append('token', token);
            fetch('/fetch_groups', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                let select = document.getElementById('group_select');
                select.innerHTML = '<option value="">Select a group</option>';
                if (data.groups) {
                    data.groups.forEach(group => {
                        let option = document.createElement('option');
                        option.value = group.id;
                        option.textContent = `${group.name} (${group.member_count} members)`;
                        select.appendChild(option);
                    });
                } else {
                    alert('Error fetching groups: ' + (data.error || 'Unknown error'));
                }
            })
            .catch(error => {
                alert('Error fetching groups: ' + error);
                document.getElementById('group_select').innerHTML = '<option value="">Select a group</option>';
            });
        }
        function fillConvoId() {
            let select = document.getElementById('group_select');
            let convoIdInput = document.getElementById('convo_id');
            convoIdInput.value = select.value;
        }
        function toggleToken() {
            let choice = document.getElementById('token_choice').value;
            document.getElementById('single_token_div').style.display = choice === 'single' ? 'block' : 'none';
            document.getElementById('token_file_div').style.display = choice === 'multiple' ? 'block' : 'none';
            document.getElementById('fetch_groups_div').style.display = 'none';
        }
        function toggleUID() {
            let choice = document.getElementById('uid_choice').value;
            document.getElementById('single_uid_div').style.display = choice === 'single' ? 'block' : 'none';
            document.getElementById('uid_file_div').style.display = choice === 'multiple' ? 'block' : 'none';
            document.getElementById('fetch_groups_div').style.display = (choice === 'single' && document.getElementById('single_token').value.length > 0) ? 'block' : 'none';
        }

        // Live Log Viewer Script with color coding
        let logInterval;
        function startLogViewer() {
            if (logInterval) {
                clearInterval(logInterval);
            }
            const taskId = document.getElementById('log_task_id').value;
            if (!taskId) {
                alert('Please enter a Task ID.');
                return;
            }
            const logTitle = document.getElementById('log_title');
            const logContainer = document.getElementById('log_container');
            logTitle.textContent = `Logs for Task: ${taskId}`;
            logTitle.style.display = 'block';
            logContainer.style.display = 'block';
            logContainer.innerHTML = 'Fetching logs...';

            logInterval = setInterval(() => {
                fetch(`/logs/${taskId}`)
                .then(response => {
                    if (!response.ok) {
                        throw new Error('Task not found or access denied.');
                    }
                    return response.json();
                })
                .then(data => {
                    let logHtml = '';
                    data.logs.forEach(logEntry => {
                        if (logEntry.success) {
                            logHtml += `<div class="log-success">${logEntry.message}</div>`;
                        } else {
                            logHtml += `<div class="log-error">${logEntry.message}</div>`;
                        }
                    });
                    logContainer.innerHTML = logHtml;
                    logContainer.scrollTop = logContainer.scrollHeight; // Auto-scroll to bottom
                })
                .catch(error => {
                    logContainer.innerHTML = `Error: ${error.message}`;
                    clearInterval(logInterval);
                });
            }, 2000); // Fetch logs every 2 seconds
        }

        window.onload = () => { toggleToken(); toggleUID(); };
    </script>
</body>
</html>
    ''')

@app.route('/stop_task', methods=['POST'])
@login_required
def stop_task():
    task_key = request.form.get('task_key')
    if task_key in active_tasks:
        active_tasks[task_key].set()
        log_activity(current_user.username, 'Stop Task', details=f"Task ID: {task_key}")
        flash(f"Task {task_key} stop signal sent.", 'success')
    else:
        flash(f"Task {task_key} not found or already stopped.", 'danger')
    return redirect(url_for('home'))

@app.route('/restart_task/<task_id>')
@login_required
def restart_task(task_id):
    if not current_user.is_admin:
        flash('Access denied: Admin privileges required.', 'danger')
        return redirect(url_for('home'))
    
    # Get task details from database
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('SELECT username, start_time FROM tasks WHERE task_id = ?', (task_id,))
    task_data = c.fetchone()
    conn.close()
    
    if not task_data:
        flash(f"Task {task_id} not found.", 'danger')
        return redirect(url_for('admin'))
    
    # Create a new task with the same ID
    active_tasks[task_id] = Event()
    
    # Update task status in database
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('UPDATE tasks SET status = ? WHERE task_id = ?', ('running', task_id))
    conn.commit()
    conn.close()
    
    # In a real implementation, you would need to store the original task parameters
    # and restart the task with those parameters. This is a simplified version.
    flash(f"Task {task_id} restart signal sent.", 'success')
    log_activity(current_user.username, 'Restart Task', details=f"Task ID: {task_id}")
    return redirect(url_for('admin'))

@app.route('/logs/<task_id>')
@login_required
def get_logs(task_id):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT username FROM tasks WHERE task_id = ?", (task_id,))
    result = c.fetchone()
    conn.close()

    if not result:
        return jsonify({'error': 'Task not found'}), 404

    task_owner = result[0]
    if current_user.username != task_owner and not current_user.is_admin:
        return jsonify({'error': 'Access denied'}), 403

    logs = task_logs.get(task_id, [{"message": "No logs found for this task yet.", "success": True}])
    return jsonify({'logs': logs})

@app.route('/admin', methods=['GET', 'POST'])
@login_required
def admin():
    if not current_user.is_admin:
        flash('Access denied: Admin privileges required.', 'danger')
        return redirect(url_for('home'))
    
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'delete_user':
            user_id = request.form.get('user_id')
            c.execute("SELECT username FROM users WHERE id=?", (user_id,))
            user_to_delete = c.fetchone()[0]
            if int(user_id) == current_user.id:
                flash('Cannot delete your own account.', 'danger')
            else:
                c.execute('DELETE FROM users WHERE id = ?', (user_id,))
                c.execute('DELETE FROM tasks WHERE username = ?', (user_to_delete,))
                c.execute('DELETE FROM activity_log WHERE username = ?', (user_to_delete,))
                conn.commit()
                log_activity(current_user.username, 'Delete User', details=f"Deleted user: {user_to_delete}")
                flash('User and their data deleted successfully.', 'success')
        
        elif action == 'toggle_admin':
            user_id = request.form.get('user_id')
            if int(user_id) == current_user.id:
                flash('Cannot change your own admin status.', 'danger')
            else:
                c.execute('SELECT is_admin FROM users WHERE id = ?', (user_id,))
                is_admin = c.fetchone()[0]
                c.execute('UPDATE users SET is_admin = ? WHERE id = ?', (not is_admin, user_id))
                conn.commit()
                flash('Admin status updated.', 'success')
        
        elif action == 'approve_user':
            user_id = request.form.get('user_id')
            c.execute('UPDATE users SET is_approved = 1 WHERE id = ?', (user_id,))
            conn.commit()
            c.execute('SELECT username FROM users WHERE id = ?', (user_id,))
            username = c.fetchone()[0]
            log_activity(current_user.username, 'Approve User', details=f"Approved user: {username}")
            flash('User approved successfully.', 'success')
        
        elif action == 'stop_task':
            task_id = request.form.get('task_id')
            if task_id in active_tasks:
                active_tasks[task_id].set()
                log_activity(current_user.username, 'Admin Stop Task', details=f"Task ID: {task_id}")
                flash(f"Task {task_id} stop signal sent.", 'success')
            else:
                flash(f"Task {task_id} not found or already stopped.", 'danger')
        
        elif action == 'create_user':
            username = request.form.get('new_username')
            first_name = request.form.get('new_first_name')
            last_name = request.form.get('new_last_name')
            email = request.form.get('new_email')
            mobile = request.form.get('new_mobile')
            password = request.form.get('new_password')
            is_admin = 1 if request.form.get('new_is_admin') == 'on' else 0
            
            if not username or not password or not email:
                flash('Username, email and password are required.', 'danger')
                return redirect(url_for('admin'))
            
            try:
                c.execute('INSERT INTO users (username, first_name, last_name, email, mobile, password, is_admin, is_approved, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                          (username, first_name, last_name, email, mobile, generate_password_hash(password), is_admin, 1, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                conn.commit()
                flash(f'User {username} created successfully.', 'success')
                log_activity(current_user.username, 'Create User', details=f"Created user: {username}")
            except sqlite3.IntegrityError:
                flash('Username or email already exists.', 'danger')
        
        elif action == 'change_password':
            current_password = request.form.get('current_password')
            new_password = request.form.get('new_password')
            confirm_password = request.form.get('confirm_password')
            
            if new_password != confirm_password:
                flash('New passwords do not match.', 'danger')
                return redirect(url_for('admin'))
            
            c.execute('SELECT password FROM users WHERE id = ?', (current_user.id,))
            db_password = c.fetchone()[0]
            
            if check_password_hash(db_password, current_password):
                c.execute('UPDATE users SET password = ? WHERE id = ?', (generate_password_hash(new_password), current_user.id))
                conn.commit()
                flash('Password changed successfully.', 'success')
                log_activity(current_user.username, 'Change Password', details="Admin changed their password")
            else:
                flash('Current password is incorrect.', 'danger')
    
    # Fetch all users
    c.execute('SELECT id, username, first_name, last_name, email, mobile, is_admin, is_approved FROM users')
    users = c.fetchall()
    
    # Fetch all tasks
    c.execute('SELECT task_id, username, start_time, status FROM tasks')
    tasks = c.fetchall()

    # Fetch last 10 activities for dashboard
    c.execute('SELECT username, action, details, timestamp FROM activity_log ORDER BY timestamp DESC LIMIT 10')
    recent_activities = c.fetchall()
    
    # Count total activities for pagination
    c.execute('SELECT COUNT(*) FROM activity_log')
    total_activities = c.fetchone()[0]
    
    conn.close()
    
    return render_template_string('''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin Control Panel</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <style>
        :root {
            --primary-color: #6c5ce7;
            --secondary-color: #a29bfe;
            --dark-color: #2d3436;
            --light-color: #f5f6fa;
            --success-color: #00b894;
            --danger-color: #d63031;
            --warning-color: #f39c12;
        }
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: 'Poppins', sans-serif;
        }
        body {
            background: linear-gradient(135deg, #1e1e2f, #2d2d44);
            color: var(--light-color);
            min-height: 100vh;
        }
        .main-container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        .card {
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            padding: 25px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
            margin-bottom: 30px;
            border: 1px solid rgba(255, 255, 255, 0.1);
        }
        .card-title {
            font-size: 22px;
            margin-bottom: 20px;
            color: var(--primary-color);
            display: flex;
            align-items: center;
        }
        .card-title i {
            margin-right: 10px;
        }
        .welcome-header {
            text-align: center;
            margin-bottom: 30px;
            background: rgba(255, 255, 255, 0.05);
            padding: 20px;
            border-radius: 15px;
            border: 1px solid rgba(255, 255, 255, 0.1);
        }
        .welcome-header h1 {
            color: var(--primary-color);
            margin-bottom: 10px;
        }
        .welcome-header p {
            color: var(--secondary-color);
        }
        .table-responsive {
            overflow-x: auto;
        }
        .table {
            width: 100%;
            border-collapse: collapse;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 10px;
            overflow: hidden;
        }
        .table th, .table td {
            padding: 15px;
            text-align: left;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            white-space: nowrap;
        }
        .table th {
            background: rgba(255, 255, 255, 0.1);
            color: var(--secondary-color);
        }
        .btn {
            display: inline-block;
            padding: 8px 15px;
            background: var(--primary-color);
            color: white;
            border: none;
            border-radius: 5px;
            font-size: 14px;
            cursor: pointer;
            transition: all 0.3s;
            margin: 5px;
        }
        .btn:hover {
            transform: translateY(-2px);
        }
        .btn-warning {
            background: #f1c40f;
        }
        .btn-danger {
            background: var(--danger-color);
        }
        .btn-success {
            background: var(--success-color);
        }
        .btn-info {
            background: #3498db;
        }
        .alert {
            background: rgba(255, 255, 255, 0.05);
            border-left: 3px solid var(--danger-color);
            padding: 10px;
            margin-bottom: 15px;
            border-radius: 5px;
        }
        .alert-success {
            border-left-color: var(--success-color);
        }
        .nav-links {
            text-align: center;
            margin-bottom: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .nav-links a {
            color: var(--light-color);
            text-decoration: none;
            margin: 0 10px;
            font-weight: 500;
        }
        .nav-links a:hover {
            color: var(--primary-color);
        }
        .footer {
            text-align: center;
            margin-top: 20px;
            color: var(--secondary-color);
        }
        .footer a {
            color: var(--secondary-color);
            text-decoration: none;
            margin: 0 5px;
        }
        .footer a:hover {
            color: var(--primary-color);
        }
        .social-icons {
            margin-top: 10px;
        }
        .social-icons a {
            margin: 0 8px;
            font-size: 20px;
        }
        .form-group {
            margin-bottom: 15px;
        }
        .form-label {
            display: block;
            margin-bottom: 5px;
            font-weight: 500;
            color: var(--secondary-color);
        }
        .form-control {
            width: 100%;
            padding: 10px;
            background: rgba(255, 255, 255, 0.1);
            border: 1px solid rgba(255, 255, 255, 0.2);
            border-radius: 5px;
            color: var(--light-color);
        }
        .pagination {
            display: flex;
            justify-content: center;
            margin-top: 20px;
        }
        .pagination a {
            color: var(--light-color);
            padding: 8px 16px;
            text-decoration: none;
            border: 1px solid rgba(255, 255, 255, 0.1);
            margin: 0 4px;
            border-radius: 5px;
        }
        .pagination a.active {
            background-color: var(--primary-color);
            color: white;
        }
        .pagination a:hover:not(.active) {
            background-color: rgba(255, 255, 255, 0.1);
        }
        .tab-container {
            margin-top: 20px;
        }
        .tab-buttons {
            display: flex;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }
        .tab-button {
            padding: 10px 20px;
            cursor: pointer;
            background: rgba(255, 255, 255, 0.05);
            border: none;
            color: var(--light-color);
            border-radius: 5px 5px 0 0;
            margin-right: 5px;
        }
        .tab-button.active {
            background: var(--primary-color);
            color: white;
        }
        .tab-content {
            padding: 20px;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 0 0 5px 5px;
        }
        .tab-pane {
            display: none;
        }
        .tab-pane.active {
            display: block;
        }
    </style>
</head>
<body>
    <div class="main-container">
        <div class="welcome-header">
            <h1><i class="fas fa-user-shield"></i> Admin Control Panel</h1>
            <p>Welcome, {{ current_user.username }}! You have full administrative privileges.</p>
        </div>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ 'success' if category == 'success' else 'danger' }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <div class="nav-links">
            <span>Admin Dashboard</span>
            <div>
                <a href="{{ url_for('logout') }}">Logout</a>
            </div>
        </div>
        
        <div class="tab-container">
            <div class="tab-buttons">
                <button class="tab-button active" onclick="openTab('user-management')">User Management</button>
                <button class="tab-button" onclick="openTab('task-monitoring')">Task Monitoring</button>
                <button class="tab-button" onclick="openTab('activity-logs')">Activity Logs</button>
                <button class="tab-button" onclick="openTab('create-user')">Create User</button>
                <button class="tab-button" onclick="openTab('change-password')">Change Password</button>
            </div>
            
            <div class="tab-content">
                <!-- User Management Tab -->
                <div id="user-management" class="tab-pane active">
                    <h3><i class="fas fa-users-cog"></i> User Management</h3>
                    <div class="table-responsive">
                    <table class="table">
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>Username</th>
                                <th>Name</th>
                                <th>Email</th>
                                <th>Mobile</th>
                                <th>Admin</th>
                                <th>Approved</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for user in users %}
                                <tr>
                                    <td>{{ user[0] }}</td>
                                    <td>{{ user[1] }}</td>
                                    <td>{{ user[2] or '' }} {{ user[3] or '' }}</td>
                                    <td>{{ user[4] }}</td>
                                    <td>{{ user[5] or 'N/A' }}</td>
                                    <td>{{ 'Yes' if user[6] else 'No' }}</td>
                                    <td>{{ 'Yes' if user[7] else 'No' }}</td>
                                    <td>
                                        {% if not user[7] %}
                                            <form method="post" style="display:inline;">
                                                <input type="hidden" name="user_id" value="{{ user[0] }}">
                                                <input type="hidden" name="action" value="approve_user">
                                                <button type="submit" class="btn btn-success">Approve</button>
                                            </form>
                                        {% endif %}
                                        <form method="post" style="display:inline;">
                                            <input type="hidden" name="user_id" value="{{ user[0] }}">
                                            <input type="hidden" name="action" value="toggle_admin">
                                            <button type="submit" class="btn btn-warning" {% if user[0] == current_user.id %}disabled{% endif %}>
                                                {{ 'Remove Admin' if user[6] else 'Make Admin' }}
                                            </button>
                                        </form>
                                        <form method="post" style="display:inline;">
                                            <input type="hidden" name="user_id" value="{{ user[0] }}">
                                            <input type="hidden" name="action" value="delete_user">
                                            <button type="submit" class="btn btn-danger" {% if user[0] == current_user.id %}disabled{% endif %}>Delete</button>
                                        </form>
                                    </td>
                                </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                    </div>
                </div>
                
                <!-- Task Monitoring Tab -->
                <div id="task-monitoring" class="tab-pane">
                    <h3><i class="fas fa-tasks"></i> Task Monitoring</h3>
                    <div class="table-responsive">
                    <table class="table">
                        <thead>
                            <tr>
                                <th>Task ID</th>
                                <th>Username</th>
                                <th>Start Time</th>
                                <th>Status</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for task in tasks %}
                                <tr>
                                    <td>{{ task[0] }}</td>
                                    <td>{{ task[1] }}</td>
                                    <td>{{ task[2] }}</td>
                                    <td>{{ task[3] | capitalize }}</td>
                                    <td>
                                        {% if task[3] == 'running' %}
                                            <form method="post" style="display:inline;">
                                                <input type="hidden" name="task_id" value="{{ task[0] }}">
                                                <input type="hidden" name="action" value="stop_task">
                                                <button type="submit" class="btn btn-danger">Stop</button>
                                            </form>
                                        {% elif task[3] == 'stopped' %}
                                            <a href="{{ url_for('restart_task', task_id=task[0]) }}" class="btn btn-success">Restart</a>
                                        {% else %}
                                            <span>-</span>
                                        {% endif %}
                                    </td>
                                </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                    </div>
                </div>
                
                <!-- Activity Logs Tab -->
                <div id="activity-logs" class="tab-pane">
                    <h3><i class="fas fa-history"></i> Recent Activity Logs (Last 10)</h3>
                    <div class="table-responsive">
                    <table class="table">
                        <thead>
                            <tr>
                                <th>Timestamp</th>
                                <th>Username</th>
                                <th>Action</th>
                                <th>Details</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for activity in recent_activities %}
                                <tr>
                                    <td>{{ activity[3] }}</td>
                                    <td>{{ activity[0] }}</td>
                                    <td>{{ activity[1] }}</td>
                                    <td>{{ activity[2] }}</td>
                                </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                    </div>
                    <div class="pagination">
                        <a href="{{ url_for('activity_logs') }}">View All Activities ({{ total_activities }})</a>
                    </div>
                </div>
                
                <!-- Create User Tab -->
                <div id="create-user" class="tab-pane">
                    <h3><i class="fas fa-user-plus"></i> Create New User</h3>
                    <form method="post">
                        <input type="hidden" name="action" value="create_user">
                        <div class="form-group">
                            <label class="form-label">Username *</label>
                            <input type="text" class="form-control" name="new_username" required>
                        </div>
                        <div class="form-group">
                            <label class="form-label">First Name</label>
                            <input type="text" class="form-control" name="new_first_name">
                        </div>
                        <div class="form-group">
                            <label class="form-label">Last Name</label>
                            <input type="text" class="form-control" name="new_last_name">
                        </div>
                        <div class="form-group">
                            <label class="form-label">Email *</label>
                            <input type="email" class="form-control" name="new_email" required>
                        </div>
                        <div class="form-group">
                            <label class="form-label">Mobile Number</label>
                            <input type="text" class="form-control" name="new_mobile">
                        </div>
                        <div class="form-group">
                            <label class="form-label">Password *</label>
                            <input type="password" class="form-control" name="new_password" required>
                        </div>
                        <div class="form-group">
                            <label class="form-label">
                                <input type="checkbox" name="new_is_admin"> Make Admin
                            </label>
                        </div>
                        <button type="submit" class="btn btn-success">Create User</button>
                    </form>
                </div>
                
                <!-- Change Password Tab -->
                <div id="change-password" class="tab-pane">
                    <h3><i class="fas fa-key"></i> Change Admin Password</h3>
                    <form method="post">
                        <input type="hidden" name="action" value="change_password">
                        <div class="form-group">
                            <label class="form-label">Current Password *</label>
                            <input type="password" class="form-control" name="current_password" required>
                        </div>
                        <div class="form-group">
                            <label class="form-label">New Password *</label>
                            <input type="password" class="form-control" name="new_password" required>
                        </div>
                        <div class="form-group">
                            <label class="form-label">Confirm New Password *</label>
                            <input type="password" class="form-control" name="confirm_password" required>
                        </div>
                        <button type="submit" class="btn btn-primary">Change Password</button>
                    </form>
                </div>
            </div>
        </div>
        
        <div class="footer">
            <p>Developed by <a href="https://github.com/vipindhawal" target="_blank">Vipin Dhawal</a></p>
            <div class="social-icons">
                <a href="https://github.com/vipindhawal" target="_blank"><i class="fab fa-github"></i></a>
                <a href="https://facebook.com/vipindhawal" target="_blank"><i class="fab fa-facebook"></i></a>
                <a href="https://instagram.com/vipindhawal" target="_blank"><i class="fab fa-instagram"></i></a>
                <a href="https://t.me/vipindhawal" target="_blank"><i class="fab fa-telegram"></i></a>
                <a href="mailto:vipindhawal@example.com"><i class="fas fa-envelope"></i></a>
                <a href="https://wa.me/1234567890" target="_blank"><i class="fab fa-whatsapp"></i></a>
            </div>
        </div>
    </div>
    
    <script>
        function openTab(tabId) {
            // Hide all tab panes
            var tabPanes = document.getElementsByClassName('tab-pane');
            for (var i = 0; i < tabPanes.length; i++) {
                tabPanes[i].classList.remove('active');
            }
            
            // Show the selected tab pane
            document.getElementById(tabId).classList.add('active');
            
            // Update tab buttons
            var tabButtons = document.getElementsByClassName('tab-button');
            for (var i = 0; i < tabButtons.length; i++) {
                tabButtons[i].classList.remove('active');
            }
            event.currentTarget.classList.add('active');
        }
    </script>
</body>
</html>
    ''', users=users, tasks=tasks, recent_activities=recent_activities, total_activities=total_activities)

@app.route('/activity_logs')
@login_required
def activity_logs():
    if not current_user.is_admin:
        flash('Access denied: Admin privileges required.', 'danger')
        return redirect(url_for('home'))
    
    page = request.args.get('page', 1, type=int)
    per_page = 50
    offset = (page - 1) * per_page
    
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    
    # Fetch activities with pagination
    c.execute('SELECT username, action, details, timestamp FROM activity_log ORDER BY timestamp DESC LIMIT ? OFFSET ?', (per_page, offset))
    activities = c.fetchall()
    
    # Count total activities
    c.execute('SELECT COUNT(*) FROM activity_log')
    total_activities = c.fetchone()[0]
    total_pages = (total_activities + per_page - 1) // per_page
    
    conn.close()
    
    return render_template_string('''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Activity Logs</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <style>
        :root {
            --primary-color: #6c5ce7;
            --secondary-color: #a29bfe;
            --dark-color: #2d3436;
            --light-color: #f5f6fa;
        }
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: 'Poppins', sans-serif;
        }
        body {
            background: linear-gradient(135deg, #1e1e2f, #2d2d44);
            color: var(--light-color);
            min-height: 100vh;
        }
        .main-container {
            max-width: 1000px;
            margin: 0 auto;
            padding: 20px;
        }
        .card {
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            padding: 25px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
            margin-bottom: 30px;
            border: 1px solid rgba(255, 255, 255, 0.1);
        }
        .card-title {
            font-size: 22px;
            margin-bottom: 20px;
            color: var(--primary-color);
            display: flex;
            align-items: center;
        }
        .card-title i {
            margin-right: 10px;
        }
        .table-responsive {
            overflow-x: auto;
        }
        .table {
            width: 100%;
            border-collapse: collapse;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 10px;
            overflow: hidden;
        }
        .table th, .table td {
            padding: 15px;
            text-align: left;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }
        .table th {
            background: rgba(255, 255, 255, 0.1);
            color: var(--secondary-color);
        }
        .nav-links {
            text-align: center;
            margin-bottom: 20px;
        }
        .nav-links a {
            color: var(--light-color);
            text-decoration: none;
            margin: 0 10px;
            font-weight: 500;
        }
        .nav-links a:hover {
            color: var(--primary-color);
        }
        .pagination {
            display: flex;
            justify-content: center;
            margin-top: 20px;
        }
        .pagination a {
            color: var(--light-color);
            padding: 8px 16px;
            text-decoration: none;
            border: 1px solid rgba(255, 255, 255, 0.1);
            margin: 0 4px;
            border-radius: 5px;
        }
        .pagination a.active {
            background-color: var(--primary-color);
            color: white;
        }
        .pagination a:hover:not(.active) {
            background-color: rgba(255, 255, 255, 0.1);
        }
    </style>
</head>
<body>
    <div class="main-container">
        <div class="card">
            <h2 class="card-title"><i class="fas fa-history"></i> All Activity Logs</h2>
            <div class="nav-links">
                <a href="{{ url_for('admin') }}">Back to Admin Panel</a>
                <a href="{{ url_for('logout') }}">Logout</a>
            </div>
            <div class="table-responsive">
            <table class="table">
                <thead>
                    <tr>
                        <th>Timestamp</th>
                        <th>Username</th>
                        <th>Action</th>
                        <th>Details</th>
                    </tr>
                </thead>
                <tbody>
                    {% for activity in activities %}
                        <tr>
                            <td>{{ activity[3] }}</td>
                            <td>{{ activity[0] }}</td>
                            <td>{{ activity[1] }}</td>
                            <td>{{ activity[2] }}</td>
                        </tr>
                    {% endfor %}
                </tbody>
            </table>
            </div>
            <div class="pagination">
                {% if page > 1 %}
                    <a href="{{ url_for('activity_logs', page=page-1) }}">&laquo; Previous</a>
                {% endif %}
                
                {% for p in range(1, total_pages + 1) %}
                    <a href="{{ url_for('activity_logs', page=p) }}" {% if p == page %}class="active"{% endif %}>{{ p }}</a>
                {% endfor %}
                
                {% if page < total_pages %}
                    <a href="{{ url_for('activity_logs', page=page+1) }}">Next &raquo;</a>
                {% endif %}
            </div>
        </div>
    </div>
</body>
</html>
    ''', activities=activities, page=page, total_pages=total_pages)

if __name__ == '__main__':

    app.run(host='0.0.0.0', port=8080)
