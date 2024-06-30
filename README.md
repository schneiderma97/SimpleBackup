# SimpleBackup

This Python script automates backups using Restic, providing a flexible and robust solution for managing multiple backup jobs with customizable schedules, retention policies, and exclude patterns.

## Features

- Multiple backup jobs with individual schedules
- Customizable retention policies
- Exclude patterns for ignoring specific files or directories
- Windows notifications for backup status
- Error logging and retry mechanism
- Option to perform backup on start

## Installation

1. Ensure you have Python 3.7 or higher installed on your system.

2. Install Restic by following the instructions on the [official Restic website](https://restic.net/#installation).

3. Clone this repository or download the script and requirements file.

4. Install the required Python packages:

   ```
   pip install -r requirements.txt
   ```

## Configuration

1. Create a `backup_config.json` file in the same directory as the script. Here's an example structure:

   ```json
   {
     "backupjobs": [
       {
         "jobname": "Daily Backup",
         "sources": [
           "/path/to/source1",
           "/path/to/source2",
           "/path/to/source3"
         ],
         "destination": "/path/to/destination",
         "password": "your_restic_password",
         "backup_interval": "0 2 * * *",
         "exclude_patterns": [
           "**/node_modules",
           "**/packages",
           "**/.git",
           "**/*.tmp"
         ],
         "retention": {
           "hours": 24,
           "days": 7,
           "weeks": 4,
           "months": 6,
           "years": 1
         }
       }
     ]
   }
   ```

2. You can add multiple backup jobs to the `backupjobs` array.

3. The `backup_interval` uses cron syntax to specify when the backup should run.

4. The `exclude_patterns` array specifies patterns for files or directories to exclude from the backup.

5. The `retention` object specifies how many snapshots to keep for different time periods. You can include or omit any of the time periods (hours, days, weeks, months, years) as needed.

### Retention Policy

The retention policy determines how long backups are kept. For each time period, Restic will keep the specified number of most recent snapshots:

- `hours`: Keep the most recent hourly snapshots
- `days`: Keep the most recent daily snapshots
- `weeks`: Keep the most recent weekly snapshots
- `months`: Keep the most recent monthly snapshots
- `years`: Keep the most recent yearly snapshots

For example, with the configuration `{"hours": 24, "days": 7, "weeks": 4, "months": 6, "years": 1}`, Restic will keep:

- The last 24 hourly snapshots
- The last 7 daily snapshots
- The last 4 weekly snapshots
- The last 6 monthly snapshots
- The last 1 yearly snapshot

Snapshots that don't fall into any of these categories will be removed.

### Exclude Patterns

Exclude patterns use glob syntax to specify files or directories to exclude from the backup. For example:

- `**/node_modules`: Excludes all `node_modules` directories in any subdirectory
- `**/packages`: Excludes all `packages` directories in any subdirectory
- `**/.git`: Excludes all `.git` directories in any subdirectory
- `**/*.tmp`: Excludes all files with the `.tmp` extension in any subdirectory

You can find more information about Restic's exclude patterns in the [official Restic documentation](https://restic.readthedocs.io/en/stable/040_backup.html#excluding-files).

## Usage

Run the script with:

```
python simplebackup.py
```

To perform a backup immediately on start, use the `--backup-on-start` flag:

```
python simplebackup.py --backup-on-start
```

The script will:

- Read the configuration file at each backup interval.
- Determine the next job to run based on the current time and job schedules.
- Execute the backup job when it's time.
- Apply the retention policy after each successful backup.
- Retry failed backups with increasing intervals.
- Display Windows notifications for important events.

You can modify the `backup_config.json` file at any time, and the changes will take effect without restarting the script.

## Internal Processes

1. **Configuration Loading**: The script reads the `backup_config.json` file at each iteration of the main loop, allowing for dynamic updates to the backup configuration.

2. **Job Scheduling**: The `get_next_job` function determines which job should run next based on the current time and the cron expressions specified for each job.

3. **Backup Execution**: The `run_backup` function performs the following steps:
   - Initializes the Restic repository if it doesn't exist.
   - Runs the Restic backup command for each source, applying exclude patterns.
   - Monitors and displays the backup progress.
   - Applies the retention policy after a successful backup.

4. **Error Handling**: If a backup fails, the script logs the error and sends a Windows notification. It then attempts to retry the backup using increasing time intervals.

5. **Notifications**: The script sends Windows notifications for events such as:
   - Successful backups (including number of files and total size)
   - Failed backups
   - Backup destination full
   - All retry attempts exhausted

6. **Logging**: Error logs are created for each job execution, providing detailed information for troubleshooting.

This script provides a flexible and robust solution for managing multiple Restic backup jobs with customizable schedules, retention policies, and exclude patterns.
