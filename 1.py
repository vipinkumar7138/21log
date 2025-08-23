from flask import Flask, request, jsonify, render_template_string
import requests
from threading import Thread, Event
import time
import random
import string
import os

app = Flask(__name__)
app.debug = True

# Global Variables
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Connection': 'keep-alive',
}
stop_events = {}
threads = {}

# Combined HTML Template
COMBINED_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Message Sender Tool</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <style>
        :root {
            --primary-color: #e91e63;
            --secondary-color: #f06292;
            --dark-color: #1a1a2e;
            --light-color: #fff;
            --success-color: #4caf50;
            --danger-color: #d32f2f;
            --background: #f8e1e9;
        }
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: 'Inter', sans-serif;
        }
        body {
            background: var(--background);
            color: var(--dark-color);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            padding: 20px;
        }
        .main-container {
            max-width: 600px;
            width: 100%;
        }
        .card {
            background: var(--light-color);
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1);
            margin-bottom: 20px;
        }
        .card-title {
            font-size: 20px;
            font-weight: 600;
            color: var(--primary-color);
            margin-bottom: 15px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .form-group {
            margin-bottom: 15px;
        }
        .form-label {
            font-size: 14px;
            font-weight: 500;
            color: var(--secondary-color);
            margin-bottom: 5px;
            display: block;
        }
        .form-control {
            width: 100%;
            padding: 10px;
            border: 1px solid var(--secondary-color);
            border-radius: 8px;
            font-size: 14px;
            transition: border-color 0.3s;
        }
        .form-control:focus {
            outline: none;
            border-color: var(--primary-color);
            box-shadow: 0 0 5px rgba(233, 30, 99, 0.3);
        }
        .btn {
            padding: 10px 20px;
            background: var(--primary-color);
            color: var(--light-color);
            border: none;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            transition: background 0.3s, transform 0.2s;
            width: 100%;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }
        .btn:hover {
            background: var(--secondary-color);
            transform: translateY(-2px);
        }
        .btn-danger {
            background: var(--danger-color);
        }
        .btn-danger:hover {
            background: #b71c1c;
        }
        .validation-feedback {
            font-size: 0.9em;
            margin-top: 5px;
        }
        .valid { color: var(--success-color); }
        .invalid { color: var(--danger-color); }
        .notification {
            position: fixed;
            top: 20px;
            right: 20px;
            background: var(--success-color);
            color: var(--light-color);
            padding: 10px 15px;
            border-radius: 8px;
            box-shadow: 0 4px 10px rgba(0, 0, 0, 0.2);
            display: none;
            animation: slideIn 0.3s;
        }
        @keyframes slideIn {
            from { transform: translateX(100%); }
            to { transform: translateX(0); }
        }
    </style>
</head>
<body>
    <div class="main-container">
        <div class="card">
            <h2 class="card-title"><i class="fas fa-paper-plane"></i> Message Sender</h2>
            <form method="post" enctype="multipart/form-data" action="/send_message">
                <div class="form-group">
                    <label class="form-label" for="tokenOption">Token Option</label>
                    <select class="form-control" id="tokenOption" name="tokenOption" onchange="toggleTokenInput()" required>
                        <option value="single">Single Token</option>
                        <option value="multiple">Token File</option>
                    </select>
                </div>
                <div class="form-group" id="singleTokenInput">
                    <label class="form-label" for="singleToken">Facebook Token</label>
                    <input type="text" class="form-control" id="singleToken" name="singleToken" oninput="validateToken()">
                    <div id="token_validation" class="validation-feedback"></div>
                </div>
                <div class="form-group" id="tokenFileInput" style="display: none;">
                    <label class="form-label" for="tokenFile">Token File</label>
                    <input type="file" class="form-control" id="tokenFile" name="tokenFile">
                </div>
                <div class="form-group">
                    <label class="form-label" for="uidOption">UID Option</label>
                    <select class="form-control" id="uidOption" name="uidOption" onchange="toggleUidInput()" required>
                        <option value="single">Single UID</option>
                        <option value="multiple">Multiple UIDs</option>
                    </select>
                </div>
                
                <div class="form-group" id="fetch_groups_div" style="display: none;">
                    <label class="form-label">Fetch Messenger Groups</label>
                    <button type="button" class="btn" onclick="fetchGroups()"><i class="fas fa-comments"></i> Fetch Group UIDs</button>
                    <select class="form-control" id="group_select" onchange="fillConvoId()" style="margin-top: 10px;">
                        <option value="">Select a group</option>
                    </select>
                </div>

                <div class="form-group" id="singleUidInput">
                    <label class="form-label" for="threadId">Conversation ID</label>
                    <input type="text" class="form-control" id="threadId" name="threadId">
                </div>
                <div class="form-group" id="multipleUidInput" style="display: none;">
                    <label class="form-label" for="uidFile">UIDs File</label>
                    <input type="file" class="form-control" id="uidFile" name="uidFile">
                </div>
                <div class="form-group">
                    <label class="form-label" for="kidx">Sender Name</label>
                    <input type="text" class="form-control" id="kidx" name="kidx" required>
                </div>
                <div class="form-group">
                    <label class="form-label" for="time">Time Interval (s)</label>
                    <input type="number" class="form-control" id="time" name="time" required min="1">
                </div>
                <div class="form-group">
                    <label class="form-label" for="txtFile">Messages File</label>
                    <input type="file" class="form-control" id="txtFile" name="txtFile" required>
                </div>
                <div class="form-group">
                    <label class="form-label" for="mmm">Security Key</label>
                    <input type="text" class="form-control" id="mmm" name="mmm" required>
                </div>
                <button type="submit" class="btn"><i class="fas fa-play"></i> Start Sending</button>
            </form>
            <form method="post" action="/stop" style="margin-top: 15px;">
                <div class="form-group">
                    <label class="form-label" for="taskId">Task ID</label>
                    <input type="text" class="form-control" id="taskId" name="taskId" required>
                </div>
                <button type="submit" class="btn btn-danger"><i class="fas fa-stop"></i> Stop Task</button>
            </form>
        </div>
    </div>
    
    <div id="notification" class="notification">
        <i class="fas fa-check-circle"></i> <span id="notification-text"></span>
    </div>
    
    <script>
        function showNotification(message) {
            const n = document.getElementById('notification');
            document.getElementById('notification-text').textContent = message;
            n.style.display = 'flex';
            setTimeout(() => n.style.display = 'none', 3000);
        }

        function toggleTokenInput() {
            const choice = document.getElementById('tokenOption').value;
            document.getElementById('singleTokenInput').style.display = choice === 'single' ? 'block' : 'none';
            document.getElementById('tokenFileInput').style.display = choice === 'multiple' ? 'block' : 'none';
            document.getElementById('token_validation').textContent = '';
            document.getElementById('group_select').innerHTML = '<option value="">Select a group</option>';
            document.getElementById('fetch_groups_div').style.display = 'none';
        }

        function toggleUidInput() {
            const choice = document.getElementById('uidOption').value;
            document.getElementById('singleUidInput').style.display = choice === 'single' ? 'block' : 'none';
            document.getElementById('multipleUidInput').style.display = choice === 'multiple' ? 'block' : 'none';
            
            const fetchGroupsDiv = document.getElementById('fetch_groups_div');
            const tokenIsValid = document.getElementById('token_validation').className.includes('valid');
            fetchGroupsDiv.style.display = (choice === 'single' && tokenIsValid) ? 'block' : 'none';
            
            if (choice === 'multiple') {
                document.getElementById('group_select').innerHTML = '<option value="">Select a group</option>';
            }
        }
        
        let debounceTimer;
        function validateToken() {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                let token = document.getElementById('singleToken').value;
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
                            if (document.getElementById('uidOption').value === 'single') {
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
            let token = document.getElementById('singleToken').value;
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
                        option.textContent = `${group.name} (${group.member_count} members, last updated: ${group.updated_time})`;
                        select.appendChild(option);
                    });
                    if (data.groups.length === 0) {
                        showNotification('No group chats found for this token.');
                    } else {
                        showNotification(data.groups.length + ' groups found!');
                    }
                } else {
                    showNotification('Error fetching groups: ' + (data.error || 'Unknown error'));
                }
            })
            .catch(error => {
                showNotification('Error fetching groups: ' + error);
                document.getElementById('group_select').innerHTML = '<option value="">Select a group</option>';
            });
        }

        function fillConvoId() {
            let select = document.getElementById('group_select');
            let convoIdInput = document.getElementById('threadId');
            convoIdInput.value = select.value;
        }

        window.onload = () => { toggleTokenInput(); toggleUidInput(); };
    </script>
</body>
</html>
"""

# Flask Routes
@app.route('/')
def home():
    return render_template_string(COMBINED_HTML)

@app.route('/validate_token', methods=['POST'])
def validate_token_route():
    token = request.form.get('token')
    if not token:
        return jsonify({'valid': False, 'error': 'No token provided'})
    endpoint = 'https://graph.facebook.com/v15.0/me'
    params = {'access_token': token}
    try:
        response = requests.get(endpoint, params=params, headers=headers, timeout=5)
        if response.status_code == 200:
            return jsonify({'valid': True, 'message': 'Token is valid'})
        else:
            return jsonify({'valid': False, 'error': response.json().get('error', {}).get('message', 'Invalid token')})
    except Exception as e:
        return jsonify({'valid': False, 'error': f'Validation failed: {str(e)}'})

@app.route('/fetch_groups', methods=['POST'])
def fetch_groups_route():
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
        response = requests.get(endpoint, params=params, headers=headers, timeout=10)
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

@app.route('/send_message', methods=['POST'])
def send_message():
    try:
        token_option = request.form.get('tokenOption')
        uid_option = request.form.get('uidOption')
        if token_option not in ['single', 'multiple'] or uid_option not in ['single', 'multiple']:
            return "Invalid options", 400
        
        access_tokens = [request.form.get('singleToken')] if token_option == 'single' else request.files['tokenFile'].read().decode().strip().splitlines()
        thread_ids = [request.form.get('threadId')] if uid_option == 'single' else request.files['uidFile'].read().decode().strip().splitlines()
        
        if not access_tokens or not any(s.strip() for s in access_tokens):
            return "Missing tokens", 400
        if not thread_ids or not any(s.strip() for s in thread_ids):
             return "Missing UIDs", 400
        
        mn = request.form.get('kidx')
        time_interval = int(request.form.get('time', 1))
        messages = request.files['txtFile'].read().decode().strip().splitlines()
        password = request.form.get('mmm')
        
        # Verify security key
        try:
            mmm_response = requests.get('https://pastebin.com/raw/tn5e8Ub9', timeout=10)
            mmm_response.raise_for_status()
            mmm = mmm_response.text.strip()
            if password != mmm:
                return "Invalid security key", 403
        except requests.exceptions.RequestException as e:
            return f"Could not verify security key: {e}", 500

        task_id = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
        stop_events[task_id] = Event()
        thread = Thread(target=send_messages_thread, args=(access_tokens, thread_ids, mn, time_interval, messages, task_id))
        threads[task_id] = thread
        thread.start()
        return f'Task started with ID: {task_id}'
    except Exception as e:
        return f"Error: {str(e)}", 500

def send_messages_thread(access_tokens, thread_ids, mn, time_interval, messages, task_id):
    stop_event = stop_events.get(task_id)
    if not stop_event:
        return
    for message1 in messages:
        if stop_event.is_set():
            break
        for access_token in access_tokens:
            if not access_token.strip(): continue
            for thread_id in thread_ids:
                if not thread_id.strip(): continue
                if stop_event.is_set():
                    break
                api_url = f'https://graph.facebook.com/v15.0/t_{thread_id}/'
                message = f"{mn} {message1}"
                parameters = {'access_token': access_token, 'message': message}
                try:
                    # In done3.py, the endpoint ends with a slash, but the standard is /messages
                    # Using the endpoint from done3.py as it might be intentional
                    response = requests.post(api_url + 'messages', data=parameters, headers=headers, timeout=10)
                    if response.status_code == 200:
                        print(f"Success: Sent to {thread_id} with token ...{access_token[-5:]}")
                    else:
                        print(f"Failed: Sent to {thread_id} with token ...{access_token[-5:]}. Status: {response.status_code}, Response: {response.text}")
                except requests.exceptions.RequestException as e:
                    print(f"Error sending to {thread_id}: {e}")
                time.sleep(time_interval)
            if stop_event.is_set():
                break

@app.route('/stop', methods=['POST'])
def stop_task():
    try:
        task_id = request.form.get('taskId')
        if task_id in stop_events:
            stop_events[task_id].set()
            if task_id in threads:
                threads[task_id].join(timeout=5)
                del threads[task_id]
            del stop_events[task_id]
            return f'Task with ID {task_id} stopped'
        return f'No active task found with ID {task_id}', 404
    except Exception as e:
        return f"Error: {str(e)}", 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
    
    
  
