#!/usr/bin/env python3
from flask import Flask, request, jsonify, render_template_string, send_file, url_for
import threading
from datetime import datetime
import zipfile
import io
import json
from jinja2 import Template

app = Flask(__name__)

clients = {}
test_results = {}
test_history = {}
running_tests = False
current_test_name = ''
client_commands = {}
initial_traceroutes_sent = {}

# Embedded HTML templates
index_html = """
<!doctype html>
<html>
<head>
    <title>Connectivity Test Server</title>
    <style>
        /* CSS styles */
        body {
            font-family: Arial, sans-serif;
            background-color: #f0f2f5;
            text-align: center;
        }
        table {
            margin: 0 auto 20px auto;
            border-collapse: collapse;
            width: 80%;
            border-radius: 10px;
            overflow: hidden;
        }
        th, td {
            border: 1px solid #ddd;
            padding: 16px 8px;
            text-align: center;
        }
        th {
            background-color: #4CAF50;
            color: white;
        }
        tr td:first-child {
            background-color: #4CAF50;
            color: white;
            font-weight: bold;
            width: 150px;
        }
        td a {
            text-decoration: none;
            color: black;
        }
        td {
            border-radius: 5px;
            width: 100px;
        }
        button {
            padding: 10px 20px;
            margin: 10px;
            font-size: 16px;
            cursor: pointer;
        }
        #testNameField {
            margin-top: 20px;
        }
        input[type="text"] {
            padding: 8px;
            font-size: 16px;
            width: 200px;
        }
        .green-text {
            color: green;
        }
        .red-text {
            color: red;
        }
        .green-bg {
            background-color: #90EE90;
        }
        .orange-bg {
            background-color: #FFA500;
        }
        .red-bg {
            background-color: #FF6347;
        }
    </style>
</head>
<body>
    <h1>Connectivity Test Server</h1>

    <div id="static-content">
        <!-- Buttons will be rendered here based on server state -->
    </div>

    <div id="dynamic-content">
        <!-- Dynamic content will be loaded here -->
    </div>

    <script>
        function loadContent() {
            fetch('/get_status')
                .then(response => response.text())
                .then(html => {
                    document.getElementById('dynamic-content').innerHTML = html;
                });

            fetch('/get_buttons')
                .then(response => response.text())
                .then(html => {
                    document.getElementById('static-content').innerHTML = html;
                });
        }

        function startTests() {
            fetch('/start_tests', {method: 'POST'}).then(() => {
                loadContent();
            });
        }

        function stopTests() {
            fetch('/stop_tests', {method: 'POST'}).then(() => {
                loadContent();
            });
        }

        function downloadResults() {
            const testName = document.getElementById('testName').value.trim();
            if (testName === '') {
                alert('Please enter a test name.');
                return;
            }
            window.location.href = '/download_results/' + encodeURIComponent(testName);
        }

        function clearData() {
            fetch('/clear_data', {method: 'POST'}).then(() => {
                loadContent();
            });
        }

        // Initial load
        loadContent();
        // Refresh content every 5 seconds
        setInterval(loadContent, 5000);
    </script>
</body>
</html>
"""

status_html = """
{% if clients %}
    <table>
        <tr>
            <th>Node</th>
            {% for hostname in clients|sort %}
            <th>{{ hostname }}</th>
            {% endfor %}
        </tr>
        {% for node1 in clients|sort %}
        <tr>
            <td>{{ node1 }}</td>
            {% for node2 in clients|sort %}
                {% if node1 == node2 %}
                    <td>-</td>
                {% else %}
                    {% set result = test_results.get(node1, {}).get(node2, {'success': 0, 'fail': 0}) %}
                    {% if result.fail == 0 %}
                        <td class="green-bg">
                            <a href="{{ url_for('detailed_results', node1=node1, node2=node2) }}">
                                <span class="green-text">{{ result.success }}</span> /
                                <span class="red-text">{{ result.fail }}</span>
                            </a>
                        </td>
                    {% elif result.fail >= 1 and result.fail <= 5 %}
                        <td class="orange-bg">
                            <a href="{{ url_for('detailed_results', node1=node1, node2=node2) }}">
                                <span class="green-text">{{ result.success }}</span> /
                                <span class="red-text">{{ result.fail }}</span>
                            </a>
                        </td>
                    {% elif result.fail > 5 %}
                        <td class="red-bg">
                            <a href="{{ url_for('detailed_results', node1=node1, node2=node2) }}">
                                <span class="green-text">{{ result.success }}</span> /
                                <span class="red-text">{{ result.fail }}</span>
                            </a>
                        </td>
                    {% else %}
                        <td>
                            <a href="{{ url_for('detailed_results', node1=node1, node2=node2) }}">
                                <span class="green-text">{{ result.success }}</span> /
                                <span class="red-text">{{ result.fail }}</span>
                            </a>
                        </td>
                    {% endif %}
                {% endif %}
            {% endfor %}
        </tr>
        {% endfor %}
    </table>
{% else %}
    <p>No clients registered.</p>
{% endif %}
"""

buttons_html = """
{% if not running_tests and not test_results %}
    <button onclick="startTests()">Start Testing</button>
{% elif running_tests %}
    <button onclick="stopTests()">Stop Testing</button>
{% else %}
    <div id="testNameField">
        <input type="text" id="testName" placeholder="Enter test name" />
        <button onclick="downloadResults()">Download Results</button>
        <button onclick="clearData()">Start Again</button>
    </div>
{% endif %}
"""

detailed_html = """
<!doctype html>
<html>
<head>
    <title>Detailed Results for {{ node1 }} and {{ node2 }}</title>
    <style>
        /* CSS styles */
        body {
            font-family: Arial, sans-serif;
            background-color: #f0f2f5;
            text-align: center;
        }
        table {
            margin: 0 auto 20px auto;
            border-collapse: collapse;
            width: 80%;
            border-radius: 10px;
            overflow: hidden;
        }
        th, td {
            border: 1px solid #ddd;
            padding: 12px;
            text-align: center;
        }
        th {
            background-color: #4CAF50;
            color: white;
        }
        .success {
            color: green;
        }
        .fail {
            color: red;
        }
        a {
            text-decoration: none;
            color: blue;
            font-size: 18px;
        }
        pre {
            text-align: left;
            margin: 20px auto;
            max-width: 80%;
            background-color: #eaeaea;
            padding: 10px;
            overflow: auto;
        }
    </style>
</head>
<body>
    <h1>Detailed Results between {{ node1 }} and {{ node2 }}</h1>
    {% if traceroutes %}
        {% if traceroutes.initial %}
            <h2>Initial Traceroute</h2>
            <pre>{{ traceroutes.initial }}</pre>
        {% endif %}
        {% if traceroutes.additional %}
            <h2>Additional Traceroutes</h2>
            {% for trace in traceroutes.additional %}
                <h3>Timestamp: {{ trace.timestamp }}</h3>
                <pre>{{ trace.output }}</pre>
            {% endfor %}
        {% endif %}
        {% if traceroutes.final %}
            <h2>Final Traceroute</h2>
            <pre>{{ traceroutes.final }}</pre>
        {% endif %}
    {% endif %}
    <table>
        <tr>
            <th>Timestamp</th>
            <th>Result</th>
            <th>Latency (ms)</th>
            <th>Source IP</th>
            <th>Destination IP</th>
        </tr>
        {% for entry in history %}
        <tr>
            <td>{{ entry.timestamp }}</td>
            <td class="{{ 'success' if entry.result == 'Success' else 'fail' }}">{{ entry.result }}</td>
            <td>{{ entry.latency if entry.latency else 'N/A' }}</td>
            <td>{{ entry.source_ip }}</td>
            <td>{{ entry.destination_ip }}</td>
        </tr>
        {% endfor %}
    </table>

    {% if url_for is defined %}
    <a href="{{ url_for('index') }}">Back to Main Page</a>
    {% endif %}
</body>
</html>
"""

html_summary_template = """
<!doctype html>
<html>
<head>
    <title>Test Summary - {{ test_name }}</title>
    <style>
        /* CSS styles */
        body {
            font-family: Arial, sans-serif;
            background-color: #f0f2f5;
            text-align: center;
        }
        h1 {
            margin-top: 20px;
        }
        table {
            margin: 0 auto 20px auto;
            border-collapse: collapse;
            width: 80%;
            border-radius: 10px;
            overflow: hidden;
            background-color: white;
        }
        th, td {
            border: 1px solid #ddd;
            padding: 16px 8px;
            text-align: center;
        }
        th {
            background-color: #4CAF50;
            color: white;
        }
        tr td:first-child {
            font-weight: bold;
        }
        .green-text {
            color: green;
        }
        .red-text {
            color: red;
        }
        .green-bg {
            background-color: #90EE90;
        }
        .orange-bg {
            background-color: #FFA500;
        }
        .red-bg {
            background-color: #FF6347;
        }
    </style>
</head>
<body>
    <h1>Test Summary - {{ test_name }}</h1>
    <h2>Timestamp: {{ timestamp }}</h2>
    {% if clients %}
    <table>
        <tr>
            <th>Node</th>
            {% for hostname in clients|sort %}
            <th>{{ hostname }}</th>
            {% endfor %}
        </tr>
        {% for node1 in clients|sort %}
        <tr>
            <td>{{ node1 }}</td>
            {% for node2 in clients|sort %}
                {% if node1 == node2 %}
                    <td>-</td>
                {% else %}
                    {% set result = test_results.get(node1, {}).get(node2, {'success': 0, 'fail': 0}) %}
                    {% if result.fail == 0 %}
                        <td class="green-bg">
                            <span class="green-text">{{ result.success }}</span> /
                            <span class="red-text">{{ result.fail }}</span>
                        </td>
                    {% elif result.fail >= 1 and result.fail <= 5 %}
                        <td class="orange-bg">
                            <span class="green-text">{{ result.success }}</span> /
                            <span class="red-text">{{ result.fail }}</span>
                        </td>
                    {% elif result.fail > 5 %}
                        <td class="red-bg">
                            <span class="green-text">{{ result.success }}</span> /
                            <span class="red-text">{{ result.fail }}</span>
                        </td>
                    {% else %}
                        <td>
                            <span class="green-text">{{ result.success }}</span> /
                            <span class="red-text">{{ result.fail }}</span>
                        </td>
                    {% endif %}
                {% endif %}
            {% endfor %}
        </tr>
        {% endfor %}
    </table>
    {% else %}
        <p>No clients registered.</p>
    {% endif %}
</body>
</html>
"""

# Route to render the main page
@app.route('/')
def index():
    return render_template_string(index_html, url_for=url_for)

# Route to get dynamic content
@app.route('/get_status')
def get_status():
    return render_template_string(status_html, clients=clients, test_results=test_results, url_for=url_for)

# Route to get the buttons based on the server state
@app.route('/get_buttons')
def get_buttons():
    return render_template_string(buttons_html, running_tests=running_tests, test_results=test_results, url_for=url_for)

# Endpoint for detailed results between two nodes
@app.route('/detailed_results/<node1>/<path:node2>')
def detailed_results(node1, node2):
    key = f"{node1}_{node2}"
    data = test_history.get(key, {'history': [], 'traceroutes': {}})
    history = data['history']
    traceroutes = data.get('traceroutes', {})
    return render_template_string(detailed_html, node1=node1, node2=node2, history=history, traceroutes=traceroutes, url_for=url_for)

# Endpoint for clients to register themselves
@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    hostname = data.get('hostname')
    ip_address = data.get('ip_address')
    if hostname and ip_address:
        clients[hostname] = {'ip_address': ip_address}
        print(f"Client registered: {hostname} ({ip_address})")
        return jsonify({'status': 'registered'})
    else:
        return jsonify({'status': 'error', 'message': 'Invalid data'}), 400

# Endpoint to start connectivity tests
@app.route('/start_tests', methods=['POST'])
def start_tests():
    global running_tests, test_results, test_history, current_test_name
    if test_results:
        return jsonify({'status': 'error', 'message': 'Please download or clear previous test data before starting a new test.'}), 400
    running_tests = True
    test_results.clear()
    test_history.clear()
    current_test_name = ''
    for hostname in clients:
        client_commands[hostname] = {'command': 'start_tests'}
    print("Continuous tests started.")
    return jsonify({'status': 'tests_started'})

# Endpoint to stop connectivity tests
@app.route('/stop_tests', methods=['POST'])
def stop_tests():
    global running_tests
    running_tests = False
    for hostname in clients:
        client_commands[hostname] = {'command': 'stop_tests'}
    print("Tests stopped.")
    return jsonify({'status': 'tests_stopped'})

# Endpoint to clear test data
@app.route('/clear_data', methods=['POST'])
def clear_data():
    global test_results, test_history, current_test_name
    test_results.clear()
    test_history.clear()
    current_test_name = ''
    print("Test data cleared.")
    return jsonify({'status': 'data_cleared'})

# Endpoint for clients to get commands
@app.route('/get_commands', methods=['GET'])
def get_commands():
    hostname = request.args.get('hostname')
    if hostname not in clients:
        print(f"Client {hostname} is not registered. Sending re_register command.")
        return jsonify({'command': 're_register'})
    elif hostname in client_commands:
        command = client_commands.pop(hostname)
        return jsonify(command)
    else:
        return jsonify({'command': None})

# Endpoint for clients to report results
@app.route('/report_results', methods=['POST'])
def report_results():
    data = request.get_json()
    hostname = data.get('hostname')
    results = data.get('results')
    traceroutes = data.get('traceroutes', {})
    if hostname:
        # Process test results
        if results:
            for target, result_info in results.items():
                if hostname not in test_results:
                    test_results[hostname] = {}
                if target not in test_results[hostname]:
                    test_results[hostname][target] = {'success': 0, 'fail': 0}
                # Update counts
                if result_info['result'] == 'Success':
                    test_results[hostname][target]['success'] += 1
                else:
                    test_results[hostname][target]['fail'] += 1
                # Update test history
                key = f"{hostname}_{target}"
                if key not in test_history:
                    test_history[key] = {'history': [], 'traceroutes': {'initial': '', 'additional': [], 'final': ''}}
                test_history[key]['history'].append({
                    'timestamp': result_info['timestamp'],
                    'result': result_info['result'],
                    'latency': result_info.get('latency'),
                    'source_ip': result_info['source_ip'],
                    'destination_ip': result_info['destination_ip']
                })
        # Process traceroutes
        if traceroutes:
            initial_traces = traceroutes.get('initial', {})
            additional_traces = traceroutes.get('additional', {})
            final_traces = traceroutes.get('final', {})
            for target, trace_output in initial_traces.items():
                key = f"{hostname}_{target}"
                if key not in test_history:
                    test_history[key] = {'history': [], 'traceroutes': {'initial': '', 'additional': [], 'final': ''}}
                test_history[key]['traceroutes']['initial'] = trace_output
            for target, trace_output in additional_traces.items():
                key = f"{hostname}_{target}"
                if key not in test_history:
                    test_history[key] = {'history': [], 'traceroutes': {'initial': '', 'additional': [], 'final': ''}}
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                test_history[key]['traceroutes']['additional'].append({
                    'timestamp': timestamp,
                    'output': trace_output
                })
            for target, trace_output in final_traces.items():
                key = f"{hostname}_{target}"
                if key not in test_history:
                    test_history[key] = {'history': [], 'traceroutes': {'initial': '', 'additional': [], 'final': ''}}
                test_history[key]['traceroutes']['final'] = trace_output
        return jsonify({'status': 'results_received'})
    else:
        return jsonify({'status': 'error', 'message': 'Invalid data'}), 400

# Endpoint to download test results
@app.route('/download_results/<test_name>')
def download_results(test_name):
    global test_results, test_history, current_test_name
    # Create a zip file in memory
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w') as zf:
        # Add summary JSON
        summary_data = {
            'test_name': test_name,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'results': test_results
        }
        summary_json = json.dumps(summary_data, indent=4)
        zf.writestr('summary.json', summary_json)
        # Add summary HTML
        summary_html = Template(html_summary_template).render(
            test_name=test_name,
            timestamp=summary_data['timestamp'],
            clients=clients.keys(),
            test_results=test_results
        )
        zf.writestr('summary.html', summary_html)
        # Add detailed results
        for key, data in test_history.items():
            history = data['history']
            traceroutes = data.get('traceroutes', {})
            # Use split with maxsplit=1 to handle underscores in hostnames
            node1, node2 = key.split('_', 1)
            # Generate detailed HTML
            detailed_html_content = Template(detailed_html).render(
                node1=node1,
                node2=node2,
                history=history,
                traceroutes=traceroutes
            )
            zf.writestr(f'detailed_{key}.html', detailed_html_content)
            # Add JSON data
            zf.writestr(f'detailed_{key}.json', json.dumps(history, indent=4))
    memory_file.seek(0)
    return send_file(
        memory_file,
        download_name=f'{test_name}.zip',
        as_attachment=True
    )

# Endpoint for clients to get the list of clients
@app.route('/get_clients', methods=['GET'])
def get_clients():
    return jsonify({'clients': clients})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=50000)