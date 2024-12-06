#!/usr/bin/env python3
import requests
import time
import subprocess
import re
import threading
import traceback
import logging

SERVER_URL = 'http://172.17.0.1:50000'

class NetworkTester:
    def __init__(self):
        self.hostname = self.get_hostname()
        self.ip_address = self.get_ip_address()
        self.initial_traceroutes_sent = False
        self.running_tests = False
        self.server_available = True
        self.session = requests.Session()
        # Dictionaries to keep track of state per target
        self.previous_state = {}  # Stores the previous ping result ('Success' or 'Fail') for each target
        self.traceroute_run = {}  # Indicates whether a traceroute has been run after the last state change for each target
        # Configure logging
        logging.basicConfig(level=logging.INFO,
                            format='%(asctime)s [%(levelname)s] %(message)s')

    def get_hostname(self):
        with open('/proc/sys/kernel/hostname', 'r') as f:
            return f.read().strip()
    
    def get_ip_address(self):
        result = subprocess.run(['hostname', '-I'], stdout=subprocess.PIPE)
        output = result.stdout.decode().strip()
        if output:
            return output.split()[0]
        else:
            return None
    
    def register(self):
        url = SERVER_URL + '/register'
        data = {'hostname': self.hostname, 'ip_address': self.ip_address}
        while True:
            try:
                response = self.session.post(url, json=data, timeout=5)
                if response.status_code == 200:
                    logging.info('Registered with server')
                    break
                else:
                    time.sleep(5)
            except Exception as e:
                logging.error(f"Error registering with server: {e}")
                time.sleep(5)
    
    def get_commands(self):
        url = SERVER_URL + '/get_commands'
        params = {'hostname': self.hostname}
        try:
            response = self.session.get(url, params=params, timeout=5)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logging.error(f"Error getting commands: {e}")
        return None
    
    def get_clients(self):
        url = SERVER_URL + '/get_clients'
        try:
            response = self.session.get(url, timeout=5)
            if response.status_code == 200:
                return response.json().get('clients')
        except Exception as e:
            logging.error(f"Error getting clients: {e}")
        return None
    
    def ping_host(self, target_ip):
        result = subprocess.run(['ping', '-c', '1', '-W', '0.8', target_ip],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output = result.stdout.decode()
        match = re.search(r'time=(\d+\.\d+)', output)
        latency = float(match.group(1)) if match else None
        return result.returncode == 0, latency
    
    def traceroute(self, target_ip):
        result = subprocess.run(['traceroute', '-n', '-w', '1', '-q', '1', target_ip],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return result.stdout.decode()
    
    def perform_tests(self, clients):
        source_ip = self.ip_address
        results = {}
        threads = []
        thread_results = {}
        traceroutes = {}
        initial_traceroutes = {}

        data_lock = threading.Lock()

        def ping_target(target_hostname, target_ip):
            success, latency = self.ping_host(target_ip)
            result = 'Success' if success else 'Fail'

            with data_lock:
                thread_results[target_hostname] = {
                    'result': result,
                    'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
                    'latency': latency,
                    'source_ip': source_ip,
                    'destination_ip': target_ip
                }

                # Initialize previous_state and traceroute_run if not already set
                if target_hostname not in self.previous_state:
                    self.previous_state[target_hostname] = result
                    self.traceroute_run[target_hostname] = False
                else:
                    if result != self.previous_state[target_hostname]:
                        # State has changed
                        if not self.traceroute_run[target_hostname]:
                            # Run additional traceroute
                            trace_output = self.traceroute(target_ip)
                            if 'additional' not in traceroutes:
                                traceroutes['additional'] = {}
                            traceroutes['additional'][target_hostname] = trace_output
                            # Set traceroute_run to True
                            self.traceroute_run[target_hostname] = True
                        # Update previous state
                        self.previous_state[target_hostname] = result
                    else:
                        # State hasn't changed
                        # Reset traceroute_run to False to allow traceroute on next state change
                        self.traceroute_run[target_hostname] = False

        # Perform initial traceroutes once
        if not self.initial_traceroutes_sent:
            initial_traceroutes = {}
            for target_hostname, info in clients.items():
                if target_hostname == self.hostname:
                    continue
                target_ip = info['ip_address']
                trace_output = self.traceroute(target_ip)
                initial_traceroutes[target_hostname] = trace_output
            self.initial_traceroutes_sent = True

        # Start ping tests
        for target_hostname, info in clients.items():
            if target_hostname == self.hostname:
                continue
            target_ip = info['ip_address']
            t = threading.Thread(target=ping_target, args=(target_hostname, target_ip))
            threads.append(t)
            t.start()

        # Wait for all threads to complete
        for t in threads:
            t.join()

        # Collect results
        results.update(thread_results)
        return results, initial_traceroutes, traceroutes
    
    def report_results(self, results, initial_traceroutes, traceroutes):
        url = SERVER_URL + '/report_results'
        data = {
            'hostname': self.hostname,
            'results': results,
            'traceroutes': {}
        }
        # Send initial traceroutes only once
        if initial_traceroutes:
            data['traceroutes']['initial'] = initial_traceroutes
        if traceroutes:
            # Merge traceroutes into data['traceroutes']
            data['traceroutes'].update(traceroutes)
        try:
            response = self.session.post(url, json=data, timeout=5)
            if response.status_code == 200:
                return True
        except Exception as e:
            logging.error(f"Error reporting results: {e}")
        return False
    
    def main_loop(self):
        self.register()
        while True:
            if self.server_available:
                try:
                    command_data = self.get_commands()
                    if command_data:
                        command = command_data.get('command')
                    else:
                        command = None
                    if command == 'start_tests':
                        if not self.running_tests:
                            logging.info('Testing started...')
                            self.running_tests = True
                            self.initial_traceroutes_sent = False
                            # Reset state tracking dictionaries
                            self.previous_state = {}
                            self.traceroute_run = {}
                    elif command == 'stop_tests':
                        if self.running_tests:
                            logging.info('Testing stopped.')
                            self.running_tests = False
                            # Run another traceroute to include at the end of the ping test in detailed reports
                            clients = self.get_clients()
                            if clients is not None and len(clients) > 1:
                                # Run traceroutes to all clients
                                final_traceroutes = {}
                                for target_hostname, info in clients.items():
                                    if target_hostname == self.hostname:
                                        continue
                                    target_ip = info['ip_address']
                                    trace_output = self.traceroute(target_ip)
                                    final_traceroutes[target_hostname] = trace_output
                                # Report the final traceroutes
                                self.report_results({}, {}, {'final': final_traceroutes})
                            else:
                                logging.info('No clients available for final traceroute at stop_tests command.')
                    elif command == 're_register':
                        logging.info('Received re_register command. Re-registering with server...')
                        self.register()
                    if self.running_tests:
                        clients = self.get_clients()
                        if clients is not None and len(clients) > 1:
                            results, initial_traceroutes, traceroutes = self.perform_tests(clients)
                            success = self.report_results(results, initial_traceroutes, traceroutes)
                            if not success:
                                logging.error('Server unreachable. Stopping tests and attempting to re-register...')
                                self.running_tests = False
                                self.server_available = False
                        else:
                            logging.error('No clients available. Stopping tests and attempting to re-register...')
                            self.running_tests = False
                            self.server_available = False
                        time.sleep(0.5)
                    else:
                        time.sleep(1)
                except Exception as e:
                    logging.error('An error occurred in main loop.')
                    logging.error(f"Exception: {e}")
                    traceback.print_exc()
                    logging.error('Server unreachable. Stopping tests and attempting to re-register...')
                    self.running_tests = False
                    self.server_available = False
            else:
                # Try to re-register with the server
                try:
                    self.register()
                    self.server_available = True
                except Exception as e:
                    logging.error(f"Error re-registering with server: {e}")
                    time.sleep(5)

def main():
    tester = NetworkTester()
    tester.main_loop()

if __name__ == '__main__':
    main()