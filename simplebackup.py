import json
import math
import subprocess
import time
from datetime import datetime, timedelta
from croniter import croniter
from win10toast import ToastNotifier
import argparse
import sys
import logging
import os
import tempfile

print("Script started")  # Debug output


class BackupJob:
    def __init__(self, config):
        self.jobname = config['jobname']
        self.sources = config['sources']
        self.destination = config['destination']
        self.password = config['password']
        self.exclude_patterns = config.get('exclude_patterns', [])
        self.webdav_user = config.get('webdav_user', '')
        self.webdav_password = config.get('webdav_password', '')
        self.use_rclone = config.get('use_rclone', False)
        self.compression_level = config.get('compression_level', 'auto')
        self.retention = config['retention']
        self.backup_interval = config['backup_interval']

class BackupManager:
    def __init__(self, config_file):
        self.config_file = config_file
        self.jobs = []
        self.load_config()

    def load_config(self):
        with open(self.config_file, 'r') as f:
            config = json.load(f)
        self.jobs = [BackupJob(job_config) for job_config in config['backupjobs']]

    def get_next_job(self):
        now = datetime.now()
        next_job = None
        next_run = None

        for job in self.jobs:
            cron = croniter(job.backup_interval, now)
            job_next_run = cron.get_next(datetime)
            if next_run is None or job_next_run < next_run:
                next_run = job_next_run
                next_job = job

        return next_job, next_run

    def run(self, backup_on_start=False):
        if backup_on_start:
            print("Performing backup on start...")
            for job in self.jobs:
                self.execute_backup(job)

        while True:
            self.load_config()  # Reload config at each iteration
            next_job, next_run = self.get_next_job()

            if next_job is None:
                print("No jobs scheduled. Waiting for 1 minute before checking again.")
                time.sleep(60)
                continue

            now = datetime.now()
            wait_time = (next_run - now).total_seconds()

            if wait_time > 0:
                print(f"Waiting {wait_time:.2f} seconds for next job: {next_job.jobname}")
                time.sleep(wait_time)

            if not self.execute_backup(next_job):
                self.retry_backup(next_job)

            self.cleanup_old_logs()

    def execute_backup(self, job):
        print(f"Starting backup job: {job.jobname}")

        env = os.environ.copy()
        env['RESTIC_PASSWORD'] = job.password

        if job.use_rclone:
            repository, temp_config_path = self.setup_rclone(job, env)
        else:
            repository = f"local:{job.destination}"
            temp_config_path = None

        try:
            self.initialize_repository(repository, env)
            self.run_backup_for_sources(job, repository, env)
            self.apply_retention_policy(job, repository, env)

            print(f"Backup job completed: {job.jobname}")
            self.send_notification("Backup Successful", f"Job {job.jobname}: Backup completed successfully.")
            return True

        except subprocess.CalledProcessError as e:
            self.handle_backup_error(job, e)
            return False

        except Exception as e:
            self.handle_unexpected_error(job, e)
            return False

        finally:
            if temp_config_path:
                os.unlink(temp_config_path)

    def setup_rclone(self, job, env):
        obscured_password = self.obscure_password(job.webdav_password)
        temp_config = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.conf')
        temp_config.write(f"""
[webdav]
type = webdav
url = {job.destination}
vendor = other
user = {job.webdav_user}
pass = {obscured_password}
""")
        temp_config.close()
        env['RCLONE_CONFIG'] = temp_config.name
        return "rclone:webdav:Backups/Restic_Test", temp_config.name

    def initialize_repository(self, repository, env):
        check_repo_command = ['restic', '-r', repository, 'snapshots']
        check_process = subprocess.run(check_repo_command, env=env, capture_output=True, text=True)

        if check_process.returncode != 0 and "unable to open config file" in check_process.stderr:
            subprocess.run(['restic', '-r', repository, 'init'], env=env, capture_output=True, text=True, check=True)
            print(f"Initialized new repository")
        elif check_process.returncode != 0:
            raise subprocess.CalledProcessError(check_process.returncode, check_process.args, check_process.stderr)
        else:
            print(f"Using existing repository")

    def run_backup_for_sources(self, job, repository, env):
        for source in job.sources:
            print(f"Backing up source: {source}")
            restic_command = self.construct_restic_command(job, repository, source)
            self.execute_restic_command(restic_command, env)
            print()  # Add a newline after the progress bar

    def construct_restic_command(self, job, repository, source):
        command = ['restic', '-r', repository, 'backup', source, '--json']
        if job.compression_level != 'auto':
            command.extend(['--compression', job.compression_level])
        for pattern in job.exclude_patterns:
            command.extend(['--exclude', pattern])
        return command

    def execute_restic_command(self, command, env):
        process = subprocess.Popen(
            command,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )

        last_percent = 0
        while True:
            output = process.stdout.readline()
            if output == '' and process.poll() is not None:
                break
            if output:
                self.process_restic_output(output, last_percent)

        if process.returncode != 0:
            stderr = process.stderr.read()
            raise subprocess.CalledProcessError(process.returncode, command, stderr)

    def process_restic_output(self, output, last_percent):
        try:
            data = json.loads(output.strip())
            if data['message_type'] == 'status':
                percent_done = data['percent_done'] * 100
                if percent_done - last_percent >= 1 or percent_done == 100:
                    last_percent = percent_done
                    self.display_progress(data)
        except json.JSONDecodeError:
            print(output.strip())

    def display_progress(self, data):
        percent_done = data['percent_done'] * 100
        files_done = data['files_done']
        total_files = data['total_files']
        bytes_done = self.human_readable_size(data['bytes_done'])
        total_bytes = self.human_readable_size(data['total_bytes'])

        progress = f"\rProgress: {percent_done:6.2f}% | Files: {files_done:4d}/{total_files:4d} | Size: {bytes_done:>8s}/{total_bytes:>8s}"
        sys.stdout.write(progress)
        sys.stdout.flush()

    def apply_retention_policy(self, job, repository, env):
        try:
             # First, list all snapshots
            list_cmd = ['restic', '-r', repository, 'snapshots']
            result = subprocess.run(list_cmd, env=env, check=True, capture_output=True, text=True)
            print("\nCurrent snapshots:")
            print(result.stdout.strip())  # Strip to remove extra newlines

            # Then, keep only the latest snapshot
            forget_cmd = ['restic', '-r', repository, 'forget', '--keep-last', '1', '--prune']
            result = subprocess.run(forget_cmd, env=env, check=True, capture_output=True, text=True)
            print("\nRetention policy applied:")
            print(result.stdout.strip())  # Strip to remove extra newlines

        except subprocess.CalledProcessError as e:
            error_message = f"Error applying retention policy: {e.stderr}"
            print(f"\n{error_message}")
            self.log_error(job.jobname, error_message)

    def print_restic_version(self):
        try:
            version_result = subprocess.run(['restic', 'version'], capture_output=True, text=True, check=True)
            print(f"Restic version: {version_result.stdout.strip()}")

            help_result = subprocess.run(['restic', 'help'], capture_output=True, text=True, check=True)
            print("Available Restic commands:")
            print(help_result.stdout)
        except subprocess.CalledProcessError as e:
            print(f"Error getting Restic information: {e.stderr}")

    def retry_backup(self, job):
        retry_intervals = [1, 2, 5, 10, 20, 30, 60]  # in minutes
        for interval in retry_intervals:
            print(f"Retrying backup job {job.jobname} in {interval} minutes...")
            time.sleep(interval * 60)
            if self.execute_backup(job):
                print(f"Retry successful for job {job.jobname}")
                return True
        print(f"All retries failed for job {job.jobname}")
        error_message = f"Job {job.jobname}: All backup retries failed."
        self.log_error(job.jobname, error_message)
        self.send_notification("Backup Retries Exhausted", f"{error_message} Check error logs for details.")
        return False

    @staticmethod
    def log_error(jobname, error_message):
        logs_dir = os.path.join(os.getcwd(), 'logs')
        os.makedirs(logs_dir, exist_ok=True)

        log_file = os.path.join(logs_dir, f"errorlog_{jobname}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

        logger = logging.getLogger(jobname)
        logger.setLevel(logging.ERROR)

        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.ERROR)

        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)

        logger.addHandler(file_handler)

        logger.error(error_message)
        logger.removeHandler(file_handler)
        file_handler.close()

    @staticmethod
    def send_notification(title, message):
        toaster = ToastNotifier()
        toaster.show_toast(title, message, duration=10, threaded=True)

    @staticmethod
    def human_readable_size(size_bytes):
        if size_bytes == 0:
            return "0B"
        size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_name[i]}"

    @staticmethod
    def obscure_password(password):
        try:
            result = subprocess.run(['rclone', 'obscure', password], capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            print(f"Error obscuring password: {e}")
            return password

    def handle_backup_error(self, job, error):
        error_message = f"Error in backup job {job.jobname}:\n"
        error_message += f"Return code: {error.returncode}\n"
        error_message += f"Command: {error.cmd}\n"
        if error.stdout:
            error_message += f"stdout: {error.stdout}\n"
        if error.stderr:
            error_message += f"stderr: {error.stderr}\n"
        print(error_message)
        self.log_error(job.jobname, error_message)
        self.send_notification("Backup Failed", f"Job {job.jobname}: Backup failed. Check error logs for details.")

    def handle_unexpected_error(self, job, error):
        error_message = f"Unexpected error in backup job {job.jobname}: {str(error)}"
        print(error_message)
        self.log_error(job.jobname, error_message)
        self.send_notification("Backup Failed", f"Job {job.jobname}: Backup failed. Check error logs for details.")

    def cleanup_old_logs(self):
        logs_dir = os.path.join(os.getcwd(), 'logs')
        if not os.path.exists(logs_dir):
            return

        two_months_ago = datetime.now() - timedelta(days=60)

        for filename in os.listdir(logs_dir):
            file_path = os.path.join(logs_dir, filename)
            if os.path.isfile(file_path):
                file_modified = datetime.fromtimestamp(os.path.getmtime(file_path))
                if file_modified < two_months_ago:
                    os.remove(file_path)
                    print(f"Removed old log file: {filename}")

def main():
    print("Entered main function")  # Debug output
    parser = argparse.ArgumentParser(description="SimpleBackup - A Python script for scheduled backups using Restic")
    parser.add_argument("--backup-on-start", action="store_true", help="Perform a backup immediately on start")
    args = parser.parse_args()

    print(f"Arguments parsed: {args}")  # Debug output

    config_file = 'backup_config.json'
    print(f"Loading config from: {config_file}")  # Debug output
    backup_manager = BackupManager(config_file)
    print("BackupManager created")  # Debug output
    backup_manager.run(args.backup_on_start)

if __name__ == "__main__":
    print("Script is being run directly")  # Debug output
    main()
else:
    print("Script is being imported")  # Debug output
