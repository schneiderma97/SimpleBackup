import json
import subprocess
import time
import logging
from datetime import datetime
from croniter import croniter
from win10toast import ToastNotifier
import argparse

def load_config(config_file):
    """Load and parse the JSON configuration file."""
    with open(config_file, 'r') as f:
        return json.load(f)

def setup_logger(jobname):
    """Set up a logger for the given job name."""
    logger = logging.getLogger(jobname)
    logger.setLevel(logging.ERROR)
    
    # Create a unique log file for each job execution
    log_file = f"errorlog_{jobname}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.ERROR)
    
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    return logger

def send_notification(title, message):
    """Send a Windows notification with the given title and message."""
    toaster = ToastNotifier()
    toaster.show_toast(title, message, duration=10)

def run_backup(job, logger):
    """Execute a backup job and handle notifications."""
    sources = job['sources']
    destination = job['destination']
    password = job['password']
    jobname = job['jobname']
    exclude_patterns = job.get('exclude_patterns', [])

    print(f"Starting backup job: {jobname}")
    
    env = {
        'RESTIC_PASSWORD': password,
        'RESTIC_REPOSITORY': destination
    }

    try:
        # Initialize repository if it doesn't exist
        subprocess.run(['restic', 'init'], env=env, check=False)

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
                            print(f"Source: {source}, "
                                  f"Files: {data.get('files_done', 'N/A')}/{data.get('total_files', 'N/A')}, "
                                  f"Size: {data.get('bytes_done', 'N/A')}/{data.get('total_bytes', 'N/A')} bytes, "
                                  f"Progress: {data.get('percent_done', 'N/A')}%")
                    except json.JSONDecodeError:
                        print(output.strip())

            # Check for errors
            if process.returncode != 0:
                stderr = process.stderr.read()
                if "no space left on device" in stderr.lower():
                    send_notification("Backup Destination Full", f"Job {jobname}: Backup destination is full. Backup failed.")
                    raise subprocess.CalledProcessError(process.returncode, process.args, stderr)
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
        error_message = f"Error in backup job {jobname}: {str(e)}"
        print(error_message)
        logger.error(error_message)
        send_notification("Backup Failed", f"Job {jobname}: Backup failed. Check error logs for details.")
        return False

def retry_backup(job, logger):
    """Retry a failed backup job with increasing intervals."""
    retry_intervals = [1, 2, 5, 10, 20, 30, 60]  # in minutes
    for interval in retry_intervals:
        print(f"Retrying backup job {job['jobname']} in {interval} minutes...")
        time.sleep(interval * 60)
        if run_backup(job, logger):
            print(f"Retry successful for job {job['jobname']}")
            return True
    print(f"All retries failed for job {job['jobname']}")
    send_notification("Backup Retries Exhausted", f"Job {job['jobname']}: All backup retries failed. Check error logs for details.")
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

    if args.backup_on_start:
        print("Performing backup on start...")
        for job in config['backupjobs']:
            logger = setup_logger(job['jobname'])
            run_backup(job, logger)
    
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
        
        logger = setup_logger(next_job['jobname'])
        if not run_backup(next_job, logger):
            retry_backup(next_job, logger)

if __name__ == "__main__":
    main()