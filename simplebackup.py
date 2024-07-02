import json
import math
import subprocess
import time
from datetime import datetime, timedelta
from croniter import croniter
from win10toast import ToastNotifier
import argparse
import os
import sys
import logging

def load_config(config_file):
    """Load and parse the JSON configuration file."""
    with open(config_file, 'r') as f:
        return json.load(f)

def log_error(jobname, error_message):
    """Log an error message to a file."""
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

def cleanup_old_logs():
    """Clean up log files older than 2 months."""
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

def send_notification(title, message):
    """Send a Windows notification with the given title and message."""
    toaster = ToastNotifier()
    toaster.show_toast(title, message, duration=10)

def human_readable_size(size_bytes):
    """Convert size in bytes to a human-readable format"""
    if size_bytes == 0:
        return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"

def run_backup(job):
    """Execute a backup job and handle notifications."""
    sources = job['sources']
    destination = job['destination']
    password = job['password']
    jobname = job['jobname']
    exclude_patterns = job.get('exclude_patterns', [])
    webdav_user = job.get('webdav_user', '')
    webdav_password = job.get('webdav_password', '')
    use_rclone = job.get('use_rclone', False)

    print(f"Starting backup job: {jobname}")
    
    env = {
        'RESTIC_PASSWORD': password,
        'RESTIC_REPOSITORY': destination
    }

    # If WebDAV credentials are provided, set them in the environment
    if webdav_user and webdav_password:
        env['WEBDAV_USERNAME'] = webdav_user
        env['WEBDAV_PASSWORD'] = webdav_password

    try:
        # Initialize the repository if using rclone with WebDAV
        if use_rclone:
            rclone_dest = f"webdav:{destination}"
            env['RESTIC_REPOSITORY'] = rclone_dest

        # Check if repository exists before initializing
        check_repo_command = ['restic', 'snapshots']
        check_process = subprocess.run(check_repo_command, env=env, capture_output=True, text=True)
        
        if check_process.returncode != 0 and "unable to open config file" in check_process.stderr:
            # Repository doesn't exist, so initialize it
            init_process = subprocess.run(['restic', 'init'], env=env, capture_output=True, text=True, check=True)
            print(f"Initialized new repository for job: {jobname}")
        elif check_process.returncode != 0:
            # Some other error occurred
            raise subprocess.CalledProcessError(check_process.returncode, check_process.args, check_process.stderr)
        else:
            print(f"Using existing repository for job: {jobname}")

        # Run backup for each source
        total_files = 0
        total_size = 0

        for source in sources:
            print(f"Backing up source: {source}")
            
            # Construct the restic command with exclude patterns
            restic_command = ['restic', 'backup', source, '--json']
            for pattern in exclude_patterns:
                restic_command.extend(['--exclude', pattern])

            process = subprocess.Popen(
                restic_command,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )

            # Process backup progress
            last_progress = ""
            while True:
                output = process.stdout.readline()
                if output == '' and process.poll() is not None:
                    break
                if output:
                    try:
                        data = json.loads(output.strip())
                        if data['message_type'] == 'status':
                            total_files += data.get('total_files', 0)
                            total_size += data.get('total_bytes', 0)
                            percent_done = data.get('percent_done', 0) * 100  # Convert to percentage
                            bytes_done = data.get('bytes_done', 0)
                            total_bytes = data.get('total_bytes', 0)
                            progress = (f"\rSource: {source}, "
                                        f"Files: {data.get('files_done', 'N/A')}/{data.get('total_files', 'N/A')}, "
                                        f"Size: {human_readable_size(bytes_done)}/{human_readable_size(total_bytes)}, "
                                        f"Progress: {percent_done:.2f}%")
                            if progress != last_progress:
                                sys.stdout.write(progress.ljust(100))  # Pad with spaces to overwrite previous output
                                sys.stdout.flush()
                                last_progress = progress
                    except json.JSONDecodeError:
                        print(output.strip())

            sys.stdout.write('\n')  # Move to the next line after the progress is complete

            # Check for errors
            if process.returncode != 0:
                stderr = process.stderr.read()
                if "no space left on device" in stderr.lower():
                    error_message = f"Job {jobname}: Backup destination is full. Backup failed."
                    send_notification("Backup Destination Full", error_message)
                    log_error(jobname, error_message)
                    raise subprocess.CalledProcessError(process.returncode, process.args, stderr)
                error_message = f"Error in backup job {jobname}: {stderr}"
                log_error(jobname, error_message)
                raise subprocess.CalledProcessError(process.returncode, process.args, stderr)

        # Apply retention policy
        retention_args = []
        if job['retention'].get('hours', 0) > 0:
            retention_args.extend(['--keep-hourly', str(job['retention']['hours'])])
        if job['retention'].get('days', 0) > 0:
            retention_args.extend(['--keep-daily', str(job['retention']['days'])])
        if job['retention'].get('weeks', 0) > 0:
            retention_args.extend(['--keep-weekly', str(job['retention']['weeks'])])
        if job['retention'].get('months', 0) > 0:
            retention_args.extend(['--keep-monthly', str(job['retention']['months'])])
        if job['retention'].get('years', 0) > 0:
            retention_args.extend(['--keep-yearly', str(job['retention']['years'])])

        subprocess.run(['restic', 'forget', '--prune'] + retention_args, env=env, check=True)

        print(f"Backup job completed: {jobname}")
        send_notification("Backup Successful", 
                          f"Job {jobname}: Backup completed successfully.\n"
                          f"Total Files: {total_files}, Total Size: {total_size/1024/1024:.2f} MB")
        return True
    except subprocess.CalledProcessError as e:
        error_message = f"Error in backup job {jobname}:\n"
        error_message += f"Return code: {e.returncode}\n"
        error_message += f"Command: {e.cmd}\n"
        if hasattr(e, 'stdout') and e.stdout:
            error_message += f"stdout: {e.stdout}\n"
        if hasattr(e, 'stderr') and e.stderr:
            error_message += f"stderr: {e.stderr}\n"
        print(error_message)
        log_error(jobname, error_message)
        try:
            send_notification("Backup Failed", f"Job {jobname}: Backup failed. Check error logs for details.")
        except Exception as notify_error:
            print(f"Failed to send notification: {str(notify_error)}")
        return False
    except Exception as e:
        error_message = f"Unexpected error in backup job {jobname}: {str(e)}"
        print(error_message)
        log_error(jobname, error_message)
        try:
            send_notification("Backup Failed", f"Job {jobname}: Backup failed. Check error logs for details.")
        except Exception as notify_error:
            print(f"Failed to send notification: {str(notify_error)}")
        return False
    
def retry_backup(job):
    """Retry a failed backup job with increasing intervals."""
    retry_intervals = [1, 2, 5, 10, 20, 30, 60]  # in minutes
    for interval in retry_intervals:
        print(f"Retrying backup job {job['jobname']} in {interval} minutes...")
        time.sleep(interval * 60)
        if run_backup(job):
            print(f"Retry successful for job {job['jobname']}")
            return True
    print(f"All retries failed for job {job['jobname']}")
    error_message = f"Job {job['jobname']}: All backup retries failed."
    log_error(job['jobname'], error_message)
    send_notification("Backup Retries Exhausted", f"{error_message} Check error logs for details.")
    return False

def get_next_job(config):
    """Determine the next job to run based on the current time and job schedules."""
    now = datetime.now()
    next_job = None
    next_run = None

    for job in config['backupjobs']:
        cron = croniter(job['backup_interval'], now)
        job_next_run = cron.get_next(datetime)
        if next_run is None or job_next_run < next_run:
            next_run = job_next_run
            next_job = job

    return next_job, next_run

def main():
    """Main function to run the backup scheduler."""
    parser = argparse.ArgumentParser(description="SimpleBackup - A Python script for scheduled backups using Restic")
    parser.add_argument("--backup-on-start", action="store_true", help="Perform a backup immediately on start")
    args = parser.parse_args()

    config_file = 'backup_config.json'
    config = load_config(config_file)

    # Clean up old logs on startup
    cleanup_old_logs()

    if args.backup_on_start:
        print("Performing backup on start...")
        for job in config['backupjobs']:
            run_backup(job)
    
    while True:
        # Load the configuration file at each iteration
        config = load_config(config_file)
        next_job, next_run = get_next_job(config)
        
        if next_job is None:
            print("No jobs scheduled. Waiting for 1 minute before checking again.")
            time.sleep(60)
            continue
        
        now = datetime.now()
        wait_time = (next_run - now).total_seconds()
        
        if wait_time > 0:
            print(f"Waiting {wait_time:.2f} seconds for next job: {next_job['jobname']}")
            time.sleep(wait_time)
        
        if not run_backup(next_job):
            retry_backup(next_job)

        # Clean up old logs after each backup job
        cleanup_old_logs()

if __name__ == "__main__":
    main()