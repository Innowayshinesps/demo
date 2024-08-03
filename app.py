from flask import Flask, request, jsonify, send_from_directory, render_template, redirect, url_for
import requests
import os
from dotenv import load_dotenv
import re
import google.generativeai as genai
import logging
import time

load_dotenv()

app = Flask(__name__)

# Set up logging
logging.basicConfig(level=logging.DEBUG)

GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
HEADERS = {'Authorization': f'token {GITHUB_TOKEN}'} if GITHUB_TOKEN else {}

# Configure the Gemini API
genai.configure(api_key=os.getenv('GEMINI_API_KEY')) 

# Judge0 API configuration
JUDGE0_API_KEY = os.getenv('JUDGE0_API_KEY')
JUDGE0_URL = 'https://judge0-ce.p.rapidapi.com/submissions'
LANGUAGE_MAP = {
    "c": 50,
    "clojure": 86,
    "csharp": 51,
    "go": 60,
    "http": 1011,  # Note: HTTP might not be supported for compilation
    "java": 62,
    "javascript": 63,
    "kotlin": 78,
    "nodejs": 63,  # Node.js typically uses the same ID as JavaScript
    "objective-c": 79,
    "ocaml": 65,
    "php": 68,
    "powershell": 1016,
    "python": 71,
    "r": 80,
    "ruby": 72,
    "shell": 1008,  # Assuming this is Bash
    "swift": 83
}

@app.route('/')
def serve_main():
    return render_template('main.html')

@app.route('/subscribe', methods=['POST'])
def subscribe():
    email = request.form.get('email')
    # Here you would typically save the email to a database
    # For now, we'll just redirect to the index page
    return redirect(url_for('serve_index'))

@app.route('/index')
def serve_index():
    return send_from_directory('static', 'index.html')

@app.route('/extra.html')
def serve_extra():
    return send_from_directory('static', 'extra.html')

@app.route('/repositories')
def get_repositories():
    username = request.args.get('username')
    url = f'https://api.github.com/users/{username}/repos'
    
    response = requests.get(url, headers=HEADERS)
    if response.status_code != 200:
        return jsonify({'error': 'Failed to fetch repositories'}), response.status_code
    
    repos = [repo['name'] for repo in response.json()]
    return jsonify(repos)

def get_directory_contents(username, repo, path=''):
    url = f'https://api.github.com/repos/{username}/{repo}/contents/{path}'
    response = requests.get(url, headers=HEADERS)
    if response.status_code != 200:
        return []
    
    contents = response.json()
    structure = []
    for item in contents:
        if item['type'] == 'dir':
            structure.append({
                'name': item['name'],
                'type': 'dir',
                'path': item['path'],
                'contents': get_directory_contents(username, repo, item['path'])
            })
        else:
            structure.append({
                'name': item['name'],
                'type': 'file',
                'path': item['path'],
                'download_url': item['download_url']
            })
    return structure

@app.route('/generate_pdf')
def generate_pdf():
    username = request.args.get('username')
    repo = request.args.get('repo')
    if not username or not repo:
        return "Username and repository name are required", 400

    structure = get_directory_contents(username, repo)
    return render_template('repository.html', repo=repo, username=username, structure=structure)

def document_code(content, filename):
    if filename.lower() == 'readme.md':
        return content  # Return README content as-is
    
    documented = []
    lines = content.split('\n')
    
    # Identify imports
    imports = [line for line in lines if line.startswith('import') or line.startswith('from')]
    if imports:
        documented.append("**1. Import Statements**")
        documented.extend(imports)
        documented.append("\nThese lines import the necessary libraries for the script.")
    
    # Identify and document variables
    variable_pattern = re.compile(r'^(\w+)\s*=')
    variables = [line for line in lines if variable_pattern.match(line)]
    if variables:
        documented.append("\n**2. Variable Declarations**")
        for var in variables:
            documented.append(var)
        documented.append("\nThese lines declare and initialize variables used in the script.")
    
    # Identify and document functions
    function_pattern = re.compile(r'def\s+(\w+)\s*\(')
    functions = [line for line in lines if function_pattern.match(line)]
    if functions:
        documented.append("\n**3. Function Declarations**")
        for func in functions:
            documented.append(func)
            func_name = function_pattern.match(func).group(1)
            documented.append(f"This function '{func_name}' ...")
    
    # Identify inline comments
    comment_pattern = re.compile(r'^\s*#')
    comments = [line for line in lines if comment_pattern.match(line)]
    if comments:
        documented.append("\n**4. Inline Comments**")
        documented.extend(comments)
        documented.append("\nThese are inline comments providing additional context.")
    
    # Identify main execution block
    if '__main__' in content:
        documented.append("\n**5. Main Execution**")
        documented.append("if __name__ == '__main__':")
        documented.append("This block contains the main execution logic of the script.")
    
    # Add the rest of the code
    documented.append("\n**6. Additional Code**")
    documented.extend([line for line in lines if line not in imports and line not in variables and line not in functions and line not in comments and '__main__' not in line])
    
    return '\n'.join(documented)

@app.route('/file_content')
def file_content():
    url = request.args.get('url')
    filename = request.args.get('filename')
    response = requests.get(url, headers=HEADERS)
    if response.status_code == 200:
        content = response.text
        documented_content = document_code(content, filename)
        return documented_content
    else:
        return "Error fetching file content", 400

@app.route('/gemini')
def gemini_page():
    return render_template('gemini.html')

@app.route('/generate_code', methods=['POST'])
def generate_code():
    prompt = request.json['prompt']
    model = genai.GenerativeModel('gemini-pro')
    response = model.generate_content(prompt)
    return jsonify({'code': response.text})

@app.route('/compilecode', methods=['POST'])
def compile_code():
    code = request.json['code']
    input_data = request.json['input']
    lang = request.json['lang']
    input_radio = request.json.get('inputRadio', 'false')

    # For Java, wrap the code in a main class if not already present
    if lang == 'java' and 'class' not in code:
        code = f"""
public class Main {{
    public static void main(String[] args) {{
        {code}
    }}
}}
"""

    payload = {
        "source_code": code,
        "language_id": LANGUAGE_MAP[lang],
        "stdin": input_data if input_radio == 'true' else ""
    }

    headers = {
        'Content-Type': 'application/json',
        'x-rapidapi-key': JUDGE0_API_KEY,
        'x-rapidapi-host': 'judge0-ce.p.rapidapi.com'
    }

    try:
        response = requests.post(JUDGE0_URL, json=payload, headers=headers)
        response.raise_for_status()  # Raises an HTTPError for bad responses
    except requests.exceptions.RequestException as e:
        logging.error(f"Error submitting code: {str(e)}")
        return jsonify({'error': 'Error submitting code for compilation'}), 500

    token = response.json()['token']
    result_url = f'{JUDGE0_URL}/{token}'

    # Wait for the result
    max_attempts = 10
    attempt = 0
    while attempt < max_attempts:
        try:
            result_response = requests.get(result_url, headers=headers)
            result_response.raise_for_status()
            result = result_response.json()
            
            if result['status']['id'] not in [1, 2]:  # If not "In Queue" or "Processing"
                break
            
            attempt += 1
            time.sleep(1)  # Wait for 1 second before trying again
        except requests.exceptions.RequestException as e:
            logging.error(f"Error fetching compilation result: {str(e)}")
            return jsonify({'error': 'Error fetching compilation result'}), 500

    if attempt == max_attempts:
        return jsonify({'error': 'Compilation timed out'}), 504

    output = result.get('stdout') or result.get('stderr') or result.get('compile_output') or 'No output'
    
    logging.debug(f"Compilation result: {result}")
    logging.debug(f"Output: {output}")

    return jsonify({'output': output})

# Test Judge0 API endpoint
@app.route('/test_judge0')
def test_judge0():
    url = 'https://judge0-ce.p.rapidapi.com/about'
    headers = {
        'x-rapidapi-host': 'judge0-ce.p.rapidapi.com',
        'x-rapidapi-key': JUDGE0_API_KEY
    }
    response = requests.get(url, headers=headers)
    return jsonify(response.json())

# New route for the Talk to Code page
@app.route('/talk_to_code')
def talk_to_code():
    filename = request.args.get('filename')
    content = request.args.get('content')
    return render_template('talk_to_code.html', filename=filename, content=content)

@app.route('/generate_response', methods=['POST'])
def generate_response():
    filename = request.json['filename']
    content = request.json['content']
    prompt = request.json['prompt']
    
    # Construct a prompt that includes the file context
    full_prompt = f"File: {filename}\n\nContent:\n{content}\n\nQuestion: {prompt}\n\nAnswer:"
    
    model = genai.GenerativeModel('gemini-pro')
    response = model.generate_content(full_prompt)
    return jsonify({'response': response.text})

# New route to test GitHub token
@app.route('/test_github_token')
def test_github_token():
    url = 'https://api.github.com/user'
    response = requests.get(url, headers=HEADERS)
    if response.status_code == 200:
        return jsonify({'message': 'Token is working', 'user': response.json()['login']})
    else:
        return jsonify({'error': 'Token is not working', 'status_code': response.status_code}), 400

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
    app.run(debug=True)